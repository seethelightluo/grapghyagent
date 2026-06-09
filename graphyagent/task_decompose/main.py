"""Main interface for node task decomposition."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..data_manager.project_store import ProjectStore
from .recovery import build_decompose_prompt, build_retry_prompt, decompose_task


def run(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    node_id: str,
    child_names: list[str] | None = None,
) -> dict[str, Any]:
    return ProjectStore(workspace).decompose_node(project_id, graph_id, node_id, child_names)


def decompose_task_to_graph(
    workspace: str | Path,
    project_id: str,
    prompt: str,
    *,
    graph_id: str | None = None,
    name: str | None = None,
    create_new_graph: bool = True,
) -> dict[str, Any]:
    return ProjectStore(workspace).decompose_task_to_graph(
        project_id,
        prompt,
        graph_id=graph_id,
        name=name,
        create_new_graph=create_new_graph,
    )


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("task_decompose", target_type)


__all__ = [
    "build_decompose_prompt",
    "build_retry_prompt",
    "commands",
    "decompose_task",
    "decompose_task_to_graph",
    "run",
]
