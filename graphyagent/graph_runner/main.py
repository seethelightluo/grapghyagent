"""Main interface for graph execution."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import load_graph_config
from ..core.types import GraphConfig
from .executor import GraphExecutionError, GraphExecutor
from .history import (
    graph_run_manifest,
    graph_run_errors,
    graph_run_outputs,
    graph_run_timeline,
    export_trace_dataset,
    list_graph_runs,
    read_graph_run,
    read_node_run,
    read_node_runs,
)


def run(config_path: str | Path, workspace: str | Path = ".graphyagent") -> dict:
    config = load_graph_config(config_path)
    return GraphExecutor(workspace).run_graph(config).to_dict()


def resume_from_checkpoint(
    graph: dict[str, Any],
    checkpoint: dict[str, Any],
    workspace: str | Path = ".graphyagent",
    *,
    resume_source: dict[str, Any] | None = None,
    reuse_policy: str = "strict_fingerprint",
) -> dict[str, Any]:
    checkpoint_state = checkpoint.get("state")
    if not isinstance(checkpoint_state, dict):
        raise ValueError("checkpoint is missing state")
    source = dict(resume_source or {})
    source.setdefault("checkpoint", checkpoint)
    if checkpoint.get("graph_run_id"):
        source.setdefault("source_graph_run_id", checkpoint.get("graph_run_id"))
    manifest = checkpoint.get("manifest") if isinstance(checkpoint.get("manifest"), dict) else {}
    if manifest.get("graph_run_id"):
        source.setdefault("source_graph_run_id", manifest.get("graph_run_id"))
    if checkpoint.get("checkpoint_id"):
        source.setdefault("checkpoint_id", checkpoint.get("checkpoint_id"))
    return GraphExecutor(workspace).run_graph(
        GraphConfig.from_dict(graph),
        initial_state=checkpoint_state,
        skip_completed=True,
        resume_source=source,
        reuse_policy=reuse_policy,
    ).to_dict()


def commands(target_type: str | None = None) -> list[dict]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("graph_runner", target_type)


__all__ = [
    "GraphExecutionError",
    "GraphExecutor",
    "commands",
    "graph_run_manifest",
    "graph_run_errors",
    "graph_run_outputs",
    "graph_run_timeline",
    "export_trace_dataset",
    "list_graph_runs",
    "read_graph_run",
    "read_node_run",
    "read_node_runs",
    "run",
    "resume_from_checkpoint",
]
