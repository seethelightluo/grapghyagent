"""Filtering helpers for knowledge candidates."""
from __future__ import annotations

from typing import Any


def trim_evidence_items(items: list[dict[str, Any]], *, limit: int, summary_chars: int) -> list[dict[str, Any]]:
    trimmed = []
    for item in items[: max(0, int(limit))]:
        entry = {
            "knowledge_id": item.get("knowledge_id"),
            "knowledge_type": item.get("knowledge_type"),
            "summary": str(item.get("summary") or "")[: max(0, int(summary_chars))],
            "content_locator": item.get("content_locator"),
            "score": item.get("score"),
            "score_features": item.get("score_features") or {},
            "access_policy": item.get("access_policy"),
        }
        trimmed.append(entry)
    return trimmed


def knowledge_ids(*groups: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen = set()
    for group in groups:
        for item in group:
            knowledge_id = str(item.get("knowledge_id") or "")
            if knowledge_id and knowledge_id not in seen:
                seen.add(knowledge_id)
                ids.append(knowledge_id)
    return ids


__all__ = ["knowledge_ids", "trim_evidence_items"]
