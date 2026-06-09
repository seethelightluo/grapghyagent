"""Main interface for graph_optimizer module commands."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .edge_stats import compute_edge_utilities as _compute_edge_utilities
from .policy_eval import promotion_gate
from .subgraph_miner import mine_reusable_subgraphs as _mine_reusable_subgraphs
from .suggestions import suggest_structure_changes as _suggest_structure_changes
from .trace_loader import load_graph_runs
from .version_builder import materialize_new_graph_version as _materialize_new_graph_version


def analyze_graph_runs(
    graph_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph: dict[str, Any] | None = None,
    graph_run_ids: list[str] | None = None,
    version_range: Any = None,
) -> dict[str, Any]:
    runs = load_graph_runs(graph_id, workspace=workspace, graph_run_ids=graph_run_ids)
    base_graph = graph or _graph_from_runs(runs) or {"graph_id": graph_id, "nodes": []}
    edge_utilities = _compute_edge_utilities(base_graph, runs)
    subgraphs = _mine_reusable_subgraphs(base_graph, runs)
    suggestions = _suggest_structure_changes(edge_utilities, subgraphs)
    analysis = {
        "schema": "graphyagent.graph_optimizer_analysis.v1",
        "graph_id": graph_id,
        "version_range": version_range,
        "run_count": len(runs),
        "success_count": sum(1 for run in runs if run.get("status") == "success"),
        "edge_utilities": edge_utilities,
        "subgraph_candidates": subgraphs,
        "suggestions": suggestions,
    }
    analysis["promotion_gate"] = promotion_gate(analysis)
    return analysis


def compute_edge_utilities(
    graph: dict[str, Any],
    runs: list[dict[str, Any]] | None = None,
    *,
    workspace: str | Path = ".graphyagent",
    graph_id: str | None = None,
) -> list[dict[str, Any]]:
    if runs is None:
        runs = load_graph_runs(str(graph_id or graph.get("graph_id") or ""), workspace=workspace)
    return _compute_edge_utilities(graph, runs)


def mine_reusable_subgraphs(
    graph: dict[str, Any],
    runs: list[dict[str, Any]] | None = None,
    *,
    workspace: str | Path = ".graphyagent",
    graph_id: str | None = None,
) -> list[dict[str, Any]]:
    if runs is None:
        runs = load_graph_runs(str(graph_id or graph.get("graph_id") or ""), workspace=workspace)
    return _mine_reusable_subgraphs(graph, runs)


def suggest_structure_changes(
    edge_utilities: list[dict[str, Any]],
    subgraph_candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return _suggest_structure_changes(edge_utilities, subgraph_candidates)


def materialize_new_graph_version(
    graph: dict[str, Any],
    suggestions: list[dict[str, Any]],
    *,
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
    graph_id: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    return _materialize_new_graph_version(
        graph,
        suggestions,
        workspace=workspace,
        project_id=project_id,
        graph_id=graph_id,
        persist=persist,
    )


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("graph_optimizer", target_type)


def _graph_from_runs(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for run in reversed(runs):
        graph = run.get("graph_config")
        if isinstance(graph, dict):
            return graph
    return None


__all__ = [
    "analyze_graph_runs",
    "commands",
    "compute_edge_utilities",
    "materialize_new_graph_version",
    "mine_reusable_subgraphs",
    "suggest_structure_changes",
]
