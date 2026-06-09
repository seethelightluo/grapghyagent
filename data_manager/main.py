"""Main interface for project, graph, file, and memory management."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_store import ProjectStore


def open_store(workspace: str | Path = ".graphyagent") -> ProjectStore:
    return ProjectStore(workspace)


def snapshot(workspace: str | Path = ".graphyagent") -> dict[str, Any]:
    return open_store(workspace).snapshot()


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("data_manager", target_type)


__all__ = ["ProjectStore", "commands", "open_store", "snapshot"]
