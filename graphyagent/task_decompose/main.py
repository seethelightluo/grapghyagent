"""Main interface for node task decomposition."""
from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.graph_schema import graph_edges
from ..core.types import utc_now
from ..data_manager.project_store import ProjectStore
from ..graph_runner.main import mark_edges_blocked
from .recovery import build_decompose_prompt, build_retry_prompt, decompose_task


def run(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    node_id: str,
    child_names: list[str] | None = None,
) -> dict[str, Any]:
    return ProjectStore(workspace).decompose_node(project_id, graph_id, node_id, child_names)


def decompose_task_to_graph(
    workspace: str | Path,
    project_id: str,
    prompt: str,
    *,
    graph_id: str | None = None,
    name: str | None = None,
    create_new_graph: bool = True,
) -> dict[str, Any]:
    return ProjectStore(workspace).decompose_task_to_graph(
        project_id,
        prompt,
        graph_id=graph_id,
        name=name,
        create_new_graph=create_new_graph,
    )


def replan_subgraph(
    workspace: str | Path,
    project_id: str,
    graph_id: str,
    failed_node_id: str,
    *,
    failure_analysis: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    replacement_strategy: str = "repair_then_retry",
    recovery_node_names: list[str] | None = None,
    rewrite_downstream_dependencies: bool = True,
    save: bool = False,
    apply: bool | None = None,
) -> dict[str, Any]:
    """Create a local recovery subgraph around a failed node."""
    failed_node_id = str(failed_node_id or "")
    if not failed_node_id:
        raise ValueError("replan_subgraph requires failed_node_id")
    store = ProjectStore(workspace)
    source_graph = deepcopy(graph) if isinstance(graph, dict) else store.read_graph(project_id, graph_id)
    failed_node = _find_node(source_graph, failed_node_id)
    if failed_node is None:
        raise FileNotFoundError(f"node not found: {failed_node_id}")

    now = utc_now()
    existing_ids = {str(node.get("id") or node.get("node_id")) for node in source_graph.get("nodes", [])}
    recovery_ids = _recovery_node_ids(failed_node_id, existing_ids, recovery_node_names)
    upstream_ids = _node_dependencies(failed_node)
    downstream_ids = _downstream_node_ids(source_graph, failed_node_id)
    failure_text = str((failure_analysis or {}).get("error") or failed_node.get("error") or "")

    candidate = deepcopy(source_graph)
    candidate_nodes = candidate.setdefault("nodes", [])
    candidate_failed = _find_node(candidate, failed_node_id)
    if candidate_failed is not None:
        recovery_meta = candidate_failed.setdefault("metadata", {}).setdefault("graphyagent", {})
        recovery_meta.setdefault("failure_recovery", []).append({
            "status": "superseded_for_replan",
            "replacement_node_id": recovery_ids["retry"],
            "strategy": replacement_strategy,
            "failure_analysis": deepcopy(failure_analysis or {}),
            "created_at": now,
        })

    recovery_nodes = _build_recovery_nodes(
        failed_node,
        recovery_ids,
        upstream_ids,
        failure_text=failure_text,
        failure_analysis=failure_analysis or {},
        strategy=replacement_strategy,
    )
    candidate_nodes.extend(recovery_nodes)

    blocked = mark_edges_blocked(
        candidate,
        failed_node_id,
        replacement_node_id=recovery_ids["retry"],
        downstream_node_ids=downstream_ids,
        status="blocked_for_replan",
        reason=failure_text or f"replan_subgraph for failed node {failed_node_id}",
        rewrite_dependencies=bool(rewrite_downstream_dependencies),
    )
    candidate = blocked["graph"]
    output_replacements = _replace_output_node(candidate, failed_node_id, recovery_ids["retry"])
    graph_meta = candidate.setdefault("metadata", {}).setdefault("graphyagent", {})
    graph_meta.setdefault("replan_subgraphs", []).append({
        "failed_node_id": failed_node_id,
        "recovery_node_ids": recovery_ids,
        "downstream_node_ids": downstream_ids,
        "strategy": replacement_strategy,
        "failure_scope": (failure_analysis or {}).get("failure_scope"),
        "created_at": now,
    })
    graph_meta["updated_at"] = now

    patch = {
        "nodes_added": [node["id"] for node in recovery_nodes],
        "failed_node_id": failed_node_id,
        "replacement_node_id": recovery_ids["retry"],
        "downstream_node_ids": downstream_ids,
        "blocked_edges": blocked.get("blocked_edges") or [],
        "rewrote_downstream_dependencies": bool(rewrite_downstream_dependencies),
        "output_node_replacements": output_replacements,
    }
    save_requested = bool(save if apply is None else apply)
    save_result = None
    if save_requested:
        save_result = store.save_graph(project_id, graph_id, candidate)
        store.append_memory_event(
            project_id,
            graph_id,
            {"type": "graph", "name": graph_id},
            "system",
            (
                "局部重规划：已围绕失败节点创建恢复分支。\n"
                f"- 失败节点：{failed_node_id}\n"
                f"- 替代节点：{recovery_ids['retry']}\n"
                f"- 影响下游：{', '.join(downstream_ids) or '无'}"
            ),
        )
    return {
        "schema": "graphyagent.replan_subgraph.v1",
        "status": "saved" if save_requested else "candidate",
        "project_id": project_id,
        "graph_id": graph_id,
        "failed_node_id": failed_node_id,
        "failure_analysis": deepcopy(failure_analysis or {}),
        "replacement_strategy": replacement_strategy,
        "patch": patch,
        "candidate_graph": candidate,
        "save_result": save_result,
    }


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("task_decompose", target_type)


def _find_node(graph: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for node in graph.get("nodes") or []:
        if str(node.get("id") or node.get("node_id")) == node_id:
            return node
    return None


def _node_dependencies(node: dict[str, Any]) -> list[str]:
    deps = node.get("depends_on")
    if deps is None:
        deps = node.get("dependencies")
    if isinstance(deps, str):
        return [deps]
    if isinstance(deps, list):
        return [str(item) for item in deps if str(item)]
    return []


def _downstream_node_ids(graph: dict[str, Any], node_id: str) -> list[str]:
    downstream = {
        str(edge.get("target_node_id") or edge.get("target"))
        for edge in graph_edges(graph)
        if str(edge.get("source_node_id") or edge.get("source")) == node_id
    }
    downstream.discard("")
    return sorted(downstream)


def _recovery_node_ids(
    failed_node_id: str,
    existing_ids: set[str],
    recovery_node_names: list[str] | None,
) -> dict[str, str]:
    base = _safe_node_id(failed_node_id)
    requested = [str(item).strip() for item in (recovery_node_names or []) if str(item).strip()]
    defaults = [
        f"{base}_failure_analysis",
        f"{base}_repair_inputs",
        f"{base}_retry",
    ]
    names = (requested + defaults)[:3]
    taken = set(existing_ids)
    analysis = _unique_id(_safe_node_id(names[0]), taken)
    repair = _unique_id(_safe_node_id(names[1]), taken)
    retry = _unique_id(_safe_node_id(names[2]), taken)
    return {"analysis": analysis, "repair": repair, "retry": retry}


def _build_recovery_nodes(
    failed_node: dict[str, Any],
    ids: dict[str, str],
    upstream_ids: list[str],
    *,
    failure_text: str,
    failure_analysis: dict[str, Any],
    strategy: str,
) -> list[dict[str, Any]]:
    failed_node_id = str(failed_node.get("id") or failed_node.get("node_id") or "")
    failure_scope = str(failure_analysis.get("failure_scope") or "unknown")
    analysis_node = _llm_recovery_node(
        ids["analysis"],
        upstream_ids,
        "failure_analysis",
        (
            "Analyze why the failed workflow node could not complete. "
            f"Failed node: {failed_node_id}. Failure scope: {failure_scope}. "
            f"Error: {failure_text or 'not provided'}. "
            "Use upstream outputs and lineage evidence only; identify whether the fix is input, executor, environment, or plan related."
        ),
    )
    repair_node = _llm_recovery_node(
        ids["repair"],
        [*upstream_ids, ids["analysis"]],
        "repair_plan",
        (
            "Prepare corrected inputs and an execution plan for retrying the failed node. "
            f"Strategy: {strategy}. "
            "Do not invent missing evidence; list missing artifacts explicitly and provide a bounded retry plan."
        ),
    )
    retry_node = deepcopy(failed_node)
    retry_node["id"] = ids["retry"]
    retry_node["depends_on"] = _dedupe([*upstream_ids, ids["repair"]])
    retry_node.setdefault("metadata", {})
    retry_node["metadata"] = deepcopy(retry_node.get("metadata") or {})
    retry_meta = retry_node["metadata"].setdefault("graphyagent", {})
    retry_meta.update({
        "replaces_node_id": failed_node_id,
        "recovery_strategy": strategy,
        "created_by": "task_decompose.replan_subgraph",
        "created_at": utc_now(),
    })
    executor = deepcopy(retry_node.get("executor") or {})
    if str(executor.get("type") or "llm").lower() == "llm":
        original_prompt = str(executor.get("prompt") or "")
        executor["prompt"] = (
            "You are retrying a GraphyAgent node after a localized recovery analysis. "
            f"The original failed node was `{failed_node_id}`. Use the repair plan from `{ids['repair']}` and the valid upstream outputs. "
            "If the task remains impossible, return explicit missing evidence instead of pretending completion.\n\n"
            f"Original node prompt:\n{original_prompt}"
        )
        executor.setdefault("output", "llm_result.md")
    retry_node["executor"] = executor or {"type": "llm", "output": "llm_result.md"}
    retry_node.setdefault("output_roles", failed_node.get("output_roles") or {"llm_result.md": "retry_result"})
    return [analysis_node, repair_node, retry_node]


def _llm_recovery_node(node_id: str, depends_on: list[str], task_type: str, prompt: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "task_type": task_type,
        "depends_on": _dedupe(depends_on),
        "executor": {
            "type": "llm",
            "output": "llm_result.md",
            "include_state": True,
            "input_char_limit": 60000,
            "prompt": prompt,
        },
        "output_roles": {"llm_result.md": task_type, "llm_call.json": "llm_call"},
        "routing": {"complexity": "complex"},
        "metadata": {
            "description": prompt,
            "graphyagent": {
                "created_by": "task_decompose.replan_subgraph",
                "created_at": utc_now(),
            },
        },
    }


def _replace_output_node(graph: dict[str, Any], failed_node_id: str, replacement_node_id: str) -> list[dict[str, str]]:
    replacements: list[dict[str, str]] = []
    output_nodes = graph.get("output_nodes") or []
    if not isinstance(output_nodes, list):
        return replacements
    new_outputs = []
    for node_id in output_nodes:
        if str(node_id) == failed_node_id:
            new_outputs.append(replacement_node_id)
            replacements.append({"old": failed_node_id, "new": replacement_node_id})
        else:
            new_outputs.append(node_id)
    graph["output_nodes"] = _dedupe([str(item) for item in new_outputs])
    return replacements


def _safe_node_id(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value).strip()).strip("_")
    return cleaned or "recovery_node"


def _unique_id(base: str, taken: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in taken:
        candidate = f"{base}_{index}"
        index += 1
    taken.add(candidate)
    return candidate


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = str(item or "")
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


__all__ = [
    "build_decompose_prompt",
    "build_retry_prompt",
    "commands",
    "decompose_task",
    "decompose_task_to_graph",
    "replan_subgraph",
    "run",
]
