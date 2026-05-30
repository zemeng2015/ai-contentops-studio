from __future__ import annotations

from pathlib import Path
from shutil import copyfile
from typing import Protocol

from contentops_core.models import Draft, EvaluationReport, PublishPlan, PublishPlanItem, RunRecord


class Publisher(Protocol):
    def plan(self, run: RunRecord, draft: Draft, report: EvaluationReport) -> PublishPlan:
        """Describe what publish would change."""

    def publish(self, run: RunRecord, draft: Draft, report: EvaluationReport) -> str:
        """Publish a draft and return a public or local URL."""


class StaticSitePublisher:
    def __init__(self, output_dir: Path, public_base_url: str) -> None:
        self.output_dir = output_dir
        self.public_base_url = public_base_url.rstrip("/")

    def publish(self, run: RunRecord, draft: Draft, report: EvaluationReport) -> str:
        plan = self.plan(run, draft, report)
        if not plan.ready:
            raise ValueError("; ".join(plan.warnings))
        posts_dir = self.output_dir / "posts"
        posts_dir.mkdir(parents=True, exist_ok=True)
        post_path = posts_dir / f"{draft.slug}.html"
        post_path.write_text(draft.html, encoding="utf-8")
        self._write_index(draft, report)
        copyfile(run.artifact_dir / "eval-report.json", posts_dir / f"{draft.slug}.eval.json")
        return f"{self.public_base_url}/posts/{draft.slug}.html"

    def plan(self, run: RunRecord, draft: Draft, report: EvaluationReport) -> PublishPlan:
        post_path = self.output_dir / "posts" / f"{draft.slug}.html"
        eval_path = self.output_dir / "posts" / f"{draft.slug}.eval.json"
        index_path = self.output_dir / "index.html"
        target_url = f"{self.public_base_url}/posts/{draft.slug}.html"
        return PublishPlan(
            provider="static",
            target_url=target_url,
            ready=report.publish_ready,
            warnings=[] if report.publish_ready else ["Evaluation report is not publish-ready."],
            items=[
                PublishPlanItem(
                    path=str(post_path),
                    action="create" if not post_path.exists() else "overwrite",
                    exists=post_path.exists(),
                    description="Write generated HTML post.",
                ),
                PublishPlanItem(
                    path=str(eval_path),
                    action="create" if not eval_path.exists() else "overwrite",
                    exists=eval_path.exists(),
                    description="Write evaluation report next to the post.",
                ),
                PublishPlanItem(
                    path=str(index_path),
                    action="create" if not index_path.exists() else "update",
                    exists=index_path.exists(),
                    description="Add post link to static site index.",
                ),
            ],
        )

    def _write_index(self, draft: Draft, report: EvaluationReport) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        index = self.output_dir / "index.html"
        existing = ""
        if index.exists():
            existing = index.read_text(encoding="utf-8")
        entry = (
            f'<article><a href="posts/{draft.slug}.html"><h2>{draft.title}</h2></a>'
            f"<p>Publish ready: {str(report.publish_ready).lower()}</p></article>"
        )
        html = (
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>AI ContentOps Studio"
            "</title></head><body><h1>Published Content</h1>"
        )
        if existing and "<main>" in existing:
            content = existing.split("<main>", 1)[1].split("</main>", 1)[0]
            html += f"<main>{entry}{content}</main></body></html>"
        else:
            html += f"<main>{entry}</main></body></html>"
        index.write_text(html, encoding="utf-8")
