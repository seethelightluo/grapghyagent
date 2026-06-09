"""Edge utility scoring from historical traces."""
from __future__ import annotations

from typing import Any

from ..core.graph_schema import graph_edges
from ..core.optimizer_schema import EdgeUtility


def compute_edge_utilities(
    graph: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    edges = graph_edges(graph)
    if not edges:
        return []
    run_count = max(1, len(runs))
    success_runs = [run for run in runs if run.get("status") == "success"]
    utilities = []
    for edge in edges:
        source = str(edge["source_node_id"])
        target = str(edge["target_node_id"])
        traversed = 0
        successful = 0
        useful = 0
        risky = 0
        cost = 0.0
        for run in runs:
            target_run = _node_run_for(run, target)
            if not target_run:
                continue
            traversed += 1
            if run.get("status") == "success" and target_run.get("status") == "success":
                successful += 1
            labels = ((target_run.get("output_snapshot") or {}).get("online_reflection") or {}).get("upstream_usage_labels") or []
            for label in labels:
                if str(label.get("node_id")) != source:
                    continue
                if label.get("label") in {"useful", "critical"}:
                    useful += 1
                if label.get("label") in {"risky", "misleading", "insufficient"}:
                    risky += 1
            cost += float(target_run.get("duration_ms") or 0) / 1000.0
        success_assoc = successful / max(1, len(success_runs) or run_count)
        useful_rate = useful / max(1, traversed)
        risk_rate = risky / max(1, traversed)
        cost_contribution = cost / max(1, traversed) / 60.0
        utility = (0.45 * success_assoc) + (0.4 * useful_rate) - (0.25 * risk_rate) - (0.1 * cost_contribution)
        utilities.append(EdgeUtility(
            edge_id=edge["edge_id"],
            source_node_id=source,
            target_node_id=target,
            utility=utility,
            success_assoc=success_assoc,
            useful_rate=useful_rate,
            risk_rate=risk_rate,
            cost_contribution=cost_contribution,
            evidence_run_count=traversed,
        ).to_dict())
    utilities.sort(key=lambda item: item["utility"], reverse=True)
    return utilities


def _node_run_for(run: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    matches = [
        item for item in run.get("node_runs_detail") or []
        if str(item.get("node_id")) == node_id
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return matches[0]


__all__ = ["compute_edge_utilities"]
