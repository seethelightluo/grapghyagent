"""Online node-level reflection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.types import utc_now
from .heuristics import label_knowledge_usage, label_upstream_usage, suggested_weight_updates


def run_online_reflection(
    node_run_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph_run_id: str | None = None,
    node_id: str | None = None,
    input_snapshot: dict[str, Any] | None = None,
    output_snapshot: dict[str, Any] | None = None,
    status: str | None = None,
    error: str | None = None,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    loaded = None
    if input_snapshot is None or output_snapshot is None:
        loaded = _find_node_run(workspace, node_run_id, graph_run_id=graph_run_id)
    node_run = loaded or {}
    input_snapshot = input_snapshot if input_snapshot is not None else node_run.get("input_snapshot") or {}
    output_snapshot = output_snapshot if output_snapshot is not None else node_run.get("output_snapshot") or {}
    resolved_status = str(status or node_run.get("status") or "unknown")
    packet = input_snapshot.get("node_memory_packet") or {}
    upstream_labels = label_upstream_usage(input_snapshot, status=resolved_status)
    knowledge_labels = label_knowledge_usage(packet, status=resolved_status)
    reflection = {
        "schema": "graphyagent.online_reflection.v1",
        "node_run_id": node_run_id,
        "graph_run_id": graph_run_id or node_run.get("graph_run_id"),
        "node_id": node_id or node_run.get("node_id") or packet.get("node_id"),
        "created_at": utc_now(),
        "status": resolved_status,
        "error": error or node_run.get("error"),
        "used_upstream_nodes": [
            item["node_id"] for item in upstream_labels
            if item.get("label") in {"useful", "critical"}
        ],
        "unused_upstream_nodes": [
            item["node_id"] for item in upstream_labels
            if item.get("label") == "unused"
        ],
        "upstream_usage_labels": upstream_labels,
        "knowledge_usage_labels": knowledge_labels,
        "evidence_gap": list(packet.get("unresolved_evidence_gaps") or []),
        "external_search_was_needed": False,
        "suggested_weight_updates": suggested_weight_updates(knowledge_labels),
        "structure_mutation_allowed": False,
    }
    if run_dir:
        path = Path(run_dir) / "logs" / "online_reflection.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reflection, indent=2, ensure_ascii=False), encoding="utf-8")
    return reflection


def apply_feedback_updates(
    node_run_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph_run_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    from .feedback_update import apply_feedback_updates as _apply

    return _apply(node_run_id, workspace=workspace, graph_run_id=graph_run_id, project_id=project_id)


def _find_node_run(workspace: str | Path, node_run_id: str, *, graph_run_id: str | None = None) -> dict[str, Any] | None:
    graphs_root = Path(workspace).expanduser().resolve() / "graphs"
    run_dirs = [graphs_root / graph_run_id] if graph_run_id else sorted(graphs_root.glob("*"))
    for run_dir in run_dirs:
        path = run_dir / "traces" / "node_runs.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("node_run_id") == node_run_id:
                item.setdefault("graph_run_id", run_dir.name)
                return item
    return None


__all__ = ["apply_feedback_updates", "run_online_reflection"]
