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
    "recommend_next",
    "runtime",
    "skills",
    "subagents",
    "tools",
]
