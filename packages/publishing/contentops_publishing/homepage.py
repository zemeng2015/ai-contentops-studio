from __future__ import annotations

from pathlib import Path
from shutil import copyfile

from contentops_core.models import Draft, EvaluationReport, RunRecord


class HomepagePublisher:
    def __init__(self, homepage_repo_path: Path, public_base_url: str) -> None:
        self.homepage_repo_path = homepage_repo_path
        self.public_base_url = public_base_url.rstrip("/")

    def publish(self, run: RunRecord, draft: Draft, report: EvaluationReport) -> str:
        posts_dir = self.homepage_repo_path / "posts"
        posts_dir.mkdir(parents=True, exist_ok=True)
        post_path = posts_dir / f"{draft.slug}.html"
        post_path.write_text(self._wrap_for_homepage(draft.html), encoding="utf-8")
        copyfile(run.artifact_dir / "eval-report.json", posts_dir / f"{draft.slug}.eval.json")
        self._update_index(draft, report)
        return f"{self.public_base_url}/posts/{draft.slug}.html"

    def _update_index(self, draft: Draft, report: EvaluationReport) -> None:
        index_path = self.homepage_repo_path / "index.html"
        if not index_path.exists():
            raise FileNotFoundError(f"Homepage index not found: {index_path}")
        html = index_path.read_text(encoding="utf-8")
        marker = '<div class="post-grid">'
        if marker not in html:
            raise ValueError("Homepage index.html does not contain the expected post-grid marker.")
        if f'href="posts/{draft.slug}.html"' in html:
            return
        status_line = (
            f"Evaluation ready: {str(report.publish_ready).lower()} | "
            f"Groundedness: {report.groundedness:.2f}"
        )
        entry = f"""
          <a class="post-card" href="posts/{draft.slug}.html">
            <span>AI ContentOps</span>
            <p class="post-date">Auto-generated</p>
            <h3>{draft.title}</h3>
            <p>{status_line}</p>
          </a>"""
        html = html.replace(marker, marker + entry, 1)
        index_path.write_text(html, encoding="utf-8")

    @staticmethod
    def _wrap_for_homepage(html: str) -> str:
        if "../assets/styles.css" in html:
            return html
        return html.replace(
            "<head>",
            '<head>\n    <link rel="stylesheet" href="../assets/styles.css" />',
            1,
        )
