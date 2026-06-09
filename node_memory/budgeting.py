"""Budget policy for node memory packets."""
from __future__ import annotations

from typing import Any


DEFAULT_PACKET_BUDGET = {
    "background_items": 4,
    "evidence_items": 6,
    "background_chars": 2400,
    "evidence_summary_chars": 600,
    "max_model_context_chars": 12000,
}


def packet_budget(node: dict[str, Any] | None = None, override: dict[str, Any] | None = None) -> dict[str, int]:
    node = node or {}
    policy = {}
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    if isinstance(metadata.get("context_policy"), dict):
        policy.update(metadata["context_policy"])
    if isinstance(node.get("context_policy"), dict):
        policy.update(node["context_policy"])
    if override:
        policy.update(override)
    result = dict(DEFAULT_PACKET_BUDGET)
    for key in result:
        try:
            if key in policy:
                result[key] = max(0, int(policy[key]))
        except (TypeError, ValueError):
            continue
    return result


__all__ = ["DEFAULT_PACKET_BUDGET", "packet_budget"]
