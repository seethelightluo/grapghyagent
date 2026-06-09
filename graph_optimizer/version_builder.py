"""Materialize optimizer suggestions as a new graph version."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.types import utc_now


def materialize_new_graph_version(
    graph: dict[str, Any],
    suggestions: list[dict[str, Any]],
    *,
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
    graph_id: str | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    candidate = deepcopy(graph)
    target_graph_id = str(graph_id or candidate.get("graph_id") or "graph")
    candidate["graph_id"] = target_graph_id
    meta = candidate.setdefault("metadata", {}).setdefault("graphyagent", {})
    current_version = int(meta.get("version") or 1)
    parent_version = meta.get("graph_version") or f"v{current_version}"
    proposed_version = f"v{current_version + 1}"
    meta["version"] = current_version + 1
    meta["graph_version"] = proposed_version
    meta["parent_graph_version"] = parent_version
    meta["optimizer_provenance"] = {
        "created_at": utc_now(),
        "source": "graph_optimizer",
        "suggestion_count": len(suggestions),
        "applied_actions": [item.get("action") for item in suggestions],
    }
    _apply_edge_suggestions(candidate, suggestions)
    result = {
        "schema": "graphyagent.optimized_graph_version.v1",
        "base_graph_id": graph.get("graph_id"),
        "graph_id": target_graph_id,
        "parent_graph_version": parent_version,
        "proposed_graph_version": proposed_version,
        "graph": candidate,
        "suggestions": suggestions,
        "persisted": False,
    }
    if persist:
        if not project_id:
            raise ValueError("persist=True requires project_id")
        from ..data_manager.project_store import ProjectStore
        from ..graph_saver import save_workflow_version

        store = ProjectStore(workspace)
        save = store.save_graph(str(project_id), target_graph_id, candidate)
        version = save_workflow_version(
            store,
            str(project_id),
            target_graph_id,
            note="materialized by graph_optimizer",
            source="graph_optimizer",
        )
        result.update({"persisted": True, "save_result": save, "version": version.get("version")})
    return result


def _apply_edge_suggestions(graph: dict[str, Any], suggestions: list[dict[str, Any]]) -> None:
    for suggestion in suggestions:
        if suggestion.get("target_type") != "edge":
            continue
        edge_id = str(suggestion.get("target_id") or "")
        if "->" not in edge_id:
            continue
        source, target = edge_id.split("->", 1)
        node = next((item for item in graph.get("nodes") or [] if str(item.get("id")) == target), None)
        if not node:
            continue
        policies = node.setdefault("metadata", {}).setdefault("edge_policies", {})
        policy = policies.setdefault(source, {})
        policy["optimizer_action"] = suggestion.get("action")
        policy["confidence"] = suggestion.get("confidence")
        policy["reason"] = suggestion.get("reason")
        if suggestion.get("action") == "increase_priority":
            policy["priority"] = "backbone"
        elif suggestion.get("action") == "soft_deprecate":
            policy["priority"] = "fallback"
            policy["soft_deprecated"] = True


__all__ = ["materialize_new_graph_version"]
