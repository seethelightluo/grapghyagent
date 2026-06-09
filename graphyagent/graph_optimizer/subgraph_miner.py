"""Mine reusable subgraph candidates from successful runs."""
from __future__ import annotations

from typing import Any


def mine_reusable_subgraphs(
    graph: dict[str, Any],
    runs: list[dict[str, Any]],
    *,
    min_support: int = 2,
) -> list[dict[str, Any]]:
    successful_paths = [_successful_path(run) for run in runs if run.get("status") == "success"]
    counts: dict[tuple[str, ...], int] = {}
    for path in successful_paths:
        for size in (2, 3):
            for idx in range(0, max(0, len(path) - size + 1)):
                motif = tuple(path[idx:idx + size])
                counts[motif] = counts.get(motif, 0) + 1
    candidates = []
    node_map = {str(node.get("id")): node for node in graph.get("nodes") or []}
    for motif, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if count < min_support:
            continue
        candidates.append({
            "nodes": list(motif),
            "support": count,
            "purpose": " -> ".join(
                str((node_map.get(node_id) or {}).get("task_type") or node_id)
                for node_id in motif
            ),
            "bounded_cost": True,
            "source": "historical_successful_runs",
        })
    return candidates


def _successful_path(run: dict[str, Any]) -> list[str]:
    path = []
    for item in sorted(run.get("node_runs_detail") or [], key=lambda row: str(row.get("started_at") or "")):
        if item.get("status") == "success":
            node_id = str(item.get("node_id") or "")
            if node_id:
                path.append(node_id)
    return path


__all__ = ["mine_reusable_subgraphs"]
