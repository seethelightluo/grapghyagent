"""GraphRun and NodeRun history queries."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.types import utc_now


def list_graph_runs(workspace: str | Path) -> list[dict[str, Any]]:
    graphs_root = _graphs_root(workspace)
    if not graphs_root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for run_json in graphs_root.glob("*/graph_run.json"):
        try:
            run = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs.append(_graph_run_summary(run, run_json.parent))
    return sorted(runs, key=lambda item: str(item.get("started_at") or ""), reverse=True)


def read_graph_run(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    run_json = _graph_run_dir(workspace, graph_run_id) / "graph_run.json"
    if not run_json.exists():
        raise FileNotFoundError(f"graph run not found: {graph_run_id}")
    return json.loads(run_json.read_text(encoding="utf-8"))


def read_node_runs(workspace: str | Path, graph_run_id: str) -> list[dict[str, Any]]:
    traces_path = _graph_run_dir(workspace, graph_run_id) / "traces" / "node_runs.jsonl"
    if not traces_path.exists():
        return []
    node_runs: list[dict[str, Any]] = []
    for line in traces_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            node_runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return node_runs


def read_node_run(
    workspace: str | Path,
    graph_run_id: str,
    *,
    node_run_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    matches = [
        item
        for item in read_node_runs(workspace, graph_run_id)
        if (not node_run_id or item.get("node_run_id") == node_run_id)
        and (not node_id or item.get("node_id") == node_id)
    ]
    if not matches:
        target = node_run_id or node_id or "<unspecified>"
        raise FileNotFoundError(f"node run not found: {graph_run_id}:{target}")
    matches.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    detail = matches[0]
    detail["files"] = _node_run_files(detail, workspace)
    detail["summary"] = _node_run_summary(detail, workspace)
    return detail


def graph_run_timeline(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    run = read_graph_run(workspace, graph_run_id)
    node_runs = read_node_runs(workspace, graph_run_id)
    events = [
        {
            "event_type": "graph_run",
            "graph_run_id": run.get("graph_run_id"),
            "graph_id": run.get("graph_id"),
            "status": run.get("status"),
            "started_at": run.get("started_at"),
            "ended_at": run.get("ended_at"),
            "duration_ms": _duration_ms(run.get("started_at"), run.get("ended_at")),
            "error": run.get("error"),
        }
    ]
    for node_run in node_runs:
        events.append({
            "event_type": "node_run",
            **_node_run_summary(node_run, workspace),
        })
    events.sort(key=lambda item: str(item.get("started_at") or ""))
    return {
        "graph_run": _graph_run_summary(run, _graph_run_dir(workspace, graph_run_id)),
        "events": events,
    }


def graph_run_outputs(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    run = read_graph_run(workspace, graph_run_id)
    final_state = run.get("final_state") or {}
    artifacts = final_state.get("artifacts") or {}
    node_results = final_state.get("node_results") or {}
    node_outputs: dict[str, list[dict[str, Any]]] = {}
    for node_id, result in sorted(node_results.items()):
        outputs = []
        for name, artifact_id in sorted((result.get("outputs") or {}).items()):
            artifact = artifacts.get(artifact_id) or {}
            metadata = artifact.get("metadata") or {}
            outputs.append({
                "name": name,
                "artifact_id": artifact_id,
                "path": artifact.get("uri"),
                "type": artifact.get("type"),
                "size": metadata.get("size"),
                "sha256": metadata.get("sha256"),
            })
        node_outputs[node_id] = outputs
    return {
        "graph_run_id": graph_run_id,
        "graphoutput": _list_files(_graph_run_dir(workspace, graph_run_id) / "graphoutput"),
        "node_outputs": node_outputs,
    }


def graph_run_manifest(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    run_dir = _graph_run_dir(workspace, graph_run_id)
    run = read_graph_run(workspace, graph_run_id)
    graph_config = run.get("graph_config") or _read_optional_json(run_dir / "graph_config.json") or {}
    experiment = run.get("experiment") or graph_config.get("experiment") or {}
    providers = []
    for provider in graph_config.get("providers") or []:
        providers.append({
            "provider_id": provider.get("provider_id") or provider.get("id"),
            "model_count": len(provider.get("models") or []),
            "models": [
                model if isinstance(model, str) else model.get("model_id") or model.get("id")
                for model in (provider.get("models") or [])
            ],
        })
    outputs = graph_run_outputs(workspace, graph_run_id)
    return {
        "schema": "graphyagent.graph_run_manifest.v1",
        "graph_run": _graph_run_summary(run, run_dir),
        "graph_config": {
            "graph_id": graph_config.get("graph_id"),
            "node_count": len(graph_config.get("nodes") or []),
            "output_nodes": list(graph_config.get("output_nodes") or []),
            "config_sha256": run.get("config_sha256"),
            "graph_config_path": run.get("graph_config_path") or str(run_dir / "graph_config.json"),
        },
        "experiment": experiment,
        "router": graph_config.get("router") or {},
        "providers": providers,
        "outputs": {
            "graphoutput_count": len(outputs.get("graphoutput") or []),
            "node_output_counts": {
                node_id: len(items)
                for node_id, items in (outputs.get("node_outputs") or {}).items()
            },
        },
    }


def graph_run_errors(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    run = read_graph_run(workspace, graph_run_id)
    errors = []
    if run.get("error"):
        errors.append({
            "scope": "graph",
            "graph_run_id": graph_run_id,
            "error": run.get("error"),
            "started_at": run.get("started_at"),
            "ended_at": run.get("ended_at"),
        })
    for node_run in read_node_runs(workspace, graph_run_id):
        if node_run.get("error") or node_run.get("status") == "failed":
            errors.append({
                "scope": "node",
                "graph_run_id": graph_run_id,
                "node_run_id": node_run.get("node_run_id"),
                "node_id": node_run.get("node_id"),
                "status": node_run.get("status"),
                "error": node_run.get("error"),
                "started_at": node_run.get("started_at"),
                "ended_at": node_run.get("ended_at"),
                "logs": _node_log_paths(node_run, workspace),
            })
    return {
        "graph_run_id": graph_run_id,
        "errors": errors,
    }


def export_trace_dataset(
    workspace: str | Path,
    graph_run_id: str,
    *,
    output_dir: str | Path | None = None,
    max_chars_per_file: int = 4000,
) -> dict[str, Any]:
    """Export GraphRun/NodeRun traces as a JSONL dataset for training/review."""
    run = read_graph_run(workspace, graph_run_id)
    node_runs = read_node_runs(workspace, graph_run_id)
    run_dir = _graph_run_dir(workspace, graph_run_id)
    dataset_root = (
        Path(output_dir).expanduser().resolve()
        if output_dir
        else run_dir / "trace_datasets"
    )
    dataset_root.mkdir(parents=True, exist_ok=True)
    jsonl_path = dataset_root / f"{_safe_filename(graph_run_id)}_trace_dataset.jsonl"
    manifest_path = dataset_root / f"{_safe_filename(graph_run_id)}_trace_dataset_manifest.json"
    max_chars = max(0, int(max_chars_per_file))
    records = [
        _trace_dataset_record(run, node_run, max_chars)
        for node_run in node_runs
    ]
    with jsonl_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    manifest = {
        "schema": "graphyagent.trace_dataset_manifest.v1",
        "graph_run_id": graph_run_id,
        "graph_id": run.get("graph_id"),
        "status": run.get("status"),
        "created_at": utc_now(),
        "record_count": len(records),
        "success_count": sum(1 for item in records if item.get("status") == "success"),
        "failed_count": sum(1 for item in records if item.get("status") == "failed"),
        "jsonl_path": str(jsonl_path),
        "source_run_path": str(run_dir / "graph_run.json"),
        "source_node_runs_path": str(run_dir / "traces" / "node_runs.jsonl"),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "graph_run_id": graph_run_id,
        "record_count": len(records),
        "paths": {
            "jsonl": str(jsonl_path),
            "manifest": str(manifest_path),
        },
        "manifest": manifest,
        "preview": records[:3],
    }


def _graph_run_summary(run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "graph_run_id": run.get("graph_run_id"),
        "graph_id": run.get("graph_id"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "duration_ms": _duration_ms(run.get("started_at"), run.get("ended_at")),
        "run_dir": run.get("run_dir") or str(run_dir),
        "output_dir": run.get("output_dir"),
        "node_run_count": len(run.get("node_runs") or []),
        "config_sha256": run.get("config_sha256"),
        "error": run.get("error"),
    }


def _node_run_summary(node_run: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
    result = (node_run.get("output_snapshot") or {}).get("result") or {}
    return {
        "graph_run_id": node_run.get("graph_run_id"),
        "node_run_id": node_run.get("node_run_id"),
        "node_id": node_run.get("node_id"),
        "status": node_run.get("status"),
        "started_at": node_run.get("started_at"),
        "ended_at": node_run.get("ended_at"),
        "duration_ms": node_run.get("duration_ms"),
        "input_count": len((node_run.get("input_snapshot") or {}).get("inputs") or {}),
        "output_count": len((node_run.get("output_snapshot") or {}).get("artifacts") or {}),
        "executor_type": ((node_run.get("call") or {}).get("executor") or {}).get("type"),
        "routing": (node_run.get("call") or {}).get("routing") or {},
        "error": node_run.get("error"),
        "logs": _node_log_paths(node_run, workspace),
        "stdout": result.get("stdout"),
        "stderr": result.get("stderr"),
    }


def _node_run_files(node_run: dict[str, Any], workspace: str | Path) -> dict[str, Any]:
    return {
        "inputs": [
            _artifact_file(name, artifact)
            for name, artifact in sorted(((node_run.get("input_snapshot") or {}).get("inputs") or {}).items())
        ],
        "outputs": [
            _artifact_file(name, artifact)
            for name, artifact in sorted(((node_run.get("output_snapshot") or {}).get("artifacts") or {}).items())
        ],
        "logs": _node_log_paths(node_run, workspace),
    }


def _trace_dataset_record(
    run: dict[str, Any],
    node_run: dict[str, Any],
    max_chars_per_file: int,
) -> dict[str, Any]:
    input_files = [
        _artifact_file_with_excerpt(name, artifact, max_chars_per_file)
        for name, artifact in sorted(((node_run.get("input_snapshot") or {}).get("inputs") or {}).items())
    ]
    output_files = [
        _artifact_file_with_excerpt(name, artifact, max_chars_per_file)
        for name, artifact in sorted(((node_run.get("output_snapshot") or {}).get("artifacts") or {}).items())
    ]
    user_payload = {
        "graph_id": run.get("graph_id"),
        "node_id": node_run.get("node_id"),
        "executor": (node_run.get("call") or {}).get("executor") or {},
        "routing": (node_run.get("call") or {}).get("routing") or {},
        "input_snapshot": {
            "depends_on": (node_run.get("input_snapshot") or {}).get("depends_on") or {},
            "experiment": (node_run.get("input_snapshot") or {}).get("experiment") or {},
            "context_keys": (node_run.get("input_snapshot") or {}).get("context_keys") or [],
            "files": input_files,
            "node_memory_packet": (node_run.get("input_snapshot") or {}).get("node_memory_packet") or {},
        },
    }
    return {
        "schema": "graphyagent.trace_dataset.v1",
        "record_id": f"{node_run.get('graph_run_id')}:{node_run.get('node_run_id')}",
        "graph_run_id": node_run.get("graph_run_id"),
        "graph_id": run.get("graph_id"),
        "node_run_id": node_run.get("node_run_id"),
        "node_id": node_run.get("node_id"),
        "status": node_run.get("status"),
        "started_at": node_run.get("started_at"),
        "ended_at": node_run.get("ended_at"),
        "duration_ms": node_run.get("duration_ms"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are reviewing a GraphyAgent node execution trace. "
                    "Use only the provided inputs, routing, executor metadata, logs, and outputs."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
            {
                "role": "assistant",
                "content": _trace_assistant_content(node_run, output_files),
            },
        ],
        "input_files": input_files,
        "output_files": output_files,
        "call": node_run.get("call") or {},
        "result": (node_run.get("output_snapshot") or {}).get("result") or {},
        "node_memory_packet": (node_run.get("input_snapshot") or {}).get("node_memory_packet") or {},
        "online_reflection": (node_run.get("output_snapshot") or {}).get("online_reflection") or {},
        "error": node_run.get("error"),
        "reward": 1.0 if node_run.get("status") == "success" else 0.0,
        "metadata": {
            "trace_kind": "node_run",
            "source": "graphyagent",
            "graph_status": run.get("status"),
            "graph_started_at": run.get("started_at"),
            "graph_ended_at": run.get("ended_at"),
        },
    }


def _trace_assistant_content(node_run: dict[str, Any], output_files: list[dict[str, Any]]) -> str:
    if node_run.get("status") != "success":
        return f"Execution failed.\n\nError:\n{node_run.get('error') or ''}".strip()
    excerpts = [
        f"## {item['name']}\n{item['content_excerpt']}"
        for item in output_files
        if item.get("content_excerpt")
    ]
    if excerpts:
        return "Execution succeeded. Output excerpts:\n\n" + "\n\n".join(excerpts)
    result = (node_run.get("output_snapshot") or {}).get("result") or {}
    if result:
        return "Execution succeeded. Result metadata:\n\n" + json.dumps(result, ensure_ascii=False, indent=2)
    return "Execution succeeded."


def _artifact_file(name: str, artifact: dict[str, Any]) -> dict[str, Any]:
    metadata = artifact.get("metadata") or {}
    return {
        "name": name,
        "artifact_id": artifact.get("artifact_id"),
        "path": artifact.get("uri"),
        "type": artifact.get("type"),
        "size": metadata.get("size"),
        "sha256": metadata.get("sha256"),
        "original_name": metadata.get("original_name"),
    }


def _artifact_file_with_excerpt(
    name: str,
    artifact: dict[str, Any],
    max_chars_per_file: int,
) -> dict[str, Any]:
    item = _artifact_file(name, artifact)
    if max_chars_per_file > 0:
        excerpt = _read_text_excerpt(item.get("path"), max_chars_per_file)
        if excerpt:
            item["content_excerpt"] = excerpt
    return item


def _read_text_excerpt(path: str | None, max_chars: int) -> str:
    if not path:
        return ""
    source = Path(str(path))
    if not source.is_file():
        return ""
    try:
        raw = source.read_bytes()
    except OSError:
        return ""
    if b"\x00" in raw[:4096]:
        return ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="replace")
        except UnicodeError:
            return ""
    if not text:
        return ""
    suffix = "..." if len(text) > max_chars else ""
    return text[:max_chars] + suffix


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value))
    return cleaned.strip("._") or "trace_dataset"


def _node_log_paths(node_run: dict[str, Any], workspace: str | Path) -> dict[str, str]:
    result = (node_run.get("output_snapshot") or {}).get("result") or {}
    logs = {}
    if result.get("stdout"):
        logs["stdout"] = result["stdout"]
    if result.get("stderr"):
        logs["stderr"] = result["stderr"]
    run_dir = _node_run_dir(node_run, workspace)
    if run_dir:
        stdout = run_dir / "logs" / "stdout.txt"
        stderr = run_dir / "logs" / "stderr.txt"
        if stdout.exists():
            logs.setdefault("stdout", str(stdout))
        if stderr.exists():
            logs.setdefault("stderr", str(stderr))
    return logs


def _node_run_dir(node_run: dict[str, Any], workspace: str | Path) -> Path | None:
    graph_run_id = node_run.get("graph_run_id")
    node_id = node_run.get("node_id")
    node_run_id = node_run.get("node_run_id")
    summary_run_dir = (((node_run.get("output_snapshot") or {}).get("result") or {}).get("run_dir"))
    if summary_run_dir:
        return Path(str(summary_run_dir))
    if not (graph_run_id and node_id and node_run_id):
        return None
    return (
        _graph_run_dir(workspace, str(graph_run_id))
        / "nodes"
        / str(node_id)
        / "runs"
        / str(node_run_id)
    )


def _list_files(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        stat = path.stat()
        files.append({
            "name": path.name,
            "relative_path": path.relative_to(root).as_posix(),
            "path": str(path),
            "size": stat.st_size,
            "updated_at": stat.st_mtime,
        })
    return files


def _graphs_root(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve() / "graphs"


def _graph_run_dir(workspace: str | Path, graph_run_id: str) -> Path:
    return _graphs_root(workspace) / graph_run_id


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None
    try:
        from datetime import datetime

        start = datetime.fromisoformat(str(started_at))
        end = datetime.fromisoformat(str(ended_at))
        return int((end - start).total_seconds() * 1000)
    except (TypeError, ValueError):
        return None


__all__ = [
    "graph_run_errors",
    "graph_run_manifest",
    "graph_run_outputs",
    "graph_run_timeline",
    "list_graph_runs",
    "read_graph_run",
    "read_node_run",
    "read_node_runs",
]
