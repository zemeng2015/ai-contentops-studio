from __future__ import annotations

import json
import time

import httpx
from contentops_core.generator import ContentGenerator
from contentops_core.models import ContentPlan, Draft, GenerationReceipt, ResearchPacket


class OpenAIResponsesGenerator:
    """OpenAI Responses API draft generator.

    The template generator remains the default so local development and CI do not require keys.
    Enable this provider with `CONTENTOPS_GENERATOR_PROVIDER=openai`.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.5,
        fallback_on_failure: bool = True,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.fallback_on_failure = fallback_on_failure
        self.fallback = ContentGenerator()
        self._last_receipt: GenerationReceipt | None = None

    def generate(self, packet: ResearchPacket, plan: ContentPlan) -> Draft:
        prompt = self._build_prompt(packet, plan)
        payload: dict[str, object] = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are an applied AI engineering editor. Generate source-grounded "
                        "technical content with concrete architecture judgment. Do not invent "
                        "facts beyond the provided research packet."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response, attempts = self._post_with_retries(client, payload)
        except Exception as exc:
            if self.fallback_on_failure:
                draft = self.fallback.generate(packet, plan)
                self._last_receipt = GenerationReceipt(
                    provider="openai",
                    model=self.model,
                    status="fallback",
                    attempts=max(self.retry_attempts, 1),
                    fallback_used=True,
                    error=str(exc),
                )
                return draft
            raise
        response_json = response.json()
        markdown = self._extract_text(response_json).strip()
        if not markdown:
            draft = self.fallback.generate(packet, plan)
            self._last_receipt = GenerationReceipt(
                provider="openai",
                model=self.model,
                status="fallback",
                attempts=attempts,
                fallback_used=True,
                error="OpenAI response did not include output text.",
            )
            return draft
        html = self.fallback._markdown_to_html(plan.title, markdown)
        usage = self._extract_usage(response_json)
        self._last_receipt = GenerationReceipt(
            provider="openai",
            model=self.model,
            status="completed",
            attempts=attempts,
            fallback_used=False,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        return Draft(title=plan.title, slug=plan.slug, markdown=markdown, html=html)

    def generation_receipt(self) -> GenerationReceipt | None:
        return self._last_receipt

    def _post_with_retries(
        self,
        client: httpx.Client,
        payload: dict[str, object],
    ) -> tuple[httpx.Response, int]:
        attempts = max(self.retry_attempts, 1)
        for attempt in range(attempts):
            try:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                return response, attempt + 1
            except Exception as exc:
                if attempt == attempts - 1 or not _is_retryable_openai_error(exc):
                    raise
                delay = max(self.retry_backoff_seconds, 0) * (2**attempt)
                if delay:
                    time.sleep(delay)
        raise RuntimeError("OpenAI Responses API request failed")

    @staticmethod
    def _extract_text(response_json: dict[str, object]) -> str:
        output_text = response_json.get("output_text")
        if isinstance(output_text, str):
            return output_text
        chunks: list[str] = []
        output = response_json.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for content_item in content:
                    if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                        chunks.append(content_item["text"])
        return "\n".join(chunks)

    @staticmethod
    def _extract_usage(response_json: dict[str, object]) -> dict[str, int]:
        usage = response_json.get("usage")
        if not isinstance(usage, dict):
            return {}
        result: dict[str, int] = {}
        for output_key, input_key in {
            "input_tokens": "input_tokens",
            "output_tokens": "output_tokens",
            "total_tokens": "total_tokens",
        }.items():
            value = usage.get(input_key)
            if isinstance(value, int):
                result[output_key] = value
        return result

    @staticmethod
    def _build_prompt(packet: ResearchPacket, plan: ContentPlan) -> str:
        return (
            "Create a publishable Markdown technical article.\n\n"
            f"Title: {plan.title}\n"
            f"Audience: {plan.audience}\n"
            f"Thesis: {plan.thesis}\n"
            f"Outline: {json.dumps(plan.outline, ensure_ascii=False)}\n\n"
            "Research packet:\n"
            f"{packet.model_dump_json(indent=2)}\n\n"
            "Requirements:\n"
            "- Use Markdown headings.\n"
            "- Include a Sources section.\n"
            "- Reference source titles when making claims.\n"
            "- Include a section on portfolio/project implications.\n"
            "- Keep the tone practical and engineering-focused.\n"
        )


def _is_retryable_openai_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or status_code >= 500
    return isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            httpx.TimeoutException,
            httpx.TransportError,
        ),
    )
