"""Compare graph versions before promotion."""
from __future__ import annotations

from typing import Any

from .metrics import graph_metrics


def compare_graph_versions(base_graph: dict[str, Any], candidate_graph: dict[str, Any]) -> dict[str, Any]:
    base = graph_metrics(base_graph)
    candidate = graph_metrics(candidate_graph)
    deltas = {
        key: candidate.get(key, 0) - base.get(key, 0)
        for key in sorted(set(base) | set(candidate))
        if isinstance(base.get(key, 0), (int, float)) and isinstance(candidate.get(key, 0), (int, float))
    }
    passed = (
        candidate["node_count"] <= max(base["node_count"] + 2, base["node_count"])
        and candidate["external_retrieval_node_count"] <= base["external_retrieval_node_count"] + 1
    )
    return {
        "schema": "graphyagent.graph_version_comparison.v1",
        "base_graph_id": base_graph.get("graph_id"),
        "candidate_graph_id": candidate_graph.get("graph_id"),
        "base_metrics": base,
        "candidate_metrics": candidate,
        "deltas": deltas,
        "promotion_recommendation": "review_or_promote" if passed else "hold",
        "reason": "candidate stays within structural regression gates" if passed else "candidate expands structure beyond gate",
    }


__all__ = ["compare_graph_versions"]
