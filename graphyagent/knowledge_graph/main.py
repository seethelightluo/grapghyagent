"""Main interface for knowledge_graph module commands."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .builder import (
    build_for_project,
    build_view_for_node,
    decay_noisy_items,
    refresh_from_run,
    update_weights_from_feedback,
)


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("knowledge_graph", target_type)


__all__ = [
    "build_for_project",
    "build_view_for_node",
    "decay_noisy_items",
    "commands",
    "refresh_from_run",
    "update_weights_from_feedback",
]
