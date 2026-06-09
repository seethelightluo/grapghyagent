"""Load optimizer-ready GraphRun traces."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_graph_runs(
    graph_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph_run_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    graphs_root = Path(workspace).expanduser().resolve() / "graphs"
    run_dirs = [graphs_root / run_id for run_id in graph_run_ids] if graph_run_ids else sorted(graphs_root.glob("*"))
    runs = []
    for run_dir in run_dirs:
        run_path = run_dir / "graph_run.json"
        if not run_path.exists():
            continue
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(run.get("graph_id") or "") != str(graph_id):
            continue
        run["node_runs_detail"] = _read_node_runs(run_dir)
        runs.append(run)
    runs.sort(key=lambda item: str(item.get("started_at") or ""))
    return runs


def _read_node_runs(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "traces" / "node_runs.jsonl"
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


__all__ = ["load_graph_runs"]
