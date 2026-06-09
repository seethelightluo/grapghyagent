"""Gate condition checks adapted to GraphyAgent DAG nodes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.types import GraphConfig, GraphState, NodeResult


_OPEN = {"open", "opened", "ready", "pass", "passed", "allow", "allowed", "true", "success"}


def check_gate_conditions(
    node_id: str,
    *,
    graph: GraphConfig | dict[str, Any],
    state: GraphState | dict[str, Any],
) -> tuple[bool, str]:
    """Check whether a node can execute based on upstream gate/results.

    This keeps the intent of ``task.store.check_gate_conditions`` from the
    source project, but maps ``blocked_by`` to GraphyAgent ``depends_on``.
    """
    graph_data = graph.to_dict() if isinstance(graph, GraphConfig) else dict(graph)
    state_data = state.to_dict() if isinstance(state, GraphState) else dict(state)
    node = _find_node(graph_data, node_id)
    blockers = [str(dep) for dep in (node.get("depends_on") or [])]
    if not blockers:
        return True, "No blockers."
    nodes_by_id = {str(item.get("id") or ""): item for item in graph_data.get("nodes") or []}
    node_results = state_data.get("node_results") or {}
    artifacts = state_data.get("artifacts") or {}
    problems: list[str] = []
    for blocker_id in blockers:
        blocker_node = nodes_by_id.get(blocker_id) or {}
        result = node_results.get(blocker_id)
        if not result:
            problems.append(f"{blocker_id}: no node result")
            continue
        if isinstance(result, NodeResult):
            result = result.to_dict()
        if str(result.get("status") or "").lower() != "success":
            problems.append(f"{blocker_id}: status={result.get('status') or 'unknown'}")
            continue
        gate_condition = _gate_condition(blocker_node)
        gate_status = _result_gate_status(result) or _gate_status(blocker_node)
        if gate_condition and gate_status not in _OPEN:
            problems.append(f"{blocker_id}: gate not open ({gate_status or 'pending'})")
            continue
        output_problems = _upstream_output_problems(blocker_id, blocker_node, result, artifacts)
        problems.extend(output_problems)
    if problems:
        return False, "Gate conditions not met: " + "; ".join(problems)
    return True, "All gate conditions satisfied."


def _find_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    for node in graph.get("nodes") or []:
        if str(node.get("id") or node.get("node_id") or "") == str(node_id):
            return node
    raise FileNotFoundError(f"node not found: {node_id}")


def _upstream_output_problems(
    blocker_id: str,
    blocker_node: dict[str, Any],
    result: dict[str, Any],
    artifacts: dict[str, Any],
) -> list[str]:
    outputs = result.get("outputs") or {}
    expected = set(str(name) for name in (blocker_node.get("output_roles") or {}))
    expected.update(_required_outputs(blocker_node))
    if expected and not outputs:
        return [f"{blocker_id}: no outputs for expected {sorted(expected)}"]
    if not expected and not outputs and not _allow_empty_outputs(blocker_node):
        return [f"{blocker_id}: no output artifacts"]
    problems: list[str] = []
    for rel, artifact_id in outputs.items():
        artifact = artifacts.get(str(artifact_id)) or {}
        path = artifact.get("uri") or artifact.get("path")
        if not path:
            problems.append(f"{blocker_id}:{rel}: missing artifact path")
            continue
        source = Path(str(path))
        if not source.is_file():
            problems.append(f"{blocker_id}:{rel}: artifact file missing")
            continue
        try:
            size = source.stat().st_size
        except OSError:
            size = 0
        if size <= 0:
            problems.append(f"{blocker_id}:{rel}: empty artifact")
    return problems


def _required_outputs(node: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for source in (
        node.get("required_outputs"),
        (node.get("metadata") or {}).get("required_outputs"),
        (node.get("gate") or {}).get("required_outputs") if isinstance(node.get("gate"), dict) else None,
    ):
        if isinstance(source, str):
            values.add(source)
        elif isinstance(source, list):
            values.update(str(item) for item in source if str(item))
        elif isinstance(source, dict):
            required = source.get("required")
            if isinstance(required, list):
                values.update(str(item) for item in required if str(item))
            else:
                values.update(str(key) for key in source if key not in {"type", "properties", "description"})
    return values


def _allow_empty_outputs(node: dict[str, Any]) -> bool:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    executor = node.get("executor") if isinstance(node.get("executor"), dict) else {}
    return bool(
        node.get("allow_empty_outputs")
        or metadata.get("allow_empty_outputs")
        or executor.get("allow_empty_outputs")
    )


def _gate_condition(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    gate = node.get("gate") if isinstance(node.get("gate"), dict) else {}
    return str(
        node.get("gate_condition")
        or metadata.get("gate_condition")
        or gate.get("condition")
        or gate.get("gate_condition")
        or ""
    ).strip()


def _gate_status(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    gate = node.get("gate") if isinstance(node.get("gate"), dict) else {}
    return str(
        node.get("gate_status")
        or metadata.get("gate_status")
        or gate.get("status")
        or gate.get("gate_status")
        or ""
    ).strip().lower()


def _result_gate_status(result: dict[str, Any]) -> str:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    return str(summary.get("gate_status") or "").strip().lower()


__all__ = ["check_gate_conditions"]
