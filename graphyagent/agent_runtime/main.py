"""Main interface for graph/node agent commands."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..data_manager.project_store import ProjectStore
from .agents import GraphyAgentAgentRuntime
from .module_registry import list_module_commands, list_modules
from .skills import list_module_skills, recommend_next_modules
from .subagents import load_agent_definitions
from .tool_catalog import list_agent_tools, list_module_inventory


def runtime(workspace: str | Path = ".graphyagent") -> GraphyAgentAgentRuntime:
    return GraphyAgentAgentRuntime(workspace, ProjectStore(workspace))


def tools(target_type: str | None = None) -> list[dict[str, Any]]:
    return list_agent_tools(target_type)


def modules() -> list[dict[str, Any]]:
    return list_modules()


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    return list_module_commands("agent_runtime", target_type)


def skills(module: str | None = None) -> list[dict[str, Any]]:
    return list_module_skills(module)


def recommend_next(module: str, *, event: str = "", error: str = "") -> dict[str, Any]:
    return recommend_next_modules(module, event=event, error=error)


def recover_graph_failure(
    workspace: str | Path = ".graphyagent",
    *,
    project_id: str,
    graph_id: str,
    graph_run_id: str | None = None,
    node_run_id: str | None = None,
    failed_node_id: str | None = None,
    node_id: str | None = None,
    error: str | None = None,
    failure_analysis: dict[str, Any] | None = None,
    apply: bool = False,
    force_replan: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "graph_run_id": graph_run_id,
        "node_run_id": node_run_id,
        "failed_node_id": failed_node_id,
        "node_id": node_id,
        "error": error,
        "failure_analysis": failure_analysis,
        "apply": apply,
        "force_replan": force_replan,
    }
    return runtime(workspace).execute_module_command({
        "module": "agent_runtime",
        "command": "recover_graph_failure",
        "project_id": project_id,
        "graph_id": graph_id,
        "node_id": node_id or failed_node_id,
        "payload": {key: value for key, value in payload.items() if value is not None},
    })


def subagents(workspace: str | Path = ".") -> list[dict[str, Any]]:
    definitions = load_agent_definitions(workspace)
    return [
        {
            "name": item.name,
            "description": item.description,
            "model": item.model,
            "tools": item.tools,
            "source": item.source,
        }
        for item in sorted(definitions.values(), key=lambda value: value.name)
    ]


__all__ = [
    "GraphyAgentAgentRuntime",
    "commands",
    "list_module_inventory",
    "modules",
    "recover_graph_failure",
    "recommend_next",
    "runtime",
    "skills",
    "subagents",
    "tools",
]
