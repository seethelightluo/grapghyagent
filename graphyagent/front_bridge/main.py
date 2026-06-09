"""Main interface for CLI/Web/API bridge operations."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent_commands import AgentCommandStore
from .service import inspect_graph_config, list_graph_runs, read_graph_run, read_node_runs, run_graph
from .webapp import start_graphyagent_web_server


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    workspace: str | Path = ".graphyagent",
    default_config: str | Path | None = None,
) -> None:
    start_graphyagent_web_server(
        host=host,
        port=port,
        workspace=workspace,
        default_config=default_config,
    )


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("front_bridge", target_type)


__all__ = [
    "AgentCommandStore",
    "commands",
    "inspect_graph_config",
    "list_graph_runs",
    "read_graph_run",
    "read_node_runs",
    "run_graph",
    "serve",
]
