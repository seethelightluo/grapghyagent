"""Match tasks or graphs to existing playbooks."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def match_playbooks(
    graph: dict[str, Any] | None = None,
    *,
    task: str = "",
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query = _query_text(graph, task)
    candidates = []
    for playbook in _load_playbooks(workspace, project_id):
        score = _overlap(query, _query_text({"nodes": playbook.get("nodes") or []}, playbook.get("name") or ""))
        if score <= 0:
            continue
        candidates.append({
            "playbook_id": playbook.get("playbook_id"),
            "name": playbook.get("name"),
            "score": round(score, 6),
            "node_count": len(playbook.get("nodes") or []),
            "source_graph_id": playbook.get("source_graph_id"),
            "path": playbook.get("path"),
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[: max(1, int(limit))]


def _load_playbooks(workspace: str | Path, project_id: str | None) -> list[dict[str, Any]]:
    root = Path(workspace).expanduser().resolve()
    paths = []
    if project_id:
        paths.extend((root / "projects" / str(project_id) / "knowledge" / "playbooks").glob("*.json"))
    paths.extend((root / "knowledge" / "playbooks").glob("*.json"))
    items = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data["path"] = str(path)
            items.append(data)
    return items


def _query_text(graph: dict[str, Any] | None, task: str) -> str:
    parts = [task]
    for node in (graph or {}).get("nodes") or []:
        meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        parts.extend([str(node.get("id") or ""), str(node.get("task_type") or ""), str(meta.get("description") or "")])
    return " ".join(parts)


def _overlap(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a))


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", str(value).lower())
        if token
    }


__all__ = ["match_playbooks"]
