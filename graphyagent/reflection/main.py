"""Main interface for reflection module commands."""
from __future__ import annotations

from typing import Any

from .online import apply_feedback_updates, run_online_reflection


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("reflection", target_type)


__all__ = ["apply_feedback_updates", "commands", "run_online_reflection"]
