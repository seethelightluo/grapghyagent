"""Node contract and gate validation helpers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..core.types import GraphConfig, GraphState, NodeSpec, utc_now


_OPEN_GATE_STATUSES = {"open", "opened", "ready", "pass", "passed", "allow", "allowed", "true"}
_CLOSED_GATE_STATUSES = {
    "closed",
    "blocked",
    "block",
    "failed",
    "fail",
    "deny",
    "denied",
    "false",
}


def validate_node_contract(
    graph: GraphConfig | dict[str, Any],
    node_id: str,
    *,
    state: GraphState | dict[str, Any] | None = None,
    phase: str = "static",
) -> dict[str, Any]:
    """Validate the declared node interface, required inputs, and gate status.

    The validator is intentionally deterministic and conservative. It blocks
    only explicit contract failures, while expression-style gate conditions are
    reported as warnings until a later verifier can evaluate them.
    """
    graph_data = _graph_to_dict(graph)
    nodes = graph_data.get("nodes") or []
    node = _find_node(nodes, node_id)
    resolved_node_id = str(node.get("id") or node_id)
    node_state = _state_to_dict(state)
    issues: list[dict[str, Any]] = []

    required_inputs = sorted(_required_input_names(node))
    declared_inputs = set(_declared_input_names(node))
    for name in required_inputs:
        if name not in declared_inputs:
            issues.append(_issue(
                "missing_required_input_binding",
                "error",
                f"required input `{name}` is not bound in node.inputs",
                field=f"inputs.{name}",
            ))

    issues.extend(_validate_input_references(graph_data, node, node_state))
    issues.extend(_validate_gate(node))
    issues.extend(_validate_output_contract(node))

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    decision = "blocked" if error_count else "warning" if warning_count else "ready"
    contract = {
        "schema": "graphyagent.node_contract.v1",
        "created_at": utc_now(),
        "phase": phase,
        "graph_id": graph_data.get("graph_id"),
        "node_id": resolved_node_id,
        "decision": decision,
        "runtime_blocking": decision == "blocked",
        "summary": {
            "error_count": error_count,
            "warning_count": warning_count,
            "required_inputs": required_inputs,
            "declared_inputs": sorted(declared_inputs),
            "expected_outputs": sorted(_expected_output_names(node)),
            "gate_status": _gate_status(node),
            "gate_condition": _gate_condition(node),
        },
        "issues": issues,
    }
    return contract


def validate_node_outputs(
    node: NodeSpec | dict[str, Any],
    output_names: list[str] | set[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Validate explicit required output file names after node execution."""
    node_data = _node_to_dict(node)
    required_outputs = sorted(_explicit_required_output_names(node_data))
    actual_outputs = {str(name) for name in output_names}
    issues: list[dict[str, Any]] = []
    for name in required_outputs:
        if name not in actual_outputs:
            issues.append(_issue(
                "missing_required_output",
                "error",
                f"required output `{name}` was not produced",
                field=f"outputs.{name}",
            ))
    decision = "blocked" if issues else "ready"
    return {
        "schema": "graphyagent.node_output_contract.v1",
        "created_at": utc_now(),
        "node_id": str(node_data.get("id") or node_data.get("node_id") or ""),
        "decision": decision,
        "runtime_blocking": decision == "blocked",
        "summary": {
            "required_outputs": required_outputs,
            "actual_outputs": sorted(actual_outputs),
        },
        "issues": issues,
    }


def format_contract_failure(contract: dict[str, Any]) -> str:
    issues = contract.get("issues") or []
    details = "; ".join(
        str(issue.get("message") or issue.get("type"))
        for issue in issues
        if issue.get("severity") == "error"
    )
    node_id = contract.get("node_id") or "unknown"
    if details:
        return f"node contract blocked `{node_id}`: {details}"
    return f"node contract blocked `{node_id}`"


def contract_audit_memory_text(contract: dict[str, Any]) -> str:
    issues = contract.get("issues") or []
    issue_lines = [
        f"- {issue.get('severity')} {issue.get('type')}: {issue.get('message')}"
        for issue in issues
    ]
    if not issue_lines:
        issue_lines = ["- 无阻塞或告警。"]
    return (
        "节点 contract/gate 校验完成。\n"
        f"- 结论：{contract.get('decision')}\n"
        f"- required_inputs：{', '.join(contract.get('summary', {}).get('required_inputs') or []) or '无'}\n"
        f"- gate_status：{contract.get('summary', {}).get('gate_status') or '未声明'}\n"
        + "\n".join(issue_lines)
    )


def _graph_to_dict(graph: GraphConfig | dict[str, Any]) -> dict[str, Any]:
    if isinstance(graph, GraphConfig):
        return graph.to_dict()
    return deepcopy(graph)


def _node_to_dict(node: NodeSpec | dict[str, Any]) -> dict[str, Any]:
    if isinstance(node, NodeSpec):
        return node.to_dict()
    return deepcopy(node)


def _state_to_dict(state: GraphState | dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    if isinstance(state, GraphState):
        return state.to_dict()
    return deepcopy(state)


def _find_node(nodes: list[Any], node_id: str) -> dict[str, Any]:
    for node in nodes:
        if str((node or {}).get("id") or (node or {}).get("node_id") or "") == str(node_id):
            return deepcopy(node)
    raise FileNotFoundError(f"node not found: {node_id}")


def _metadata(node: dict[str, Any]) -> dict[str, Any]:
    metadata = node.get("metadata") or {}
    return metadata if isinstance(metadata, dict) else {}


def _interface(node: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(node)
    interface = node.get("interface") or metadata.get("interface") or {}
    return interface if isinstance(interface, dict) else {}


def _gate(node: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(node)
    gate = node.get("gate") or metadata.get("gate") or {}
    if isinstance(gate, dict):
        return gate
    if gate:
        return {"status": str(gate)}
    return {}


def _gate_status(node: dict[str, Any]) -> str | None:
    metadata = _metadata(node)
    gate = _gate(node)
    raw = (
        node.get("gate_status")
        or metadata.get("gate_status")
        or gate.get("status")
        or gate.get("gate_status")
    )
    return str(raw).strip().lower() if raw is not None and str(raw).strip() else None


def _gate_condition(node: dict[str, Any]) -> str | None:
    metadata = _metadata(node)
    gate = _gate(node)
    raw = (
        node.get("gate_condition")
        or metadata.get("gate_condition")
        or gate.get("condition")
        or gate.get("gate_condition")
    )
    return str(raw).strip() if raw is not None and str(raw).strip() else None


def _required_input_names(node: dict[str, Any]) -> set[str]:
    metadata = _metadata(node)
    interface = _interface(node)
    gate = _gate(node)
    names: set[str] = set()
    for source in (
        node.get("required_inputs"),
        metadata.get("required_inputs"),
        gate.get("required_inputs"),
        node.get("input_spec"),
        metadata.get("input_spec"),
        interface.get("required_inputs"),
        interface.get("inputs"),
        interface.get("input_spec"),
    ):
        names.update(_names_from_contract_source(source, required_only=True))
    return names


def _expected_output_names(node: dict[str, Any]) -> set[str]:
    metadata = _metadata(node)
    interface = _interface(node)
    names: set[str] = set()
    for source in (
        node.get("required_outputs"),
        metadata.get("required_outputs"),
        node.get("output_spec"),
        metadata.get("output_spec"),
        interface.get("required_outputs"),
        interface.get("outputs"),
        interface.get("output_spec"),
    ):
        names.update(_names_from_contract_source(source, required_only=False))
    return names


def _explicit_required_output_names(node: dict[str, Any]) -> set[str]:
    metadata = _metadata(node)
    interface = _interface(node)
    gate = _gate(node)
    names: set[str] = set()
    for source in (
        node.get("required_outputs"),
        metadata.get("required_outputs"),
        gate.get("required_outputs"),
        interface.get("required_outputs"),
    ):
        names.update(_names_from_contract_source(source, required_only=True))
    return names


def _declared_input_names(node: dict[str, Any]) -> set[str]:
    inputs = node.get("inputs") or {}
    return {str(name) for name in inputs if str(name)}


def _names_from_contract_source(source: Any, *, required_only: bool) -> set[str]:
    names: set[str] = set()
    if not source:
        return names
    if isinstance(source, str):
        names.add(source)
        return names
    if isinstance(source, list):
        for item in source:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                raw = item.get("name") or item.get("key") or item.get("id") or item.get("field")
                if raw and (not required_only or item.get("required", True)):
                    names.add(str(raw))
        return names
    if isinstance(source, dict):
        required = source.get("required")
        properties = source.get("properties")
        if isinstance(required, list):
            names.update(str(item) for item in required if str(item))
            return names
        if isinstance(properties, dict) and source.get("type") == "object":
            for key, value in properties.items():
                if not required_only or not isinstance(value, dict) or value.get("required", True):
                    names.add(str(key))
            return names
        for key, value in source.items():
            if key in {"type", "title", "description", "additionalProperties", "$schema"}:
                continue
            if not required_only or not isinstance(value, dict) or value.get("required", True):
                names.add(str(key))
    return names


def _validate_input_references(
    graph: dict[str, Any],
    node: dict[str, Any],
    state: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    node_ids = {str(item.get("id") or "") for item in graph.get("nodes") or []}
    initial_artifacts = set((graph.get("initial_artifacts") or {}).keys())
    state_aliases = set((state or {}).get("artifact_aliases") or {})
    state_artifacts = set((state or {}).get("artifacts") or {})
    node_results = (state or {}).get("node_results") or {}
    depends_on = {str(dep) for dep in (node.get("depends_on") or [])}
    for input_name, reference in (node.get("inputs") or {}).items():
        if isinstance(reference, dict) and reference.get("path"):
            continue
        ref = _reference_string(reference)
        if not ref:
            continue
        if ":" in ref and not ref.startswith(("artifact:", "alias:")):
            source_node, output_name = ref.split(":", 1)
            if source_node not in node_ids:
                issues.append(_issue(
                    "missing_input_source_node",
                    "error",
                    f"input `{input_name}` references missing node `{source_node}`",
                    field=f"inputs.{input_name}",
                ))
            elif source_node not in depends_on:
                issues.append(_issue(
                    "input_reference_without_dependency",
                    "warning",
                    f"input `{input_name}` references `{source_node}:{output_name}` but depends_on does not include `{source_node}`",
                    field=f"inputs.{input_name}",
                ))
            if state is not None:
                result = node_results.get(source_node)
                if not result:
                    issues.append(_issue(
                        "input_source_not_ready",
                        "error",
                        f"input `{input_name}` references `{source_node}:{output_name}` before that node has a result",
                        field=f"inputs.{input_name}",
                    ))
                elif output_name not in (result.get("outputs") or {}):
                    issues.append(_issue(
                        "missing_input_source_output",
                        "error",
                        f"input `{input_name}` references missing output `{source_node}:{output_name}`",
                        field=f"inputs.{input_name}",
                    ))
            continue
        alias = ref.split(":", 1)[1] if ref.startswith(("artifact:", "alias:")) else ref
        if state is not None and alias not in state_aliases and alias not in state_artifacts:
            issues.append(_issue(
                "unresolved_input_artifact",
                "error",
                f"input `{input_name}` references unresolved artifact or alias `{alias}`",
                field=f"inputs.{input_name}",
            ))
        elif state is None and alias not in initial_artifacts:
            issues.append(_issue(
                "input_artifact_not_declared",
                "warning",
                f"input `{input_name}` references `{alias}`, which is not declared in initial_artifacts",
                field=f"inputs.{input_name}",
            ))
    return issues


def _validate_gate(node: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    status = _gate_status(node)
    condition = _gate_condition(node)
    gate = _gate(node)
    reason = str(gate.get("reason") or gate.get("message") or "").strip()
    if status in _CLOSED_GATE_STATUSES:
        suffix = f": {reason}" if reason else ""
        issues.append(_issue(
            "gate_blocked",
            "error",
            f"gate is {status}{suffix}",
            field="gate.status",
        ))
    elif status and status not in _OPEN_GATE_STATUSES:
        issues.append(_issue(
            "unknown_gate_status",
            "warning",
            f"gate status `{status}` is not a recognized open/blocked state",
            field="gate.status",
        ))
    if condition and not status:
        issues.append(_issue(
            "gate_condition_unverified",
            "warning",
            "gate_condition is declared but no gate_status/gate.status records whether it is open",
            field="gate_condition",
        ))
    return issues


def _validate_output_contract(node: dict[str, Any]) -> list[dict[str, Any]]:
    expected = _expected_output_names(node)
    if not expected:
        return []
    executor = node.get("executor") if isinstance(node.get("executor"), dict) else {}
    declared_outputs = set(str(name) for name in (node.get("output_roles") or {}))
    declared_outputs.update(str(name) for name in (executor.get("write_outputs") or {}))
    if executor.get("output"):
        declared_outputs.add(str(executor["output"]))
    missing = sorted(name for name in expected if name not in declared_outputs)
    if not missing:
        return []
    return [
        _issue(
            "output_contract_not_bound",
            "warning",
            f"output contract names are not explicitly bound to output_roles/write_outputs: {', '.join(missing)}",
            field="output_spec",
        )
    ]


def _reference_string(reference: Any) -> str | None:
    if isinstance(reference, dict):
        for key in ("artifact", "alias", "from", "path"):
            if reference.get(key):
                return str(reference[key])
        return None
    if reference is None:
        return None
    return str(reference)


def _issue(
    issue_type: str,
    severity: str,
    message: str,
    *,
    field: str | None = None,
) -> dict[str, Any]:
    issue = {
        "type": issue_type,
        "severity": severity,
        "message": message,
    }
    if field:
        issue["field"] = field
    return issue


__all__ = [
    "contract_audit_memory_text",
    "format_contract_failure",
    "validate_node_contract",
    "validate_node_outputs",
]
