"""Evidence gap state helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.types import utc_now


def update_gap_state(
    project_id: str,
    graph_id: str,
    node_id: str,
    gaps: list[str],
    *,
    workspace: str | Path = ".graphyagent",
    status: str = "open",
) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve() / "projects" / str(project_id) / "knowledge"
    path = root / "gap_state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"nodes": {}}
    node_key = f"{graph_id}:{node_id}"
    state.setdefault("nodes", {})[node_key] = {
        "project_id": project_id,
        "graph_id": graph_id,
        "node_id": node_id,
        "status": status,
        "gaps": list(gaps),
        "updated_at": utc_now(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return state["nodes"][node_key]


__all__ = ["update_gap_state"]
