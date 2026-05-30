from __future__ import annotations

from html import escape

from contentops_core.models import ContentPlan, Draft, ResearchPacket


class ContentGenerator:
    """Template generator used before model providers are connected.

    This keeps the system useful and testable without API keys. A future LLM generator can
    implement the same interface and still write the same artifacts.
    """

    def generate(self, packet: ResearchPacket, plan: ContentPlan) -> Draft:
        sections = [
            f"# {plan.title}",
            "",
            f"**Audience:** {plan.audience}",
            "",
            f"**Thesis:** {plan.thesis}",
            "",
            "## Why this matters",
            (
                "The useful version of AI automation is not a single clever prompt. It is a "
                "workflow with boundaries: research produces artifacts, planning chooses the "
                "angle, generation creates a draft, evaluation gates quality, and publishing "
                "records the final state."
            ),
            "",
            "## Engineering signals",
            *[f"- {signal}" for signal in packet.engineering_signals],
            "",
            "## Source-backed claims",
            *[f"- {claim.text} Source: {claim.source_title}." for claim in packet.claims],
            "",
            "## Risks and controls",
            *[f"- {risk}" for risk in packet.risks],
            "",
            "## How this changes the portfolio roadmap",
            *[f"- {implication}" for implication in packet.project_implications],
            "",
            "## Sources",
            *[
                f"- {source.title}: {source.summary}"
                + (f" ({source.url})" if source.url else "")
                for source in packet.sources
            ],
            "",
            "## Next build",
            (
                "The next practical step is to turn this analysis into a reusable ContentOps run "
                "that stores research.json, outline.md, draft.md, eval-report.json, and trace.json "
                "for every publication."
            ),
        ]
        markdown = "\n".join(sections)
        html = self._markdown_to_html(plan.title, markdown)
        return Draft(title=plan.title, slug=plan.slug, markdown=markdown, html=html)

    def _markdown_to_html(self, title: str, markdown: str) -> str:
        body: list[str] = []
        in_list = False
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if not line:
                if in_list:
                    body.append("</ul>")
                    in_list = False
                continue
            if line.startswith("# "):
                if in_list:
                    body.append("</ul>")
                    in_list = False
                body.append(f"<h1>{escape(line[2:])}</h1>")
            elif line.startswith("## "):
                if in_list:
                    body.append("</ul>")
                    in_list = False
                body.append(f"<h2>{escape(line[3:])}</h2>")
            elif line.startswith("- "):
                if not in_list:
                    body.append("<ul>")
                    in_list = True
                body.append(f"<li>{escape(line[2:])}</li>")
            else:
                if in_list:
                    body.append("</ul>")
                    in_list = False
                body.append(f"<p>{escape(line)}</p>")
        if in_list:
            body.append("</ul>")
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{escape(title)}</title>"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<style>body{font-family:Inter,system-ui,sans-serif;max-width:880px;margin:48px auto;"
            "padding:0 24px;line-height:1.6;color:#18201e}h1{font-size:44px;line-height:1.05}"
            "h2{margin-top:36px}li{margin:8px 0}</style></head><body>"
            + "\n".join(body)
            + "</body></html>"
        )

