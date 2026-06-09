"""Main interface for workflow persistence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..data_manager.project_store import ProjectStore
from .saver import (
    export_workflow,
    fork_workflow_from_checkpoint,
    import_workflow,
    list_graph_run_checkpoints,
    list_workflow_versions,
    merge_workflow,
    read_graph_run_checkpoint,
    restore_workflow_version,
    save_workflow_version,
)


def save(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    *,
    graph: dict[str, Any] | None = None,
    note: str | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    return save_workflow_version(
        ProjectStore(workspace),
        project_id,
        graph_id,
        graph=graph,
        note=note,
        source=source,
    )


def versions(workspace: str | Path, project_id: str, graph_id: str) -> dict[str, Any]:
    return list_workflow_versions(ProjectStore(workspace), project_id, graph_id)


def restore(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    version_id: str,
) -> dict[str, Any]:
    return restore_workflow_version(ProjectStore(workspace), project_id, graph_id, version_id)


def export(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    *,
    output_path: str | Path | None = None,
    include_versions: bool = False,
) -> dict[str, Any]:
    return export_workflow(
        ProjectStore(workspace),
        project_id,
        graph_id,
        output_path=output_path,
        include_versions=include_versions,
    )


def import_graph(
    workspace: str | Path,
    project_id: str,
    path: str | Path,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    return import_workflow(ProjectStore(workspace), project_id, path, name=name)


def merge(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    *,
    source_graph: dict[str, Any] | None = None,
    source_graph_id: str | None = None,
    path: str | Path | None = None,
    prefix: str | None = None,
    attach_to: list[str] | None = None,
    output_policy: str = "append",
    note: str | None = None,
) -> dict[str, Any]:
    return merge_workflow(
        ProjectStore(workspace),
        project_id,
        graph_id,
        source_graph=source_graph,
        source_graph_id=source_graph_id,
        path=path,
        prefix=prefix,
        attach_to=attach_to,
        output_policy=output_policy,
        note=note,
    )


def list_checkpoints(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    return list_graph_run_checkpoints(workspace, graph_run_id)


def read_checkpoint(
    workspace: str | Path,
    graph_run_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    return read_graph_run_checkpoint(workspace, graph_run_id, checkpoint_id)


def fork_from_checkpoint(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    *,
    graph_run_id: str,
    checkpoint_id: str,
    name: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return fork_workflow_from_checkpoint(
        ProjectStore(workspace),
        project_id,
        graph_id,
        graph_run_id=graph_run_id,
        checkpoint_id=checkpoint_id,
        name=name,
        note=note,
    )


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("graph_saver", target_type)


__all__ = [
    "commands",
    "export",
    "fork_from_checkpoint",
    "import_graph",
    "list_checkpoints",
    "merge",
    "read_checkpoint",
    "restore",
    "save",
    "versions",
]
