"""Main interface for execution lineage module commands."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..core.lineage_schema import ExecutionLineageRecord
from ..core.types import GraphConfig, GraphState, NodeRun, NodeSpec, utc_now


RETRIEVAL_POLICY_VERSION = "lineage-context-v2"


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_node_inputs(
    *,
    workspace: str | Path = ".graphyagent",
    graph: dict[str, Any] | GraphConfig,
    node_id: str,
    state: dict[str, Any] | GraphState | None = None,
    graph_run_id: str | None = None,
    node_run_id: str | None = None,
    input_snapshot: dict[str, Any] | None = None,
    route_decision: dict[str, Any] | None = None,
    context_packet_hash: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic preflight view for a node's current inputs."""
    del workspace
    config = graph if isinstance(graph, GraphConfig) else GraphConfig.from_dict(graph)
    node = _node_by_id(config, node_id)
    state_obj = _state(state)
    input_items = _input_artifacts(input_snapshot or {}, state_obj)
    if not input_items:
        input_items = _configured_input_artifacts(node, state_obj)
    upstream_items = _upstream_artifacts(node, state_obj)
    missing = [
        item for item in input_items + upstream_items
        if item.get("status") not in {"available", "success", "materialized_input"}
    ]
    executor_signature = stable_hash(_executor_signature(node, route_decision))
    node_spec_hash = stable_hash(node.to_dict())
    fingerprint_payload = {
        "node_id": node.node_id,
        "node_spec_hash": node_spec_hash,
        "executor_signature": executor_signature,
        "input_artifacts": _fingerprint_artifacts(input_items),
        "upstream_artifacts": _fingerprint_artifacts(upstream_items),
        "context_packet_hash": context_packet_hash,
        "retrieval_policy_version": RETRIEVAL_POLICY_VERSION,
    }
    verdict = "blocked" if missing else "valid"
    return {
        "schema": "graphyagent.lineage_preflight.v1",
        "graph_run_id": graph_run_id,
        "node_run_id": node_run_id,
        "node_id": node.node_id,
        "created_at": utc_now(),
        "verdict": verdict,
        "reason": "missing input artifact" if missing else "inputs verified",
        "node_spec_hash": node_spec_hash,
        "executor_signature": executor_signature,
        "input_fingerprint": stable_hash(fingerprint_payload),
        "fingerprint_payload": fingerprint_payload,
        "input_artifacts": input_items,
        "upstream_artifacts": upstream_items,
        "missing_artifacts": missing,
        "retrieval_policy_version": RETRIEVAL_POLICY_VERSION,
    }


def record_node_lineage(
    *,
    workspace: str | Path = ".graphyagent",
    graph_run_id: str,
    node_run: dict[str, Any] | NodeRun,
    preflight_verdict: dict[str, Any] | None = None,
    postflight_verdict: dict[str, Any] | None = None,
    checkpoint_id: str | None = None,
    context_packet_hash: str | None = None,
) -> dict[str, Any]:
    """Persist a NodeRun lineage record under the GraphRun directory."""
    node_run_data = node_run.to_dict() if isinstance(node_run, NodeRun) else dict(node_run)
    input_snapshot = node_run_data.get("input_snapshot") or {}
    output_snapshot = node_run_data.get("output_snapshot") or {}
    packet = input_snapshot.get("node_memory_packet") if isinstance(input_snapshot, dict) else None
    if context_packet_hash is None and isinstance(packet, dict):
        context_packet_hash = str(packet.get("packet_hash") or stable_hash(_without_packet_hash(packet)))
    preflight = dict(preflight_verdict or input_snapshot.get("lineage_preflight") or {})
    output_artifacts = _output_artifacts(output_snapshot.get("artifacts") or {})
    postflight = dict(postflight_verdict or _postflight_from_outputs(output_artifacts, node_run_data))
    record = ExecutionLineageRecord(
        graph_run_id=str(graph_run_id),
        node_run_id=str(node_run_data.get("node_run_id") or ""),
        node_id=str(node_run_data.get("node_id") or preflight.get("node_id") or ""),
        input_fingerprint=str(preflight.get("input_fingerprint") or ""),
        input_artifacts=list(preflight.get("input_artifacts") or []),
        output_artifacts=output_artifacts,
        executor_signature=str(preflight.get("executor_signature") or ""),
        context_packet_hash=context_packet_hash,
        preflight_verdict=preflight,
        postflight_verdict=postflight,
        checkpoint_id=checkpoint_id,
    ).to_dict()
    path = _lineage_path(workspace, graph_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def plan_replay_from_checkpoint(
    *,
    workspace: str | Path = ".graphyagent",
    graph: dict[str, Any] | GraphConfig,
    checkpoint: dict[str, Any],
    current_state: dict[str, Any] | GraphState | None = None,
    source_graph_run_id: str | None = None,
    reuse_policy: str = "strict_fingerprint",
) -> dict[str, Any]:
    """Compare checkpoint lineage against the current graph and state."""
    config = graph if isinstance(graph, GraphConfig) else GraphConfig.from_dict(graph)
    checkpoint_state = checkpoint.get("state")
    if not isinstance(checkpoint_state, dict):
        raise ValueError("checkpoint is missing state")
    state = _state(current_state) if current_state is not None else GraphState.from_dict(checkpoint_state)
    source_run_id = str(source_graph_run_id or checkpoint.get("graph_run_id") or "")
    if not source_run_id:
        source_run_id = _infer_graph_run_id_from_checkpoint(checkpoint)
    previous_by_node = _latest_records_by_node(read_lineage_records(workspace, source_run_id)) if source_run_id else {}
    completed = {
        node_id
        for node_id, result in (checkpoint_state.get("node_results") or {}).items()
        if (result or {}).get("status") == "success"
    }
    reusable: list[str] = []
    dirty: list[str] = []
    fingerprints: dict[str, Any] = {}
    dirty_seen: set[str] = set()
    for node in _topological_nodes(config):
        if node.node_id not in completed:
            continue
        upstream_dirty = [dep for dep in node.depends_on if dep in dirty_seen]
        route_decision = None
        try:
            from ..model_routing.routing import route_model

            route_decision = route_model(config, node, state).to_dict()
        except Exception:
            route_decision = None
        current = verify_node_inputs(
            workspace=workspace,
            graph=config,
            node_id=node.node_id,
            state=state,
            route_decision=route_decision,
        )
        fingerprints[node.node_id] = {
            "current": current.get("input_fingerprint"),
            "previous": (previous_by_node.get(node.node_id) or {}).get("input_fingerprint"),
        }
        previous = previous_by_node.get(node.node_id)
        fingerprint_matches = bool(previous) and previous.get("input_fingerprint") == current.get("input_fingerprint")
        if reuse_policy == "reuse_completed":
            fingerprint_matches = bool(previous or node.node_id in completed)
        if upstream_dirty or not fingerprint_matches:
            dirty_seen.add(node.node_id)
            dirty.append(node.node_id)
        else:
            reusable.append(node.node_id)
    return {
        "schema": "graphyagent.lineage_replay_plan.v1",
        "source_graph_run_id": source_run_id,
        "checkpoint_id": checkpoint.get("checkpoint_id") or checkpoint.get("id"),
        "reuse_policy": reuse_policy,
        "completed_node_ids": sorted(completed),
        "reusable_node_ids": reusable,
        "dirty_node_ids": dirty,
        "fingerprints": fingerprints,
        "created_at": utc_now(),
    }


def list_dirty_nodes(
    *,
    workspace: str | Path = ".graphyagent",
    graph: dict[str, Any] | GraphConfig | None = None,
    checkpoint: dict[str, Any] | None = None,
    current_state: dict[str, Any] | GraphState | None = None,
    graph_run_id: str | None = None,
    reuse_policy: str = "strict_fingerprint",
) -> dict[str, Any]:
    if graph is not None and checkpoint is not None:
        plan = plan_replay_from_checkpoint(
            workspace=workspace,
            graph=graph,
            checkpoint=checkpoint,
            current_state=current_state,
            source_graph_run_id=graph_run_id,
            reuse_policy=reuse_policy,
        )
        return {
            "schema": "graphyagent.lineage_dirty_nodes.v1",
            "dirty_node_ids": plan["dirty_node_ids"],
            "reusable_node_ids": plan["reusable_node_ids"],
            "plan": plan,
        }
    records = read_lineage_records(workspace, str(graph_run_id or ""))
    dirty = [
        record.get("node_id") for record in records
        if (record.get("preflight_verdict") or {}).get("verdict") == "blocked"
        or (record.get("postflight_verdict") or {}).get("verdict") == "blocked"
    ]
    return {
        "schema": "graphyagent.lineage_dirty_nodes.v1",
        "dirty_node_ids": [str(item) for item in dirty if item],
        "reusable_node_ids": [],
        "record_count": len(records),
    }


def read_lineage_records(workspace: str | Path, graph_run_id: str) -> list[dict[str, Any]]:
    if not graph_run_id:
        return []
    path = _lineage_path(workspace, graph_run_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("execution_lineage", target_type)


def _lineage_path(workspace: str | Path, graph_run_id: str) -> Path:
    return Path(workspace).expanduser().resolve() / "graphs" / str(graph_run_id) / "lineage" / "lineage_records.jsonl"


def _state(state: dict[str, Any] | GraphState | None) -> GraphState:
    if isinstance(state, GraphState):
        return state
    if isinstance(state, dict):
        return GraphState.from_dict(state)
    return GraphState()


def _node_by_id(config: GraphConfig, node_id: str) -> NodeSpec:
    for node in config.nodes:
        if node.node_id == str(node_id):
            return node
    raise ValueError(f"node not found: {node_id}")


def _input_artifacts(input_snapshot: dict[str, Any], state: GraphState) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for input_name, artifact_data in sorted(input_snapshot.items()):
        if not isinstance(artifact_data, dict):
            continue
        artifact_id = str(artifact_data.get("artifact_id") or "")
        artifact = state.artifacts.get(artifact_id)
        items.append(_artifact_lineage_item(
            input_name=str(input_name),
            artifact_id=artifact_id,
            artifact_data=artifact_data,
            state_artifact=artifact.to_dict() if artifact else None,
            state=state,
            status="available" if artifact_id else "missing",
        ))
    return items


def _configured_input_artifacts(node: NodeSpec, state: GraphState) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for input_name, reference in sorted(node.inputs.items()):
        artifact_id = _resolve_input_reference(reference, state)
        if not artifact_id:
            items.append({
                "input_name": str(input_name),
                "artifact_id": None,
                "status": "missing",
            })
            continue
        artifact = state.artifacts.get(artifact_id)
        items.append(_artifact_lineage_item(
            input_name=str(input_name),
            artifact_id=artifact_id,
            artifact_data=artifact.to_dict() if artifact else {},
            state_artifact=artifact.to_dict() if artifact else None,
            state=state,
            status="available" if artifact else "missing",
        ))
    return items


def _resolve_input_reference(reference: Any, state: GraphState) -> str | None:
    if isinstance(reference, dict):
        for key in ("artifact", "alias", "from"):
            if key in reference:
                return _resolve_input_reference(reference[key], state)
        if "path" in reference:
            return None
        return None
    ref = str(reference)
    if ref.startswith("artifact:"):
        ref = ref.split(":", 1)[1]
    elif ref.startswith("alias:"):
        ref = ref.split(":", 1)[1]
    if ref in state.artifacts:
        return ref
    if ref in state.artifact_aliases:
        return state.artifact_aliases[ref]
    if ":" in ref:
        node_id, output_name = ref.split(":", 1)
        result = state.node_results.get(node_id)
        if result and output_name in result.outputs:
            return result.outputs[output_name]
    return None


def _upstream_artifacts(node: NodeSpec, state: GraphState) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for dep in node.depends_on:
        result = state.node_results.get(dep)
        if not result:
            items.append({
                "node_id": dep,
                "output_name": None,
                "status": "missing",
            })
            continue
        for output_name, artifact_id in sorted(result.outputs.items()):
            artifact = state.artifacts.get(artifact_id)
            items.append(_artifact_lineage_item(
                input_name=str(output_name),
                artifact_id=str(artifact_id),
                artifact_data=artifact.to_dict() if artifact else {},
                state_artifact=artifact.to_dict() if artifact else None,
                state=state,
                producer_node_id=dep,
                producer_node_run_id=result.node_run_id,
                status="success" if artifact else "missing",
            ))
    return items


def _artifact_lineage_item(
    *,
    input_name: str,
    artifact_id: str,
    artifact_data: dict[str, Any],
    state_artifact: dict[str, Any] | None,
    state: GraphState,
    producer_node_id: str | None = None,
    producer_node_run_id: str | None = None,
    status: str,
) -> dict[str, Any]:
    if producer_node_id is None:
        producer_node_id, producer_node_run_id = _producer_for_artifact(state, artifact_id)
    source = state_artifact or artifact_data
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return {
        "input_name": input_name,
        "artifact_id": artifact_id,
        "sha256": metadata.get("sha256") or artifact_id,
        "uri": source.get("uri") or source.get("path"),
        "type": source.get("type"),
        "name": source.get("name"),
        "producer_node_id": producer_node_id,
        "producer_node_run_id": producer_node_run_id,
        "status": status,
    }


def _producer_for_artifact(state: GraphState, artifact_id: str) -> tuple[str | None, str | None]:
    for node_id, result in state.node_results.items():
        if artifact_id in result.outputs.values():
            return node_id, result.node_run_id
    return None, None


def _fingerprint_artifacts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "input_name": item.get("input_name"),
            "node_id": item.get("node_id"),
            "output_name": item.get("output_name"),
            "artifact_id": item.get("artifact_id"),
            "sha256": item.get("sha256"),
            "producer_node_id": item.get("producer_node_id"),
            "producer_node_run_id": item.get("producer_node_run_id"),
            "status": item.get("status"),
        }
        for item in items
    ]


def _executor_signature(node: NodeSpec, route_decision: dict[str, Any] | None) -> dict[str, Any]:
    route = route_decision or {}
    return {
        "executor": node.executor,
        "routing": node.routing,
        "model_ref": node.model_ref,
        "provider_id": route.get("provider_id"),
        "model_id": route.get("model_id"),
        "model_ref": route.get("model_ref"),
        "routing_reason": route.get("routing_reason"),
    }


def _output_artifacts(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for output_name, artifact_data in sorted(artifacts.items()):
        if not isinstance(artifact_data, dict):
            continue
        metadata = artifact_data.get("metadata") if isinstance(artifact_data.get("metadata"), dict) else {}
        artifact_id = str(artifact_data.get("artifact_id") or "")
        items.append({
            "output_name": str(output_name),
            "artifact_id": artifact_id,
            "sha256": metadata.get("sha256") or artifact_id,
            "uri": artifact_data.get("uri") or artifact_data.get("path"),
            "type": artifact_data.get("type"),
            "name": artifact_data.get("name"),
            "status": "available" if artifact_id else "missing",
        })
    return items


def _postflight_from_outputs(output_artifacts: list[dict[str, Any]], node_run: dict[str, Any]) -> dict[str, Any]:
    blocked = bool(node_run.get("error"))
    return {
        "schema": "graphyagent.lineage_postflight.v1",
        "node_run_id": node_run.get("node_run_id"),
        "node_id": node_run.get("node_id"),
        "created_at": utc_now(),
        "verdict": "blocked" if blocked else "valid",
        "reason": node_run.get("error") or "outputs verified",
        "output_count": len(output_artifacts),
    }


def _without_packet_hash(packet: dict[str, Any]) -> dict[str, Any]:
    clone = dict(packet)
    clone.pop("packet_hash", None)
    return clone


def _latest_records_by_node(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        node_id = str(record.get("node_id") or "")
        if node_id:
            result[node_id] = record
    return result


def _topological_nodes(config: GraphConfig) -> list[NodeSpec]:
    by_id = {node.node_id: node for node in config.nodes}
    order = {node.node_id: index for index, node in enumerate(config.nodes)}
    children: dict[str, list[str]] = {node.node_id: [] for node in config.nodes}
    indegree: dict[str, int] = {node.node_id: 0 for node in config.nodes}
    for node in config.nodes:
        for dep in node.depends_on:
            if dep not in by_id:
                continue
            children[dep].append(node.node_id)
            indegree[node.node_id] += 1
    ready = [node_id for node_id, value in indegree.items() if value == 0]
    nodes: list[NodeSpec] = []
    while ready:
        ready.sort(key=lambda node_id: order[node_id])
        current = ready
        ready = []
        for node_id in current:
            nodes.append(by_id[node_id])
            for child_id in children[node_id]:
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)
    return nodes or list(config.nodes)


def _infer_graph_run_id_from_checkpoint(checkpoint: dict[str, Any]) -> str:
    manifest = checkpoint.get("manifest") if isinstance(checkpoint.get("manifest"), dict) else {}
    return str(manifest.get("graph_run_id") or "")


__all__ = [
    "RETRIEVAL_POLICY_VERSION",
    "commands",
    "list_dirty_nodes",
    "plan_replay_from_checkpoint",
    "read_lineage_records",
    "record_node_lineage",
    "stable_hash",
    "verify_node_inputs",
]
