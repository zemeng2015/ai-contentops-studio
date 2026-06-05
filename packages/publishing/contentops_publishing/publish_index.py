from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from contentops_core.models import Draft, EvaluationReport, RunRecord


def upsert_publish_index_entry(
    index_path: Path,
    *,
    provider: str,
    public_url: str,
    run: RunRecord,
    draft: Draft,
    report: EvaluationReport,
) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_index(index_path)
    existing_entries = payload.get("entries", [])
    if not isinstance(existing_entries, list):
        existing_entries = []
    entries = [
        entry
        for entry in existing_entries
        if isinstance(entry, dict) and entry.get("run_id") != run.id
    ]
    entries.insert(
        0,
        {
            "run_id": run.id,
            "topic": run.topic,
            "slug": draft.slug,
            "title": draft.title,
            "url": public_url,
            "provider": provider,
            "published_at": datetime.now(UTC).isoformat(),
            "quality": {
                "publish_ready": report.publish_ready,
                "groundedness": report.groundedness,
                "source_coverage": report.source_coverage,
                "source_quality": report.source_quality,
                "career_relevance": report.career_relevance,
                "technical_depth": report.technical_depth,
            },
        },
    )
    payload["schema_version"] = 1
    payload["updated_at"] = datetime.now(UTC).isoformat()
    payload["entries"] = entries
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_publish_index_entries(index_path: Path) -> list[dict[str, Any]]:
    payload = _read_index(index_path)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def render_rss_feed(
    index_path: Path,
    *,
    channel_title: str = "AI ContentOps Studio",
    channel_description: str = "Reviewed AI and technical content.",
    channel_url: str = "",
    limit: int = 20,
) -> str:
    entries = load_publish_index_entries(index_path)[:limit]
    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = channel_title
    SubElement(channel, "description").text = channel_description
    SubElement(channel, "link").text = channel_url or _first_entry_url(entries)
    SubElement(channel, "lastBuildDate").text = datetime.now(UTC).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    for entry in entries:
        item = SubElement(channel, "item")
        title = str(entry.get("title") or entry.get("topic") or "Untitled")
        url = str(entry.get("url") or "")
        topic = str(entry.get("topic") or title)
        quality = entry.get("quality")
        quality_line = ""
        if isinstance(quality, dict):
            quality_line = (
                f" Groundedness {float(quality.get('groundedness', 0.0)):.2f};"
                f" source coverage {float(quality.get('source_coverage', 0.0)):.2f}."
            )
        SubElement(item, "title").text = title
        SubElement(item, "link").text = url
        SubElement(item, "guid").text = str(entry.get("run_id") or url or title)
        SubElement(item, "description").text = f"{topic}.{quality_line}".strip()
        if published_at := _rss_date(entry.get("published_at")):
            SubElement(item, "pubDate").text = published_at
    return '<?xml version="1.0" encoding="utf-8"?>\n' + tostring(
        rss,
        encoding="unicode",
        short_empty_elements=False,
    )


def render_promotion_brief(index_path: Path, *, limit: int = 5) -> str:
    entries = load_publish_index_entries(index_path)[:limit]
    lines = [
        "# Promotion Brief",
        "",
        "Use these reviewed content items for homepage modules, newsletters, or social posts.",
        "",
    ]
    if not entries:
        lines.append("No published content is available in the publish index yet.")
        return "\n".join(lines) + "\n"
    for entry in entries:
        title = str(entry.get("title") or entry.get("topic") or "Untitled")
        topic = str(entry.get("topic") or title)
        url = str(entry.get("url") or "")
        quality = _quality(entry)
        groundedness = float(quality.get("groundedness", 0.0))
        source_coverage = float(quality.get("source_coverage", 0.0))
        quality_summary = (
            f"groundedness {groundedness:.2f}, source coverage {source_coverage:.2f}"
        )
        lines.extend(
            [
                f"## {title}",
                "",
                f"- URL: {url}",
                f"- Angle: {topic}",
                f"- Quality: {quality_summary}",
                f"- LinkedIn draft: {escape(_linkedin_draft(title, topic, url))}",
                f"- Newsletter blurb: {escape(_newsletter_blurb(title, topic, url))}",
                "",
            ]
        )
    return "\n".join(lines)


def write_distribution_assets(
    index_path: Path,
    output_dir: Path,
    *,
    channel_title: str = "AI ContentOps Studio",
    channel_description: str = "Reviewed AI and technical content.",
    channel_url: str = "",
    limit: int = 20,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    feed_path = output_dir / "feed.xml"
    brief_path = output_dir / "promotion-brief.md"
    feed_path.write_text(
        render_rss_feed(
            index_path,
            channel_title=channel_title,
            channel_description=channel_description,
            channel_url=channel_url,
            limit=limit,
        ),
        encoding="utf-8",
    )
    brief_path.write_text(
        render_promotion_brief(index_path, limit=min(limit, 10)),
        encoding="utf-8",
    )
    return {"feed": feed_path, "promotion_brief": brief_path}


def _read_index(index_path: Path) -> dict[str, object]:
    if not index_path.exists():
        return {"schema_version": 1, "entries": []}
    try:
        payload: Any = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": 1, "entries": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "entries": []}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        payload["entries"] = []
    return payload


def _first_entry_url(entries: list[dict[str, Any]]) -> str:
    for entry in entries:
        url = entry.get("url")
        if isinstance(url, str) and url:
            return url
    return ""


def _quality(entry: dict[str, Any]) -> dict[str, Any]:
    quality = entry.get("quality")
    if isinstance(quality, dict):
        return quality
    return {}


def _rss_date(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _linkedin_draft(title: str, topic: str, url: str) -> str:
    return (
        f"Published a new source-backed AI engineering note: {title}. "
        f"It covers {topic}. Read it here: {url}"
    )


def _newsletter_blurb(title: str, topic: str, url: str) -> str:
    return f"{title}: a reviewed technical write-up on {topic}. {url}"
