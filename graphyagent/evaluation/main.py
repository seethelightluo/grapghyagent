"""Main interface for evaluation module commands."""
from __future__ import annotations

from typing import Any

from .compare_versions import compare_graph_versions
from .leaderboard import rank_graph_versions
from .metrics import graph_metrics
from .reporting import render_evaluation_report
from .task_sets import load_task_set


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("evaluation", target_type)


__all__ = [
    "commands",
    "compare_graph_versions",
    "graph_metrics",
    "rank_graph_versions",
    "load_task_set",
    "render_evaluation_report",
]
