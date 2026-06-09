"""Main interface for node necessity audit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..data_manager.project_store import ProjectStore
from .contract import contract_audit_memory_text, validate_node_contract


def run(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    node_id: str,
) -> dict[str, Any]:
    return ProjectStore(workspace).audit_node_necessity(project_id, graph_id, node_id)


def validate_contract(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    node_id: str,
    *,
    graph: dict[str, Any] | None = None,
    update_graph: bool = True,
) -> dict[str, Any]:
    store = ProjectStore(workspace)
    graph_data = graph if isinstance(graph, dict) else store.read_graph(project_id, graph_id)
    contract = validate_node_contract(graph_data, node_id, phase="audit")
    resolved_node_id = str(contract.get("node_id") or node_id)
    if not update_graph:
        return {
            "node_id": resolved_node_id,
            "contract_audit": contract,
        }

    updated_graph = graph_data
    for node in updated_graph.get("nodes", []):
        if str(node.get("id") or "") == resolved_node_id:
            node.setdefault("metadata", {})["contract_audit"] = contract
            break
    result = store.save_graph(project_id, graph_id, updated_graph)
    store.append_memory_event(
        project_id,
        graph_id,
        {"type": "node", "name": resolved_node_id},
        "system",
        contract_audit_memory_text(contract),
    )
    return {
        "node_id": resolved_node_id,
        "contract_audit": contract,
        **result,
    }


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("node_audit", target_type)


__all__ = ["commands", "run", "validate_contract", "validate_node_contract"]
