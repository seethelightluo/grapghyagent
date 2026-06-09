"""Main interface for graph execution."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.config import load_graph_config
from ..core.graph_schema import graph_edges
from ..core.types import GraphConfig, utc_now
from .executor import GraphExecutionError, GraphExecutor
from .history import (
    graph_run_manifest,
    graph_run_errors,
    graph_run_outputs,
    graph_run_timeline,
    export_trace_dataset,
    list_graph_runs,
    read_graph_run,
    read_node_run,
    read_node_runs,
)


def run(config_path: str | Path, workspace: str | Path = ".graphyagent") -> dict:
    config = load_graph_config(config_path)
    return GraphExecutor(workspace).run_graph(config).to_dict()


def resume_from_checkpoint(
    graph: dict[str, Any],
    checkpoint: dict[str, Any],
    workspace: str | Path = ".graphyagent",
    *,
    resume_source: dict[str, Any] | None = None,
    reuse_policy: str = "strict_fingerprint",
) -> dict[str, Any]:
    checkpoint_state = checkpoint.get("state")
    if not isinstance(checkpoint_state, dict):
        raise ValueError("checkpoint is missing state")
    source = dict(resume_source or {})
    source.setdefault("checkpoint", checkpoint)
    if checkpoint.get("graph_run_id"):
        source.setdefault("source_graph_run_id", checkpoint.get("graph_run_id"))
    manifest = checkpoint.get("manifest") if isinstance(checkpoint.get("manifest"), dict) else {}
    if manifest.get("graph_run_id"):
        source.setdefault("source_graph_run_id", manifest.get("graph_run_id"))
    if checkpoint.get("checkpoint_id"):
        source.setdefault("checkpoint_id", checkpoint.get("checkpoint_id"))
    return GraphExecutor(workspace).run_graph(
        GraphConfig.from_dict(graph),
        initial_state=checkpoint_state,
        skip_completed=True,
        resume_source=source,
        reuse_policy=reuse_policy,
    ).to_dict()


def classify_node_failure(
    workspace: str | Path = ".graphyagent",
    graph_run_id: str | None = None,
    *,
    node_run_id: str | None = None,
    node_id: str | None = None,
    error: str | None = None,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a failed NodeRun without starting a recovery loop."""
    if not graph_run_id and not error:
        raise ValueError("classify_node_failure requires graph_run_id or error")

    run: dict[str, Any] = {}
    node_run: dict[str, Any] = {}
    lookup_errors: list[str] = []
    if graph_run_id:
        try:
            run = read_graph_run(workspace, str(graph_run_id))
        except Exception as exc:  # noqa: BLE001
            lookup_errors.append(f"graph_run_lookup_failed: {exc}")
        try:
            node_run = _resolve_node_run(
                workspace,
                str(graph_run_id),
                node_run_id=node_run_id,
                node_id=node_id,
            )
        except Exception as exc:  # noqa: BLE001
            lookup_errors.append(f"node_run_lookup_failed: {exc}")

    resolved_node_id = (
        str(node_id or "")
        or str(node_run.get("node_id") or "")
        or _node_id_from_error(str(error or run.get("error") or ""))
    )
    error_text = str(
        error
        or node_run.get("error")
        or run.get("error")
        or _node_result_error(run, resolved_node_id)
        or ""
    )
    if not error_text and node_run.get("status") not in {"failed", "error"}:
        return {
            "schema": "graphyagent.failure_analysis.v1",
            "status": "no_failure_detected",
            "graph_run_id": graph_run_id,
            "node_run_id": node_run.get("node_run_id") or node_run_id,
            "node_id": resolved_node_id or None,
            "failure_scope": "none",
            "confidence": 0.0,
            "signals": lookup_errors,
            "should_pause_graph_run": False,
            "recommended_next_modules": [],
            "created_at": utc_now(),
        }

    inference = _infer_failure_scope(error_text, node_run=node_run, run=run, graph=graph)
    recommendations = _failure_recommendations(inference["failure_scope"], inference["failure_type"])
    return {
        "schema": "graphyagent.failure_analysis.v1",
        "status": "classified",
        "graph_run_id": graph_run_id,
        "node_run_id": node_run.get("node_run_id") or node_run_id,
        "node_id": resolved_node_id or None,
        "failure_scope": inference["failure_scope"],
        "failure_type": inference["failure_type"],
        "confidence": inference["confidence"],
        "signals": [*lookup_errors, *inference["signals"]],
        "error": error_text,
        "should_pause_graph_run": inference["failure_scope"] in {"graph_level", "plan_level"},
        "recommended_next_modules": recommendations,
        "next_action": _failure_next_action(inference["failure_scope"], inference["failure_type"]),
        "created_at": utc_now(),
    }


def pause_for_replan(
    workspace: str | Path = ".graphyagent",
    graph_run_id: str | None = None,
    *,
    node_run_id: str | None = None,
    node_id: str | None = None,
    reason: str = "",
    failure_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a GraphRun as paused so agent_runtime can replan around it."""
    if not graph_run_id:
        raise ValueError("pause_for_replan requires graph_run_id")
    run_dir = _graph_run_dir(workspace, str(graph_run_id))
    run_path = run_dir / "graph_run.json"
    now = utc_now()
    event = {
        "schema": "graphyagent.replan_pause_event.v1",
        "event_type": "paused_for_replan",
        "graph_run_id": str(graph_run_id),
        "node_run_id": node_run_id,
        "node_id": node_id or (failure_analysis or {}).get("node_id"),
        "reason": reason or (failure_analysis or {}).get("error") or "graph recovery requested",
        "failure_analysis": deepcopy(failure_analysis or {}),
        "created_at": now,
    }
    run_record_updated = False
    if run_path.exists():
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["status"] = "paused_for_replan"
        run["paused_for_replan_at"] = now
        run["replan_reason"] = event["reason"]
        run["failure_analysis"] = event["failure_analysis"]
        run_path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
        run_record_updated = True
    _append_jsonl(run_dir / "traces" / "replan_events.jsonl", event)
    return {
        "schema": "graphyagent.pause_for_replan.v1",
        "graph_run_id": str(graph_run_id),
        "status": "paused_for_replan",
        "run_record_updated": run_record_updated,
        "run_path": str(run_path),
        "event": event,
    }


def mark_edges_blocked(
    graph: dict[str, Any],
    failed_node_id: str,
    *,
    replacement_node_id: str | None = None,
    downstream_node_ids: list[str] | None = None,
    status: str = "blocked_for_replan",
    reason: str = "",
    rewrite_dependencies: bool = False,
) -> dict[str, Any]:
    """Return a graph copy with failed-node outgoing edges marked blocked."""
    if not isinstance(graph, dict):
        raise ValueError("mark_edges_blocked requires graph")
    failed_node_id = str(failed_node_id or "")
    if not failed_node_id:
        raise ValueError("mark_edges_blocked requires failed_node_id")

    patched = deepcopy(graph)
    now = utc_now()
    normalized_edges = graph_edges(patched)
    requested_downstream = {str(item) for item in (downstream_node_ids or []) if str(item)}
    restrict_downstream = bool(requested_downstream)
    affected_node_ids = {
        str(edge.get("target_node_id") or edge.get("target"))
        for edge in normalized_edges
        if str(edge.get("source_node_id") or edge.get("source")) == failed_node_id
    }
    if restrict_downstream:
        affected_node_ids &= requested_downstream
    affected_node_ids.discard("")

    blocked_edges: list[dict[str, Any]] = []
    for edge in patched.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source_node_id") or edge.get("source") or edge.get("from_node_id") or edge.get("from") or "")
        target = str(edge.get("target_node_id") or edge.get("target") or edge.get("to_node_id") or edge.get("to") or "")
        if source != failed_node_id or (restrict_downstream and target not in affected_node_ids):
            continue
        edge["status"] = status
        edge["blocked"] = True
        edge_meta = edge.setdefault("metadata", {}).setdefault("graphyagent", {})
        edge_meta.update({
            "status": status,
            "blocked_by_node": failed_node_id,
            "replacement_node_id": replacement_node_id,
            "reason": reason,
            "updated_at": now,
        })
        blocked_edges.append(_blocked_edge_record(failed_node_id, target, edge, status, reason, replacement_node_id))

    for node in patched.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        target = str(node.get("id") or node.get("node_id") or "")
        deps = [str(dep) for dep in _node_dependencies(node)]
        if failed_node_id not in deps or (restrict_downstream and target not in affected_node_ids):
            continue
        node_meta = node.setdefault("metadata", {}).setdefault("graphyagent", {})
        records = node_meta.setdefault("blocked_upstream_edges", [])
        record = {
            "source": failed_node_id,
            "target": target,
            "status": status,
            "reason": reason,
            "replacement_node_id": replacement_node_id,
            "updated_at": now,
        }
        records.append(record)
        if rewrite_dependencies and replacement_node_id:
            node["depends_on"] = [
                str(replacement_node_id) if dep == failed_node_id else dep
                for dep in deps
            ]
            node_meta.setdefault("replan_dependency_rewrites", []).append(record)
        blocked_edges.append(record)
        affected_node_ids.add(target)

    graph_meta = patched.setdefault("metadata", {}).setdefault("graphyagent", {})
    graph_meta.setdefault("blocked_edges", []).extend(blocked_edges)
    graph_meta["updated_at"] = now
    return {
        "schema": "graphyagent.mark_edges_blocked.v1",
        "graph": patched,
        "failed_node_id": failed_node_id,
        "replacement_node_id": replacement_node_id,
        "status": status,
        "rewrite_dependencies": rewrite_dependencies,
        "affected_node_ids": sorted(affected_node_ids),
        "blocked_edges": blocked_edges,
    }


def commands(target_type: str | None = None) -> list[dict]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("graph_runner", target_type)


def _graph_run_dir(workspace: str | Path, graph_run_id: str) -> Path:
    return Path(workspace).expanduser().resolve() / "graphs" / graph_run_id


def _resolve_node_run(
    workspace: str | Path,
    graph_run_id: str,
    *,
    node_run_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    if node_run_id or node_id:
        return read_node_run(workspace, graph_run_id, node_run_id=node_run_id, node_id=node_id)
    failed = [
        item for item in read_node_runs(workspace, graph_run_id)
        if item.get("status") in {"failed", "error"} or item.get("error")
    ]
    if failed:
        failed.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return failed[0]
    return {}


def _node_result_error(run: dict[str, Any], node_id: str | None) -> str | None:
    if not node_id:
        return None
    result = ((run.get("final_state") or {}).get("node_results") or {}).get(node_id)
    if isinstance(result, dict):
        return result.get("error")
    return None


def _node_id_from_error(error_text: str) -> str:
    marker = "node "
    lowered = error_text.lower()
    if marker not in lowered:
        return ""
    start = lowered.find(marker) + len(marker)
    tail = error_text[start:].strip()
    for sep in (":", " ", "\n", "\t"):
        if sep in tail:
            return tail.split(sep, 1)[0].strip("`'\"")
    return tail.strip("`'\"")


def _infer_failure_scope(
    error_text: str,
    *,
    node_run: dict[str, Any],
    run: dict[str, Any],
    graph: dict[str, Any] | None,
) -> dict[str, Any]:
    text = " ".join([
        error_text,
        json.dumps((node_run.get("call") or {}).get("executor") or {}, ensure_ascii=False),
        json.dumps((node_run.get("input_snapshot") or {}).get("lineage_context") or {}, ensure_ascii=False),
    ]).lower()
    groups = [
        (
            "plan_level",
            "graph_topology_or_plan",
            [
                "cycle",
                "no runnable",
                "depends_on",
                "dependency",
                "missing upstream",
                "blocked gate",
                "gate closed",
                "workflow",
                "plan",
                "topology",
            ],
        ),
        (
            "graph_level",
            "contract_or_evidence_flow",
            [
                "required input",
                "input contract",
                "output contract",
                "contract failure",
                "missing artifact",
                "artifact not found",
                "lineage",
                "fingerprint",
                "stale",
                "insufficient evidence",
                "schema",
                "field",
                "column",
            ],
        ),
        (
            "node_local",
            "environment_or_executor",
            [
                "cuda",
                "gpu",
                "out of memory",
                "oom",
                "module not found",
                "no such file",
                "permission denied",
                "timeout",
                "connection",
                "http",
                "sqlite",
                "subprocess",
                "exit code",
            ],
        ),
        (
            "node_local",
            "model_or_prompt",
            [
                "llm",
                "model",
                "rate limit",
                "invalid json",
                "jsondecode",
                "parse",
                "tool",
                "prompt",
                "completion",
            ],
        ),
    ]
    matches: list[tuple[str, str, str]] = []
    for scope, failure_type, terms in groups:
        for term in terms:
            if term in text:
                matches.append((scope, failure_type, term))
    if matches:
        scope, failure_type, _ = matches[0]
        confidence = min(0.95, 0.55 + len(matches) * 0.08)
    elif run.get("status") == "failed" and not node_run:
        scope, failure_type, confidence = "graph_level", "unknown_graph_failure", 0.45
    else:
        scope, failure_type, confidence = "node_local", "unknown_node_failure", 0.35

    if graph and node_run.get("node_id"):
        downstream = [
            str(edge.get("target_node_id") or edge.get("target"))
            for edge in graph_edges(graph)
            if str(edge.get("source_node_id") or edge.get("source")) == str(node_run.get("node_id"))
        ]
        if downstream and scope == "node_local" and "required" in text:
            scope, failure_type, confidence = "graph_level", "blocked_downstream_inputs", max(confidence, 0.68)
    return {
        "failure_scope": scope,
        "failure_type": failure_type,
        "confidence": round(confidence, 2),
        "signals": [f"{failure_type}:{term}" for _, failure_type, term in matches],
    }


def _failure_recommendations(failure_scope: str, failure_type: str) -> list[str]:
    if failure_scope in {"graph_level", "plan_level"}:
        return [
            "graph_runner.pause_for_replan",
            "graph_runner.mark_edges_blocked",
            "task_decompose.replan_subgraph",
            "agent_runtime.recover_graph_failure",
        ]
    if failure_type == "environment_or_executor":
        return ["model_routing.route_node", "task_decompose.decompose_node", "node_audit.validate_node_contract"]
    return ["model_routing.route_node", "task_decompose.decompose_node"]


def _failure_next_action(failure_scope: str, failure_type: str) -> str:
    if failure_scope in {"graph_level", "plan_level"}:
        return "pause graph run and ask agent_runtime to replan a replacement subgraph"
    if failure_type == "environment_or_executor":
        return "retry the node with model routing or a decomposed local execution strategy"
    return "retry or decompose the failed node locally"


def _node_dependencies(node: dict[str, Any]) -> list[str]:
    deps = node.get("depends_on")
    if deps is None:
        deps = node.get("dependencies")
    if isinstance(deps, str):
        return [deps]
    if isinstance(deps, list):
        return [str(item) for item in deps if str(item)]
    return []


def _blocked_edge_record(
    source: str,
    target: str,
    edge: dict[str, Any],
    status: str,
    reason: str,
    replacement_node_id: str | None,
) -> dict[str, Any]:
    return {
        "edge_id": edge.get("edge_id") or edge.get("id") or f"{source}->{target}",
        "source": source,
        "target": target,
        "status": status,
        "reason": reason,
        "replacement_node_id": replacement_node_id,
        "updated_at": utc_now(),
    }


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


__all__ = [
    "GraphExecutionError",
    "GraphExecutor",
    "classify_node_failure",
    "commands",
    "graph_run_manifest",
    "graph_run_errors",
    "graph_run_outputs",
    "graph_run_timeline",
    "export_trace_dataset",
    "list_graph_runs",
    "read_graph_run",
    "read_node_run",
    "read_node_runs",
    "mark_edges_blocked",
    "pause_for_replan",
    "run",
    "resume_from_checkpoint",
]
