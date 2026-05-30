from __future__ import annotations

import json

import httpx
from contentops_core.generator import ContentGenerator
from contentops_core.models import ContentPlan, Draft, ResearchPacket


class OpenAIResponsesGenerator:
    """OpenAI Responses API draft generator.

    The template generator remains the default so local development and CI do not require keys.
    Enable this provider with `CONTENTOPS_GENERATOR_PROVIDER=openai`.
    """

    def __init__(self, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback = ContentGenerator()

    def generate(self, packet: ResearchPacket, plan: ContentPlan) -> Draft:
        prompt = self._build_prompt(packet, plan)
        payload = {
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
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        markdown = self._extract_text(response.json()).strip()
        if not markdown:
            return self.fallback.generate(packet, plan)
        html = self.fallback._markdown_to_html(plan.title, markdown)
        return Draft(title=plan.title, slug=plan.slug, markdown=markdown, html=html)

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
