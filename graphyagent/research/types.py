"""Small source-backed report types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Result:
    source: str
    title: str
    url: str = ""
    snippet: str = ""
    author: str = ""
    published: str = ""
    engagement_raw: int = 0
    engagement_label: str = ""
    domain: str = "web"
    extra: dict[str, Any] = field(default_factory=dict)
    engagement_score: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Result":
        return cls(
            source=str(data.get("source") or data.get("type") or "graphyagent"),
            title=str(data.get("title") or data.get("name") or "Untitled"),
            url=str(data.get("url") or data.get("path") or ""),
            snippet=str(data.get("snippet") or data.get("content") or data.get("summary") or ""),
            author=str(data.get("author") or ""),
            published=str(data.get("published") or data.get("created_at") or ""),
            engagement_raw=_int(data.get("engagement_raw") or 0),
            engagement_label=str(data.get("engagement_label") or ""),
            domain=str(data.get("domain") or "web"),
            extra=dict(data.get("extra") or {}),
            engagement_score=float(data.get("engagement_score") or 0.0),
        )


@dataclass
class SourceStatus:
    name: str
    ok: bool
    count: int = 0
    duration_ms: int = 0
    error: str = ""
    skipped_reason: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceStatus":
        return cls(
            name=str(data.get("name") or data.get("source") or "source"),
            ok=bool(data.get("ok", True)),
            count=_int(data.get("count") or 0),
            duration_ms=_int(data.get("duration_ms") or 0),
            error=str(data.get("error") or ""),
            skipped_reason=str(data.get("skipped_reason") or ""),
        )


@dataclass
class Brief:
    topic: str
    domains: list[str]
    results: list[Result]
    statuses: list[SourceStatus]
    synthesis: str = ""
    total_duration_ms: int = 0
    cache_hits: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Brief":
        results = [
            Result.from_dict(item)
            for item in data.get("results", [])
            if isinstance(item, dict)
        ]
        statuses = [
            SourceStatus.from_dict(item)
            for item in data.get("statuses", [])
            if isinstance(item, dict)
        ]
        domains = data.get("domains") or sorted({item.domain for item in results}) or ["web"]
        return cls(
            topic=str(data.get("topic") or data.get("title") or "GraphyAgent Report"),
            domains=[str(item) for item in domains],
            results=results,
            statuses=statuses,
            synthesis=str(data.get("synthesis") or data.get("summary") or ""),
            total_duration_ms=_int(data.get("total_duration_ms") or 0),
            cache_hits=_int(data.get("cache_hits") or 0),
        )

    def by_domain(self) -> dict[str, list[Result]]:
        grouped: dict[str, list[Result]] = {}
        for result in self.results:
            grouped.setdefault(result.domain, []).append(result)
        for domain in grouped:
            grouped[domain].sort(key=lambda item: item.engagement_score, reverse=True)
        return grouped


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
