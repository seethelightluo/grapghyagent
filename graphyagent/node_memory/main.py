"""Main interface for node_memory module commands."""
from __future__ import annotations

from typing import Any

from .assembler import (
    prepare_node_context,
    record_context_usage,
    summarize_context_for_model,
    update_gap_state,
)


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("node_memory", target_type)


__all__ = [
    "commands",
    "prepare_node_context",
    "record_context_usage",
    "summarize_context_for_model",
    "update_gap_state",
]
