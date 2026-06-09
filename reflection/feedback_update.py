"""Apply reflection labels to knowledge weights."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..knowledge_graph import update_weights_from_feedback


def apply_feedback_updates(
    node_run_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph_run_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    return update_weights_from_feedback(
        node_run_id,
        workspace=workspace,
        graph_run_id=graph_run_id,
        project_id=project_id,
    )


__all__ = ["apply_feedback_updates"]
