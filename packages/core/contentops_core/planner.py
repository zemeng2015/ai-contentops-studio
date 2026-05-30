from __future__ import annotations

from slugify import slugify

from contentops_core.models import ContentPlan, ResearchPacket


class ContentPlanner:
    def plan(self, packet: ResearchPacket) -> ContentPlan:
        topic = packet.topic.strip()
        title = f"What {topic} means for production AI engineering"
        return ContentPlan(
            title=title,
            slug=slugify(title)[:90],
            audience="Applied AI engineers, platform engineers, and technical hiring managers",
            thesis=(
                f"{topic} matters when it is translated into observable workflows, quality gates, "
                "and repeatable publishing or product systems."
            ),
            outline=[
                "Why this signal matters",
                "Engineering signals",
                "Risks and operating boundaries",
                "How this changes the portfolio roadmap",
                "What to build next",
            ],
            keywords=["applied AI", "LLM workflow", "evaluation", "observability", "portfolio"],
        )

