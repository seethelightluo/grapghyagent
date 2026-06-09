"""Generate optimizer suggestions from trace statistics."""
from __future__ import annotations

import hashlib
from typing import Any

from ..core.optimizer_schema import OptimizerSuggestion


def suggest_structure_changes(
    edge_utilities: list[dict[str, Any]],
    subgraph_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    suggestions = []
    for edge in edge_utilities:
        utility = float(edge.get("utility", 0.0))
        if edge.get("evidence_run_count", 0) <= 0:
            continue
        if utility >= 0.5:
            action = "increase_priority"
            reason = "edge has high success association and useful upstream labels"
            confidence = min(0.95, 0.55 + utility / 2)
        elif utility <= 0.05 and edge.get("evidence_run_count", 0) >= 2:
            action = "soft_deprecate"
            reason = "edge has low historical utility; keep as fallback until evaluated"
            confidence = 0.6
        else:
            continue
        suggestions.append(OptimizerSuggestion(
            suggestion_id=_suggestion_id(action, edge.get("edge_id")),
            action=action,
            target_type="edge",
            target_id=str(edge.get("edge_id")),
            reason=reason,
            confidence=confidence,
            evidence={"edge_utility": edge},
        ).to_dict())
    for candidate in subgraph_candidates or []:
        nodes = candidate.get("nodes") or []
        if len(nodes) < 2:
            continue
        target_id = "subgraph:" + ",".join(str(item) for item in nodes)
        suggestions.append(OptimizerSuggestion(
            suggestion_id=_suggestion_id("promote_playbook", target_id),
            action="promote_playbook",
            target_type="subgraph",
            target_id=target_id,
            reason="node sequence recurs in successful runs",
            confidence=min(0.9, 0.45 + 0.1 * int(candidate.get("support") or 0)),
            evidence={"subgraph": candidate},
        ).to_dict())
    return suggestions


def _suggestion_id(action: str, target_id: Any) -> str:
    digest = hashlib.sha256(f"{action}:{target_id}".encode("utf-8")).hexdigest()[:12]
    return f"suggestion-{digest}"


__all__ = ["suggest_structure_changes"]
