"""Version leaderboard helpers for graph promotion review."""
from __future__ import annotations

from typing import Any

from .metrics import graph_metrics


def rank_graph_versions(entries: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for index, entry in enumerate(entries):
        graph = entry.get("graph") if isinstance(entry.get("graph"), dict) else None
        comparison = entry.get("comparison") if isinstance(entry.get("comparison"), dict) else None
        metrics = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else None
        if comparison:
            metrics = comparison.get("candidate_metrics") or metrics or {}
            graph_id = comparison.get("candidate_graph_id") or entry.get("graph_id")
            recommendation = comparison.get("promotion_recommendation")
        elif graph:
            metrics = graph_metrics(graph)
            graph_id = graph.get("graph_id") or entry.get("graph_id")
            recommendation = entry.get("promotion_recommendation")
        else:
            graph_id = entry.get("graph_id") or f"candidate_{index + 1}"
            metrics = metrics or {}
            recommendation = entry.get("promotion_recommendation")
        oracle_score = float(entry.get("oracle_score", entry.get("score", 0.0)) or 0.0)
        score = _leaderboard_score(metrics, recommendation, oracle_score)
        rows.append({
            "rank": 0,
            "graph_id": graph_id,
            "graph_version": entry.get("graph_version") or entry.get("version"),
            "score": round(score, 6),
            "oracle_score": oracle_score,
            "promotion_recommendation": recommendation,
            "metrics": metrics,
            "reason": _reason(metrics, recommendation),
        })
    rows.sort(key=lambda item: item["score"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return {
        "schema": "graphyagent.version_leaderboard.v1",
        "candidate_count": len(rows),
        "leader": rows[0] if rows else None,
        "rows": rows,
    }


def _leaderboard_score(metrics: dict[str, Any], recommendation: Any, oracle_score: float) -> float:
    node_count = float(metrics.get("node_count") or 0)
    path_length = float(metrics.get("estimated_path_length") or 0)
    fallback_edges = float(metrics.get("fallback_edge_count") or 0)
    backbone_edges = float(metrics.get("backbone_edge_count") or 0)
    external_nodes = float(metrics.get("external_retrieval_node_count") or 0)
    recommendation_bonus = 0.15 if recommendation == "review_or_promote" else 0.0
    return (
        oracle_score
        + recommendation_bonus
        + (0.04 * backbone_edges)
        - (0.015 * node_count)
        - (0.02 * path_length)
        - (0.03 * fallback_edges)
        - (0.04 * external_nodes)
    )


def _reason(metrics: dict[str, Any], recommendation: Any) -> str:
    parts = []
    if recommendation:
        parts.append(f"promotion={recommendation}")
    parts.append(f"nodes={metrics.get('node_count', 0)}")
    parts.append(f"path={metrics.get('estimated_path_length', 0)}")
    parts.append(f"backbone={metrics.get('backbone_edge_count', 0)}")
    parts.append(f"fallback={metrics.get('fallback_edge_count', 0)}")
    return ", ".join(parts)


__all__ = ["rank_graph_versions"]
