"""Knowledge graph policy helpers."""
from __future__ import annotations

from typing import Any


def access_policy_for_source(source: str, metadata: dict[str, Any] | None = None) -> str:
    metadata = metadata or {}
    if metadata.get("quarantined"):
        return "quarantine"
    lowered = str(source).lower()
    if lowered.startswith(("http://", "https://")) or metadata.get("external"):
        return "quarantine"
    return "internal"


def should_index_file(file_record: dict[str, Any]) -> bool:
    return bool(file_record.get("storage_path") or file_record.get("path"))


__all__ = ["access_policy_for_source", "should_index_file"]
