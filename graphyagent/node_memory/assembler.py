"""Assemble bounded Node Memory Packets."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from ..core.graph_schema import graph_edges
from ..core.memory_schema import NodeMemoryPacket
from ..core.types import GraphState, NodeSpec
from ..execution_lineage import RETRIEVAL_POLICY_VERSION, stable_hash
from ..knowledge_graph import build_for_project, build_view_for_node
from ..knowledge_graph.store import KnowledgeGraphStore
from ..memory.context import find_relevant_memories
from .budgeting import packet_budget
from .filters import knowledge_ids, trim_evidence_items
from .gap_tracker import update_gap_state as persist_gap_state


def prepare_node_context(
    *,
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
    graph_id: str | None = None,
    node_id: str,
    graph: dict[str, Any] | None = None,
    node: dict[str, Any] | NodeSpec | None = None,
    state: GraphState | dict[str, Any] | None = None,
    graph_run_id: str | None = None,
    node_run_id: str | None = None,
    run_dir: str | Path | None = None,
    input_snapshot: dict[str, Any] | None = None,
    lineage_context: dict[str, Any] | None = None,
    budget_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node_data = _node_to_dict(node, graph, node_id)
    resolved_graph_id = str(graph_id or (graph or {}).get("graph_id") or "graph")
    resolved_project_id = _infer_project_id(project_id, graph)
    budget = packet_budget(node_data, budget_override)
    if graph is not None:
        build_for_project(resolved_project_id, workspace=workspace, graph=graph)
    query = _node_query(node_data)
    view = build_view_for_node(
        resolved_project_id,
        resolved_graph_id,
        node_id,
        workspace=workspace,
        graph=None,
        query=query,
        limit=budget["background_items"] + budget["evidence_items"],
    )
    background_items = (view.get("background_items") or [])[: budget["background_items"]]
    evidence_items = trim_evidence_items(
        list(view.get("evidence_items") or []),
        limit=budget["evidence_items"],
        summary_chars=budget["evidence_summary_chars"],
    )
    legacy_items = _legacy_memory_items(
        workspace,
        graph,
        node_id,
        query,
        limit=max(0, budget["evidence_items"] - len(evidence_items)),
        summary_chars=budget["evidence_summary_chars"],
    )
    if legacy_items:
        evidence_items = trim_evidence_items(
            [*evidence_items, *legacy_items],
            limit=budget["evidence_items"],
            summary_chars=budget["evidence_summary_chars"],
        )
    required_upstream, optional_upstream = _upstream_outputs(
        node_data,
        _state_to_dict(state),
        input_snapshot,
        graph,
    )
    gaps = _evidence_gaps(node_data, required_upstream, evidence_items)
    missing_requirements = _missing_requirements(required_upstream, gaps)
    must_verify = _must_verify_before_output(node_data, missing_requirements)
    prohibited = _prohibited_assumptions(node_data, bool(gaps))
    packet = NodeMemoryPacket(
        packet_id=f"packet-{uuid.uuid4().hex[:12]}",
        project_id=resolved_project_id,
        graph_id=resolved_graph_id,
        node_id=node_id,
        graph_run_id=graph_run_id,
        node_run_id=node_run_id,
        node_goal=str(node_data.get("metadata", {}).get("name") or node_data.get("id") or node_id),
        node_purpose=str(node_data.get("metadata", {}).get("description") or node_data.get("task_type") or node_id),
        node_role=_node_role(node_data, graph),
        required_upstream_outputs=required_upstream,
        optional_upstream_outputs=optional_upstream,
        background_summary=str(view.get("background_summary") or "")[: budget["background_chars"]],
        evidence_candidates=evidence_items,
        unresolved_evidence_gaps=gaps,
        prohibited_assumptions=prohibited,
        known_facts=_known_facts(required_upstream, optional_upstream, evidence_items),
        missing_requirements=missing_requirements,
        confidence_by_requirement=_confidence_by_requirement(missing_requirements, evidence_items),
        must_verify_before_output=must_verify,
        tool_usage_hints=_tool_hints(node_data),
        stop_conditions=_stop_conditions(node_data),
        supplied_knowledge_ids=knowledge_ids(background_items, evidence_items),
        lineage_context=_lineage_context(lineage_context, required_upstream, optional_upstream),
        context_sources=_context_sources(lineage_context, background_items, evidence_items, view.get("quarantined_items") or []),
        retrieval_policy_version=RETRIEVAL_POLICY_VERSION,
        budget=budget,
        usage_log={
            "candidate_count": view.get("candidate_count", 0),
            "quarantined_count": len(view.get("quarantined_items") or []),
            "input_count": len((input_snapshot or {})),
        },
    ).to_dict()
    packet["packet_hash"] = stable_hash(_without_packet_hash(packet))
    if run_dir:
        _write_packet(run_dir, packet)
    if gaps and resolved_project_id != "runtime":
        persist_gap_state(resolved_project_id, resolved_graph_id, node_id, gaps, workspace=workspace)
    return packet


def summarize_context_for_model(packet: dict[str, Any]) -> str:
    lines = [
        "## Node Memory Packet",
        f"node_goal: {packet.get('node_goal') or ''}",
        f"node_purpose: {packet.get('node_purpose') or ''}",
    ]
    role = str(packet.get("node_role") or "").strip()
    if role:
        lines.append(f"node_role: {role}")
    required = packet.get("required_upstream_outputs") or []
    if required:
        lines.append("required_upstream_outputs:")
        lines.extend(f"- {item.get('node_id')}:{item.get('output_name')} ({item.get('status')})" for item in required)
    optional = packet.get("optional_upstream_outputs") or []
    if optional:
        lines.append("optional_upstream_outputs:")
        lines.extend(f"- {item.get('node_id')}:{item.get('output_name')} ({item.get('status')})" for item in optional[:8])
    known = packet.get("known_facts") or []
    if known:
        lines.append("known_facts:")
        lines.extend(f"- {item}" for item in known[:8])
    background = str(packet.get("background_summary") or "").strip()
    if background:
        lines.extend(["background_summary:", background])
    evidence = packet.get("evidence_candidates") or []
    if evidence:
        lines.append("evidence_candidates:")
        for item in evidence:
            lines.append(f"- {item.get('knowledge_id')}: {item.get('summary') or ''}")
    lineage = packet.get("lineage_context") if isinstance(packet.get("lineage_context"), dict) else {}
    if lineage:
        lines.append("lineage_context:")
        preflight = lineage.get("preflight") if isinstance(lineage.get("preflight"), dict) else {}
        if preflight:
            lines.append(f"- verifier: {preflight.get('verdict')} ({preflight.get('reason')})")
            lines.append(f"- input_fingerprint: {preflight.get('input_fingerprint')}")
        for item in (lineage.get("upstream_artifacts") or [])[:8]:
            lines.append(
                "- "
                f"{item.get('producer_node_id') or item.get('node_id')}:"
                f"{item.get('input_name') or item.get('output_name') or 'artifact'} "
                f"sha256={item.get('sha256') or item.get('artifact_id')} "
                f"status={item.get('status')}"
            )
    sources = packet.get("context_sources") if isinstance(packet.get("context_sources"), dict) else {}
    if sources:
        lines.append("context_sources:")
        for source_name in ["lineage_evidence", "kg_evidence", "legacy_memory", "external_quarantine"]:
            values = sources.get(source_name) or []
            if values:
                lines.append(f"- {source_name}: {', '.join(str(value) for value in values[:8])}")
    gaps = packet.get("unresolved_evidence_gaps") or []
    if gaps:
        lines.append("unresolved_evidence_gaps:")
        lines.extend(f"- {gap}" for gap in gaps)
    missing = packet.get("missing_requirements") or []
    if missing:
        lines.append("missing_requirements:")
        lines.extend(f"- {item}" for item in missing)
    must_verify = packet.get("must_verify_before_output") or []
    if must_verify:
        lines.append("must_verify_before_output:")
        lines.extend(f"- {item}" for item in must_verify)
    prohibited = packet.get("prohibited_assumptions") or []
    if prohibited:
        lines.append("prohibited_assumptions:")
        lines.extend(f"- {item}" for item in prohibited)
    hints = packet.get("tool_usage_hints") or []
    if hints:
        lines.append("tool_usage_hints:")
        lines.extend(f"- {hint}" for hint in hints)
    stops = packet.get("stop_conditions") or []
    if stops:
        lines.append("stop_conditions:")
        lines.extend(f"- {condition}" for condition in stops)
    text = "\n".join(lines)
    budget = packet.get("budget") if isinstance(packet.get("budget"), dict) else {}
    try:
        max_chars = int(budget.get("max_model_context_chars") or 12000)
    except (TypeError, ValueError):
        max_chars = 12000
    if max_chars > 0 and len(text) > max_chars:
        suffix = "\n[context truncated by node memory budget]"
        return text[: max(0, max_chars - len(suffix))] + suffix
    return text


def _without_packet_hash(packet: dict[str, Any]) -> dict[str, Any]:
    clone = dict(packet)
    clone.pop("packet_hash", None)
    return clone

def record_context_usage(
    project_id: str,
    usage: dict[str, Any],
    *,
    workspace: str | Path = ".graphyagent",
) -> dict[str, Any]:
    return KnowledgeGraphStore(workspace, project_id).record_context_usage(usage)


def update_gap_state(
    project_id: str,
    graph_id: str,
    node_id: str,
    gaps: list[str],
    *,
    workspace: str | Path = ".graphyagent",
    status: str = "open",
) -> dict[str, Any]:
    return persist_gap_state(project_id, graph_id, node_id, gaps, workspace=workspace, status=status)


def _node_to_dict(node: dict[str, Any] | NodeSpec | None, graph: dict[str, Any] | None, node_id: str) -> dict[str, Any]:
    if isinstance(node, NodeSpec):
        return node.to_dict()
    if isinstance(node, dict):
        return dict(node)
    for item in (graph or {}).get("nodes") or []:
        if str(item.get("id") or item.get("node_id")) == str(node_id):
            return dict(item)
    return {"id": node_id, "depends_on": [], "metadata": {}}


def _state_to_dict(state: GraphState | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(state, GraphState):
        return state.to_dict()
    if isinstance(state, dict):
        return state
    return {}


def _infer_project_id(project_id: str | None, graph: dict[str, Any] | None) -> str:
    if project_id:
        return str(project_id)
    meta = ((graph or {}).get("metadata") or {}).get("graphyagent") or {}
    return str(meta.get("project_id") or "runtime")


def _node_query(node: dict[str, Any]) -> str:
    meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    return " ".join(
        str(value)
        for value in [
            node.get("id"),
            node.get("task_type"),
            meta.get("name"),
            meta.get("description"),
            node.get("gate_condition"),
        ]
        if value
    )


def _upstream_outputs(
    node: dict[str, Any],
    state: dict[str, Any],
    input_snapshot: dict[str, Any] | None,
    graph: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required_names = _required_input_names(node)
    node_results = state.get("node_results") or {}
    required = []
    optional = []
    for dep in _upstream_node_ids(node, graph):
        result = node_results.get(str(dep)) or {}
        outputs = result.get("outputs") or {}
        if not outputs:
            item = {"node_id": str(dep), "output_name": None, "status": result.get("status") or "missing"}
            (required if str(dep) in required_names else optional).append(item)
            continue
        for output_name, artifact_id in outputs.items():
            item = {
                "node_id": str(dep),
                "output_name": str(output_name),
                "artifact_id": artifact_id,
                "status": result.get("status") or "unknown",
            }
            optional.append(item)
    for name in (input_snapshot or {}).keys():
        if str(name) in required_names and not any(item.get("output_name") == name for item in required):
            required.append({"node_id": None, "output_name": str(name), "status": "materialized_input"})
    return required, optional


def _lineage_context(
    preflight: dict[str, Any] | None,
    required_upstream: list[dict[str, Any]],
    optional_upstream: list[dict[str, Any]],
) -> dict[str, Any]:
    preflight = dict(preflight or {})
    return {
        "schema": "graphyagent.node_lineage_context.v1",
        "preflight": preflight,
        "input_artifacts": list(preflight.get("input_artifacts") or []),
        "upstream_artifacts": list(preflight.get("upstream_artifacts") or []),
        "required_upstream_outputs": required_upstream,
        "optional_upstream_outputs": optional_upstream,
    }


def _context_sources(
    preflight: dict[str, Any] | None,
    background_items: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    quarantined_items: list[dict[str, Any]],
) -> dict[str, Any]:
    lineage_ids = [
        str(item.get("artifact_id") or "")
        for item in (preflight or {}).get("input_artifacts", []) + (preflight or {}).get("upstream_artifacts", [])
        if item.get("artifact_id")
    ]
    kg_ids = [
        str(item.get("knowledge_id") or "")
        for item in [*background_items, *evidence_items]
        if item.get("knowledge_id") and str(item.get("knowledge_type") or "") != "legacy_memory"
    ]
    legacy_ids = [
        str(item.get("knowledge_id") or "")
        for item in evidence_items
        if str(item.get("knowledge_type") or "") == "legacy_memory" and item.get("knowledge_id")
    ]
    quarantine_ids = [
        str(item.get("knowledge_id") or "")
        for item in quarantined_items
        if item.get("knowledge_id")
    ]
    return {
        "lineage_evidence": _unique(lineage_ids),
        "kg_evidence": _unique(kg_ids),
        "legacy_memory": _unique(legacy_ids),
        "external_quarantine": _unique(quarantine_ids),
    }


def _legacy_memory_items(
    workspace: str | Path,
    graph: dict[str, Any] | None,
    node_id: str,
    query: str,
    *,
    limit: int,
    summary_chars: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        memories = find_relevant_memories(
            query,
            workspace_root=workspace,
            graph=graph,
            node_id=node_id,
            max_results=limit,
            max_chars_per_memory=max(200, summary_chars),
        )
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for memory in memories:
        content = str(memory.get("content") or "").strip()
        if not content:
            continue
        source = str(memory.get("file_path") or memory.get("name") or "")
        items.append({
            "knowledge_id": f"legacy_memory:{stable_hash({'source': source})[:16]}",
            "knowledge_type": "legacy_memory",
            "summary": content[: max(0, int(summary_chars))],
            "content_locator": source,
            "score": memory.get("score"),
            "score_features": {"source": "legacy_memory_adapter", "scope": memory.get("scope")},
            "access_policy": "internal",
        })
    return items


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _upstream_node_ids(node: dict[str, Any], graph: dict[str, Any] | None) -> list[str]:
    node_id = str(node.get("id") or node.get("node_id") or "")
    if graph is not None and node_id:
        upstream: list[str] = []
        for edge in graph_edges(graph):
            if str(edge.get("target_node_id") or "") == node_id:
                source = str(edge.get("source_node_id") or "")
                if source and source not in upstream:
                    upstream.append(source)
        if upstream:
            return upstream
    deps = node.get("depends_on")
    if deps is None:
        deps = node.get("deps")
    if isinstance(deps, str):
        return [deps]
    if isinstance(deps, list):
        return [str(item) for item in deps if str(item)]
    return []



def _node_role(node: dict[str, Any], graph: dict[str, Any] | None) -> str:
    policy = _context_policy(node)
    explicit = policy.get("node_role") or node.get("node_role") or node.get("role")
    if explicit:
        return str(explicit)
    node_type = str(node.get("node_type") or node.get("task_type") or "task")
    upstream_count = len(_upstream_node_ids(node, graph))
    output_roles = node.get("output_roles") if isinstance(node.get("output_roles"), dict) else {}
    output_names = ",".join(str(key) for key in output_roles) or "none"
    return f"{node_type}; upstream_count={upstream_count}; declared_outputs={output_names}"


def _context_policy(node: dict[str, Any]) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    if isinstance(metadata.get("context_policy"), dict):
        policy.update(metadata["context_policy"])
    if isinstance(node.get("context_policy"), dict):
        policy.update(node["context_policy"])
    return policy


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _known_facts(
    required_upstream: list[dict[str, Any]],
    optional_upstream: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
) -> list[str]:
    facts: list[str] = []
    for item in required_upstream + optional_upstream:
        if item.get("status") in {"success", "materialized_input"}:
            source = item.get("node_id") or "input"
            output = item.get("output_name") or "output"
            facts.append(f"{source}:{output} is available")
    for item in evidence_items[:5]:
        summary = str(item.get("summary") or item.get("knowledge_id") or "").strip()
        if summary:
            facts.append(summary[:240])
    return facts


def _missing_requirements(required_upstream: list[dict[str, Any]], gaps: list[str]) -> list[str]:
    missing = [
        f"{item.get('node_id')}:{item.get('output_name') or 'output'} status={item.get('status')}"
        for item in required_upstream
        if item.get("status") not in {"success", "materialized_input"}
    ]
    for gap in gaps:
        if gap not in missing:
            missing.append(str(gap))
    return missing


def _confidence_by_requirement(missing_requirements: list[str], evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    confidence: dict[str, Any] = {item: 0.0 for item in missing_requirements}
    for item in evidence_items:
        knowledge_id = str(item.get("knowledge_id") or "")
        if knowledge_id:
            confidence[knowledge_id] = round(float(item.get("score") or 0.0), 6)
    return confidence


def _must_verify_before_output(node: dict[str, Any], missing_requirements: list[str]) -> list[str]:
    policy = _context_policy(node)
    explicit = _string_list(policy.get("must_verify_before_output") or node.get("must_verify_before_output"))
    combined = list(explicit)
    for item in missing_requirements:
        if item not in combined:
            combined.append(item)
    return combined


def _prohibited_assumptions(node: dict[str, Any], has_gaps: bool) -> list[str]:
    policy = _context_policy(node)
    items = _string_list(policy.get("prohibited_assumptions") or node.get("prohibited_assumptions"))
    defaults = [
        "Do not infer facts that are absent from supplied upstream outputs or evidence candidates.",
        "Do not treat quarantined external knowledge as verified evidence.",
    ]
    if has_gaps:
        defaults.append("Do not close unresolved evidence gaps by assumption; report or verify them first.")
    for item in defaults:
        if item not in items:
            items.append(item)
    return items

def _required_input_names(node: dict[str, Any]) -> set[str]:
    names = set()
    interface = node.get("interface") if isinstance(node.get("interface"), dict) else {}
    for key in ("required_inputs", "inputs"):
        value = interface.get(key)
        if isinstance(value, list):
            names.update(str(item) for item in value)
    if isinstance(node.get("input_spec"), list):
        names.update(str(item) for item in node["input_spec"])
    return names


def _evidence_gaps(
    node: dict[str, Any],
    required_upstream: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
) -> list[str]:
    gaps: list[str] = []
    missing_required = [
        item for item in required_upstream
        if item.get("status") not in {"success", "materialized_input"}
    ]
    if missing_required:
        gaps.append("required upstream output is missing or not successful")
    if not evidence_items:
        gaps.append("no evidence candidates selected for this node")
    if node.get("gate_condition") and not evidence_items:
        gaps.append("gate condition has no supporting evidence item")
    return gaps


def _tool_hints(node: dict[str, Any]) -> list[str]:
    executor_type = str((node.get("executor") or node.get("runner") or {}).get("type") or "noop")
    hints = [f"executor_type={executor_type}"]
    if executor_type == "audit":
        hints.append("write audit outputs before LLM summarization")
    if executor_type == "llm":
        hints.append("use bounded packet evidence; do not infer from absent context")
    return hints


def _stop_conditions(node: dict[str, Any]) -> list[str]:
    conditions = []
    if node.get("gate_condition"):
        conditions.append(str(node["gate_condition"]))
    output_roles = node.get("output_roles") or {}
    if output_roles:
        conditions.append("declared output roles are produced")
    return conditions


def _write_packet(run_dir: str | Path, packet: dict[str, Any]) -> None:
    path = Path(run_dir) / "logs" / "node_memory_packet.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")


__all__ = [
    "prepare_node_context",
    "record_context_usage",
    "summarize_context_for_model",
    "update_gap_state",
]
