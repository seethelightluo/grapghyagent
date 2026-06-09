"""Deterministic report/citation rendering for GraphyAgent outputs."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from ..core.types import utc_now
from .types import Brief, Result, SourceStatus


_MAX_RESULTS_FOR_CITATIONS = 40


def render_without_llm(brief: Brief | dict[str, Any]) -> str:
    """Render a source-backed report without calling an LLM."""
    data = _brief(brief)
    lines = [
        f"# {data.topic}",
        "",
        "## TL;DR",
        "",
        (
            f"- 共 {len(data.results)} 条结果，来自 "
            f"{sum(1 for status in data.statuses if status.ok) or len(set(r.source for r in data.results))} 个来源。"
        ),
        f"- 生成时间：{utc_now()}",
        "",
    ]
    if data.synthesis:
        lines.extend(["## Summary", "", data.synthesis.strip(), ""])
    if data.statuses:
        lines.extend(["## Source Status", "", _status_table(data.statuses), ""])
    grouped = data.by_domain()
    for domain, results in grouped.items():
        lines.extend([f"## {domain.title()}", ""])
        for index, result in enumerate(results[:8], start=1):
            marker = _citation_marker(data, result)
            engagement = f" - {result.engagement_label}" if result.engagement_label else ""
            lines.append(f"{index}. **{result.title}**{engagement} {marker}".rstrip())
            if result.url:
                lines.append(f"   {result.url}")
            if result.snippet:
                lines.append(f"   {result.snippet[:500]}")
            lines.append("")
    citations = render_citations(data)
    if citations:
        lines.extend([citations, ""])
    return "\n".join(lines).strip() + "\n"


def render_citations(brief: Brief | dict[str, Any]) -> str:
    """Emit a numbered citation list matching [N] markers."""
    data = _brief(brief)
    if not data.results:
        return ""
    lines = ["## Citations", ""]
    for index, result in enumerate(data.results[:_MAX_RESULTS_FOR_CITATIONS], start=1):
        engagement = f" - {result.engagement_label}" if result.engagement_label else ""
        lines.append(f"[{index}] ({result.source}) {result.title}{engagement}")
        if result.url:
            lines.append(f"    {result.url}")
        if result.published or result.author:
            details = " · ".join(item for item in [result.author, result.published] if item)
            lines.append(f"    {details}")
    return "\n".join(lines).strip()


def render_report_files(
    brief: Brief | dict[str, Any],
    *,
    output_dir: str | Path,
    basename: str = "report",
    include_html: bool = True,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(basename)
    markdown = render_without_llm(brief)
    md_path = out_dir / f"{safe_name}.md"
    md_path.write_text(markdown, encoding="utf-8")
    paths: dict[str, str] = {"markdown": str(md_path)}
    if include_html:
        html_path = out_dir / f"{safe_name}.html"
        html_path.write_text(_markdown_to_html(markdown), encoding="utf-8")
        paths["html"] = str(html_path)
    citations = render_citations(brief)
    citations_path = out_dir / f"{safe_name}_citations.md"
    citations_path.write_text(citations + ("\n" if citations else ""), encoding="utf-8")
    paths["citations"] = str(citations_path)
    return {
        "paths": paths,
        "preview_path": paths.get("html") or paths["markdown"],
        "markdown": markdown,
        "citations": citations,
    }


def brief_from_outputs(
    *,
    topic: str,
    outputs: dict[str, Any] | list[Any] | str,
    source: str = "graphyagent",
) -> Brief:
    results: list[Result] = []
    if isinstance(outputs, str):
        results.append(Result(source=source, title=topic, snippet=outputs, domain="graph"))
    elif isinstance(outputs, list):
        for index, item in enumerate(outputs, start=1):
            results.append(_result_from_any(item, index, source))
    elif isinstance(outputs, dict):
        for index, (name, value) in enumerate(outputs.items(), start=1):
            if isinstance(value, dict):
                data = {"title": name, "source": source, **value}
                results.append(Result.from_dict(data))
            else:
                results.append(Result(source=source, title=str(name), snippet=str(value), domain="graph"))
    return Brief(
        topic=topic,
        domains=sorted({result.domain for result in results}) or ["graph"],
        results=results,
        statuses=[SourceStatus(name=source, ok=True, count=len(results))],
    )


def _brief(value: Brief | dict[str, Any]) -> Brief:
    if isinstance(value, Brief):
        return value
    if isinstance(value, dict) and "results" in value:
        return Brief.from_dict(value)
    if isinstance(value, dict):
        return brief_from_outputs(
            topic=str(value.get("topic") or value.get("title") or "GraphyAgent Report"),
            outputs=value.get("outputs") or value,
        )
    raise TypeError("brief must be a Brief or dict")


def _result_from_any(value: Any, index: int, source: str) -> Result:
    if isinstance(value, dict):
        return Result.from_dict({"source": source, **value})
    return Result(source=source, title=f"Output {index}", snippet=str(value), domain="graph")


def _citation_marker(brief: Brief, result: Result) -> str:
    try:
        index = brief.results.index(result) + 1
    except ValueError:
        return ""
    return f"[{index}]"


def _status_table(statuses: list[SourceStatus]) -> str:
    lines = ["| Source | Status | Count | Notes |", "|---|---:|---:|---|"]
    for status in statuses:
        note = status.error or status.skipped_reason or ""
        lines.append(f"| {status.name} | {'ok' if status.ok else 'failed'} | {status.count} | {note} |")
    return "\n".join(lines)


def _markdown_to_html(markdown: str) -> str:
    body_lines = []
    in_list = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            body_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body_lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            body_lines.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                body_lines.append("<ul>")
                in_list = True
            body_lines.append(f"<li>{_inline_markdown(line[2:])}</li>")
        else:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<p>{_inline_markdown(line)}</p>")
    if in_list:
        body_lines.append("</ul>")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;max-width:920px;margin:32px auto;line-height:1.55;color:#111827}"
        "h1,h2,h3{line-height:1.2}code,pre{background:#f3f4f6;padding:2px 4px;border-radius:4px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #d1d5db;padding:6px 8px;text-align:left}</style>"
        "</head><body>"
        + "\n".join(body_lines)
        + "</body></html>"
    )


def _inline_markdown(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    url_pattern = r"(https?://[^\s<]+)"
    return re.sub(url_pattern, r'<a href="\1">\1</a>', escaped)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "_", str(value).strip())
    return cleaned.strip("._") or "report"


__all__ = [
    "brief_from_outputs",
    "render_citations",
    "render_report_files",
    "render_without_llm",
]
