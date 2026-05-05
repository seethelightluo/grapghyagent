"""Evidence chain demo: decompose a task into a verifiable task graph.

This script demonstrates the full verifiable graph protocol:
1. Decompose task into nodes with I/O contracts and examples
2. Create tasks with gate conditions and necessity audits
3. Execute nodes with gate control
4. Verify outputs against examples
5. Open/close gates based on verification
6. Compress results into judgment sentences
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cc_config import load_config
from providers import stream, TextChunk
from task.store import (
    create_task, update_task, get_task, list_tasks,
    check_gate_conditions,
)
from task.types import TaskStatus


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"").strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


def _validate_graph(graph: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(graph, dict):
        return ["Graph is not a JSON object."]
    for key in ("nodes", "edges", "inputMapping", "outputMapping"):
        if key not in graph:
            errors.append(f"Missing '{key}' field.")
    nodes = graph.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list.")
        return errors
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("Node entry is not an object.")
            continue
        for k in ("id", "name", "contract"):
            if k not in node:
                errors.append(f"Node missing '{k}'.")
        contract = node.get("contract", {})
        if not isinstance(contract, dict):
            errors.append(f"Node {node.get('id', '?')} contract is not an object.")
            continue
        for ck in ("inputs", "outputs"):
            if ck not in contract:
                errors.append(f"Node {node.get('id', '?')} missing contract.{ck}.")
    return errors


def _build_prompt(task_desc: str) -> str:
    return (
        "You are a task decomposition engine. Return JSON only.\n"
        "Decompose the task into a directed graph with:\n"
        "- Explicit IO contracts (typed inputs/outputs)\n"
        "- IO examples (concrete sample data, not just types)\n"
        "- Necessity claims and counterfactual audits\n"
        "- Verification rules and gate conditions\n"
        "- Evidence pointer plans\n\n"
        "Schema:\n"
        "{\n"
        '  "id": "graph_id",\n'
        '  "nodes": [\n'
        "    {\n"
        '      "id": "node_1",\n'
        '      "name": "Short name",\n'
        '      "strategy": "direct|decompose|hybrid",\n'
        '      "contract": {\n'
        '        "inputs": {"field": {"type": "string", "desc": "..."}},\n'
        '        "outputs": {"field": {"type": "string", "desc": "..."}}\n'
        "      },\n"
        '      "input_example": {"field": "concrete sample value"},\n'
        '      "output_example": {"field": "concrete expected value"},\n'
        '      "necessity_claim": "Why this node is indispensable",\n'
        '      "necessity_audit": "If removed, what specific consequence?",\n'
        '      "verification_rule": "How to verify output (specific checks)",\n'
        '      "gate_condition": "Condition for downstream execution"\n'
        "    }\n"
        "  ],\n"
        '  "edges": [\n'
        "    {\"from\": {\"nodeId\": \"node_1\", \"port\": \"field\"},\n"
        "     \"to\":   {\"nodeId\": \"node_2\", \"port\": \"field\"}}\n"
        "  ],\n"
        '  "inputMapping":  {"task_input": {"nodeId": "node_1", "port": "field"}},\n'
        '  "outputMapping": {"task_output": {"nodeId": "node_n", "port": "field"}}\n'
        "}\n\n"
        f"Task: {task_desc}\n"
    )


def _verify_node(task_id: str) -> dict:
    """Simulate verification for a node. In production, this would run actual checks."""
    task = get_task(task_id)
    if task is None:
        return {"status": "error", "reason": "task not found"}

    # Compare actual_output against output_example
    if not task.actual_output:
        return {"status": "fail", "reason": "no actual_output recorded"}

    if task.output_example:
        # Simple structural check: same keys present
        expected_keys = set(task.output_example.keys())
        actual_keys = set(task.actual_output.keys())
        if not expected_keys.issubset(actual_keys):
            missing = expected_keys - actual_keys
            return {
                "status": "fail",
                "reason": f"missing output keys: {missing}",
                "verification_result": f"key_check=false; missing={list(missing)}",
            }

    return {
        "status": "pass",
        "verification_result": "structure_match=true; keys_present=true",
        "compressed_judgment": f"[VERIFIED]: node #{task_id} output matches contract | confidence: 0.9",
    }


def _execute_node(task_id: str, graph: dict, node: dict, node_outputs: dict) -> dict:
    """Simulate node execution. Produces mock actual_output."""
    # Resolve inputs from predecessors
    contract = node.get("contract", {})
    input_spec = contract.get("inputs", {})
    actual_input = {}

    for field_name in input_spec:
        # Check if this comes from a predecessor via edges
        for edge in graph.get("edges", []):
            to_node = edge.get("to", {})
            to_port = to_node.get("port", "")
            from_node_id = edge.get("from", {}).get("nodeId", "")
            from_port = edge.get("from", {}).get("port", "")
            if to_node.get("nodeId") == node.get("id") and to_port == field_name:
                if from_node_id in node_outputs:
                    actual_input[field_name] = node_outputs[from_node_id].get(from_port, "")
        # Fallback to input_example
        if field_name not in actual_input:
            actual_input[field_name] = node.get("input_example", {}).get(field_name, "")

    # Mock output (in production, this would be real execution)
    output_example = node.get("output_example", {})
    actual_output = {}
    for k, v in output_example.items():
        actual_output[k] = v  # pretend we produced exactly the expected output

    return {"actual_input": actual_input, "actual_output": actual_output}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _load_dotenv(root / ".env")

    task_desc = "Design a small note-taking CLI with add/list/search commands."
    if len(sys.argv) > 1:
        task_desc = " ".join(sys.argv[1:]).strip()

    config = load_config()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if api_key:
        config["anthropic_api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        config["anthropic_base_url"] = base_url

    # Load evidence chain fragment
    fragment_path = root / "prompts" / "fragments" / "evidence_chain.md"
    fragment = fragment_path.read_text(encoding="utf-8") if fragment_path.exists() else ""
    system_prompt = "You are a precise decomposition assistant.\n\n" + fragment

    user_prompt = _build_prompt(task_desc)
    messages = [{"role": "user", "content": user_prompt}]

    print("=" * 60)
    print("PHASE 1: Decomposing task into verifiable graph")
    print("=" * 60)

    text_out = ""
    for event in stream(
        model=config["model"],
        system=system_prompt,
        messages=messages,
        tool_schemas=[],
        config=config,
    ):
        if isinstance(event, TextChunk):
            text_out += event.text

    graph = _extract_json(text_out)
    errors = _validate_graph(graph)
    if errors:
        print("Graph validation failed:")
        for err in errors:
            print(f"  - {err}")
        return 2

    graph_id = graph.get("id", "graph_demo")
    node_to_task: dict[str, str] = {}

    # ── Phase 1: Create tasks with full audit fields ────────────────────────

    print(f"\nGraph ID: {graph_id}")
    print(f"Nodes: {len(graph.get('nodes', []))}")
    print(f"Edges: {len(graph.get('edges', []))}\n")

    for node in graph.get("nodes", []):
        contract = node.get("contract", {})
        input_spec = contract.get("inputs", {})
        output_spec = contract.get("outputs", {})
        input_example = node.get("input_example", {})
        output_example = node.get("output_example", {})

        t = create_task(
            subject=node.get("name", node.get("id", "")),
            description=f"graph:{graph_id} node:{node.get('id', '')}",
            input_spec=input_spec,
            output_spec=output_spec,
            input_example=input_example,
            output_example=output_example,
            necessity_claim=node.get("necessity_claim", ""),
            necessity_audit=node.get("necessity_audit", ""),
            verification_rule=node.get("verification_rule", ""),
            gate_condition=node.get("gate_condition", ""),
            acceptance_status="unchecked",
            compressed_judgment="pending_verification",
            audit_status="io_ready" if input_spec and output_spec else "missing_io",
            evidence_pointers=[],
            metadata={"graph_id": graph_id, "node_id": node.get("id", "")},
        )
        node_to_task[node.get("id", "")] = t.id
        print(f"  Created task #{t.id}: {t.subject}")
        if t.necessity_claim:
            print(f"    Necessity: {t.necessity_claim[:80]}")
        if t.gate_condition:
            print(f"    Gate: {t.gate_condition}")

    # ── Phase 1b: Wire edges ────────────────────────────────────────────────

    print("\nWiring edges:")
    for edge in graph.get("edges", []):
        src = edge.get("from", {}).get("nodeId")
        dst = edge.get("to", {}).get("nodeId")
        if not src or not dst:
            continue
        src_id = node_to_task.get(src)
        dst_id = node_to_task.get(dst)
        if src_id and dst_id:
            update_task(dst_id, add_blocked_by=[src_id])
            print(f"  {src} -> {dst}")

    # ── Phase 2: Execute with gate control ──────────────────────────────────

    print("\n" + "=" * 60)
    print("PHASE 2: Executing with gate control")
    print("=" * 60)

    from collections import deque

    # Topological execution
    nodes = graph.get("nodes", [])
    node_map = {n.get("id"): n for n in nodes}
    executed = set()
    node_outputs: dict[str, dict] = {}

    # Simple topological sort
    max_iterations = len(nodes) * 2
    iteration = 0

    while len(executed) < len(nodes) and iteration < max_iterations:
        iteration += 1
        for node in nodes:
            nid = node.get("id")
            if nid in executed:
                continue

            task_id = node_to_task.get(nid)
            if not task_id:
                continue

            # Check gate conditions
            can_execute, reason = check_gate_conditions(task_id)
            if not can_execute:
                print(f"\n  [{nid}] BLOCKED: {reason}")
                continue

            print(f"\n  [{nid}] Executing: {node.get('name', nid)}")

            # Execute
            update_task(task_id, status="in_progress")
            result = _execute_node(task_id, graph, node, node_outputs)

            # Record actuals
            update_task(
                task_id,
                actual_input=result["actual_input"],
                actual_output=result["actual_output"],
                add_run_log={
                    "timestamp": datetime.now().isoformat(),
                    "step": "execute",
                    "detail": f"produced {list(result['actual_output'].keys())}",
                },
            )
            print(f"    Actual input:  {json.dumps(result['actual_input'], ensure_ascii=False)[:100]}")
            print(f"    Actual output: {json.dumps(result['actual_output'], ensure_ascii=False)[:100]}")

            # ── Phase 3: Verify ─────────────────────────────────────────────

            verification = _verify_node(task_id)
            gate_status = "open" if verification["status"] == "pass" else "closed"

            update_task(
                task_id,
                status="completed" if verification["status"] == "pass" else "cancelled",
                acceptance_status=verification["status"],
                verification_result=verification.get("verification_result", ""),
                gate_status=gate_status,
                compressed_judgment=verification.get("compressed_judgment", f"[{verification['status'].upper()}]: node #{task_id}"),
                add_audit_log={
                    "timestamp": datetime.now().isoformat(),
                    "action": "verify",
                    "result": verification["status"],
                    "detail": verification.get("verification_result", verification.get("reason", "")),
                },
            )

            print(f"    Verification: {verification['status']}")
            if "verification_result" in verification:
                print(f"    Result: {verification['verification_result']}")
            print(f"    Gate: {gate_status}")

            node_outputs[nid] = result["actual_output"]
            executed.add(nid)

    # ── Final report ────────────────────────────────────────────────────────

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)

    all_tasks = list_tasks()
    for t in all_tasks:
        print(f"\n  #{t.id} [{t.status.value}] {t.subject}")
        if t.input_example:
            print(f"    In Example:  {t.input_example}")
        if t.actual_input:
            print(f"    Actual In:   {t.actual_input}")
        if t.output_example:
            print(f"    Out Example: {t.output_example}")
        if t.actual_output:
            print(f"    Actual Out:  {t.actual_output}")
        if t.verification_result:
            print(f"    Verify Res:  {t.verification_result}")
        if t.gate_condition:
            print(f"    Gate Cond:   {t.gate_condition}")
            print(f"    Gate Status: {t.gate_status}")
        if t.compressed_judgment:
            print(f"    Judgment:    {t.compressed_judgment}")
        if t.necessity_audit:
            print(f"    Necessity:   {t.necessity_audit}")
        if t.audit_log:
            print(f"    Audit Log:   {len(t.audit_log)} entries")
        if t.run_log:
            print(f"    Run Log:     {len(t.run_log)} entries")

    # ── Phase 4: Memory compression ─────────────────────────────────────────

    print("\n" + "=" * 60)
    print("PHASE 4: Judgment sentences (memory-ready)")
    print("=" * 60)

    for t in all_tasks:
        if t.compressed_judgment and t.compressed_judgment != "pending_verification":
            pointer = t.evidence_pointers[0] if t.evidence_pointers else f"tasks.json#{t.id}"
            print(f"  {t.compressed_judgment} | evidence: {pointer}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
