"""Run the city-famous-things task through the verifiable graph protocol.

This script directly orchestrates the framework's task system and recovery engine:
1. Graph decomposition (LLM)
2. Per-node execution with TaskExecuteRecovery (attempt → retry → decompose)
3. Gate-controlled execution
4. Full audit trail in modules/ format

Usage:
    python scripts/run_verifiable_graph.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cc_config import load_config
from providers import stream, TextChunk
from task.store import create_task, get_task, update_task, clear_all_tasks, check_gate_conditions
from task.recovery import (
    execute_with_recovery, retry_task, decompose_task,
    verify_output, merge_sub_outputs, call_llm, extract_json,
)

OUTPUT_DIR = ROOT.parent / "example" / "example1"
LOG_DIR = OUTPUT_DIR / "log"


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


def _write_log(log_dir: Path, name: str, system_prompt: str, user_prompt: str,
               response: str, meta: dict) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{name}.md"
    lines = [
        f"# Log: {name}", "",
        f"## Metadata", "```json",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "```", "",
        f"## System Prompt ({len(system_prompt)} chars)", "```",
        system_prompt, "```", "",
        f"## User Prompt ({len(user_prompt)} chars)", "```",
        user_prompt, "```", "",
        f"## Response ({len(response)} chars)", "```",
        response, "```",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _log_cb(name: str, system_prompt: str, user_prompt: str, response: str, meta: dict) -> None:
    _write_log(LOG_DIR, name, system_prompt, user_prompt, response, meta)


# ── Custom verifier for this task ─────────────────────────────────────────────

def _city_task_verifier(output: dict, spec: dict, example: dict, rule: str) -> list[str]:
    """Custom verification for city-famous-things task nodes."""
    issues = []

    # Check city list
    city_list = output.get("cities") or output.get("city_list")
    if city_list is not None:
        if not isinstance(city_list, list):
            issues.append(f"city list should be list, got {type(city_list).__name__}")
        elif len(city_list) != 10:
            issues.append(f"Expected 10 cities, got {len(city_list)}")

    # Check famous_things
    if "famous_things" in output:
        things = output["famous_things"]
        if not isinstance(things, list):
            issues.append(f"famous_things should be list, got {type(things).__name__}")
        else:
            if things and isinstance(things[0], dict) and "items" in things[0]:
                total = sum(len(c.get("items", [])) for c in things)
                city_count = len(things)
            elif things and isinstance(things[0], dict) and "thing" in things[0]:
                total = len(things)
                city_count = len(set(t.get("city", "") for t in things))
            else:
                total = len(things)
                city_count = 0
            if total != 100:
                issues.append(f"Expected 100 items total, got {total}")
            if city_count not in (0, 10):
                issues.append(f"Expected 10 cities worth of items, got {city_count}")

    # Check ranked_items
    if "ranked_items" in output:
        ranked = output["ranked_items"]
        if not isinstance(ranked, list):
            issues.append(f"ranked_items should be list, got {type(ranked).__name__}")
        elif len(ranked) != 100:
            issues.append(f"Expected 100 ranked items, got {len(ranked)}")
        else:
            scores = [r.get("importance_score", r.get("score", 0)) for r in ranked if isinstance(r, dict)]
            if len(scores) != len(set(scores)):
                dupes = [s for s in set(scores) if scores.count(s) > 1]
                issues.append(f"Duplicate scores: {dupes[:5]}")
            if not all(scores[i] >= scores[i+1] for i in range(len(scores)-1)):
                issues.append("Not sorted by score descending")

    # Check tree_text
    if "tree_text" in output:
        tree = output["tree_text"]
        if not isinstance(tree, str):
            issues.append(f"tree_text should be string, got {type(tree).__name__}")
        elif len(tree) < 100:
            issues.append(f"tree_text suspiciously short ({len(tree)} chars)")

    # Check txt_content
    if "txt_content" in output:
        txt = output["txt_content"]
        if not isinstance(txt, str):
            issues.append(f"txt_content should be string, got {type(txt).__name__}")
        elif len(txt) < 200:
            issues.append(f"txt_content suspiciously short ({len(txt)} chars)")

    return issues


# ── Graph decomposition prompt ───────────────────────────────────────────────

def _build_graph_prompt(task_desc: str) -> str:
    return (
        "You are a task decomposition engine. Return a JSON object only — no markdown, no explanation.\n\n"
        "Decompose the following task into a directed graph. Each node must have:\n"
        "- id, name, strategy (direct/decompose/hybrid)\n"
        "- contract with typed inputs and outputs\n"
        "- input_example: concrete sample input data\n"
        "- output_example: concrete expected output data\n"
        "- necessity_claim: why this node is indispensable\n"
        "- necessity_audit: what happens if this node is removed\n"
        "- verification_rule: how to verify the output\n"
        "- gate_condition: condition for downstream execution\n\n"
        "The graph must:\n"
        "1. Cover the full task: collect 10 famous things for each of the top 10 cities (100 items total)\n"
        "2. Visualize as a tree structure\n"
        "3. Rank all 100 items by importance\n"
        "4. Generate a TXT file with the ranking\n"
        "5. Include validation nodes that gate downstream execution\n\n"
        "Schema:\n"
        "{\n"
        '  "id": "graph_id",\n'
        '  "nodes": [\n'
        "    {\n"
        '      "id": "node_1",\n'
        '      "name": "Short name",\n'
        '      "strategy": "direct",\n'
        '      "contract": {\n'
        '        "inputs": {"field": {"type": "string", "desc": "..."}},\n'
        '        "outputs": {"field": {"type": "string", "desc": "..."}}\n'
        "      },\n"
        '      "input_example": {"field": "concrete sample"},\n'
        '      "output_example": {"field": "concrete expected"},\n'
        '      "necessity_claim": "...",\n'
        '      "necessity_audit": "if removed: ...",\n'
        '      "verification_rule": "...",\n'
        '      "gate_condition": "..."\n'
        "    }\n"
        "  ],\n"
        '  "edges": [\n'
        '    {"from": {"nodeId": "node_1", "port": "field"}, "to": {"nodeId": "node_2", "port": "field"}}\n'
        "  ],\n"
        '  "inputMapping": {"task_input": {"nodeId": "node_1", "port": "field"}},\n'
        '  "outputMapping": {"task_output": {"nodeId": "node_N", "port": "field"}}\n'
        "}\n\n"
        f"Task: {task_desc}\n"
    )


# ── Input resolution ─────────────────────────────────────────────────────────

def _resolve_inputs(node: dict, graph: dict, node_outputs: dict) -> dict:
    contract = node.get("contract", {})
    input_spec = contract.get("inputs", {})
    edges = graph.get("edges", [])
    node_id = node.get("id", "")

    actual_inputs = {}
    for field_name in input_spec:
        for edge in edges:
            to = edge.get("to", {})
            if to.get("nodeId") == node_id and to.get("port") == field_name:
                from_id = edge.get("from", {}).get("nodeId", "")
                from_port = edge.get("from", {}).get("port", "")
                if from_id in node_outputs:
                    val = node_outputs[from_id]
                    if isinstance(val, dict) and from_port in val:
                        actual_inputs[field_name] = val[from_port]
                    else:
                        actual_inputs[field_name] = val

    if not actual_inputs:
        for mapping_port, mapping in graph.get("inputMapping", {}).items():
            if mapping.get("nodeId") == node_id:
                port = mapping.get("port", "")
                if port in input_spec:
                    actual_inputs[port] = f"<task_input:{mapping_port}>"

    return actual_inputs


# ── Topological sort ─────────────────────────────────────────────────────────

def _topological_order(graph: dict) -> list[str]:
    nodes = {n.get("id"): n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])
    in_degree = {nid: 0 for nid in nodes}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in edges:
        src = e.get("from", {}).get("nodeId", "")
        dst = e.get("to", {}).get("nodeId", "")
        if src in in_degree and dst in in_degree:
            in_degree[dst] += 1
            adj.setdefault(src, []).append(dst)

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in adj.get(nid, []):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)
    return order


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    task_desc = (
        "搜寻世界上前10城市的10个出名的事物共100个，用树结构可视化展现出来，"
        "同时对这100个的重要性排序，排序结果生成txt文件"
    )

    # Setup
    _load_dotenv(ROOT / ".env")
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

    # Clean previous state
    clear_all_tasks()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    run_log: list[dict] = []
    def log_event(step: str, detail: str = ""):
        entry = {"timestamp": datetime.now().isoformat(), "step": step, "detail": detail}
        run_log.append(entry)
        print(f"  [{entry['timestamp'][:19]}] {step}: {detail[:120]}")

    log_event("start", f"task={task_desc[:80]}")

    # Load evidence chain fragment
    fragment_path = ROOT / "prompts" / "fragments" / "evidence_chain.md"
    fragment = fragment_path.read_text(encoding="utf-8") if fragment_path.exists() else ""
    system_prompt = (
        "You are a precise task decomposition and execution assistant.\n\n"
        + fragment
    )

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 1: GRAPH DECOMPOSITION
    # ══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("PHASE 1: GRAPH DECOMPOSITION")
    print("=" * 70)

    graph_prompt = _build_graph_prompt(task_desc)
    graph_response, graph_meta = call_llm(system_prompt, graph_prompt, config)
    _write_log(LOG_DIR, "01_graph_decomposition", system_prompt, graph_prompt, graph_response, graph_meta)
    log_event("graph_decomposition", f"len={len(graph_response)}, dur={graph_meta['duration_s']}s")

    try:
        graph = extract_json(graph_response)
    except Exception as e:
        log_event("graph_parse_error", str(e))
        print(f"\nFATAL: Could not parse graph JSON. See log/01_graph_decomposition.md")
        return 2

    required_keys = {"nodes", "edges", "inputMapping", "outputMapping"}
    missing = required_keys - set(graph.keys())
    if missing:
        log_event("graph_validation_error", f"missing keys: {missing}")
        print(f"\nFATAL: Graph missing keys: {missing}")
        return 2

    nodes_by_id = {n.get("id"): n for n in graph.get("nodes", [])}
    log_event("graph_valid", f"nodes={len(nodes_by_id)}, edges={len(graph.get('edges', []))}")

    print(f"\n  Nodes: {len(nodes_by_id)}")
    for nid, node in nodes_by_id.items():
        print(f"    {nid}: {node.get('name', '')}")
        print(f"      necessity: {node.get('necessity_claim', '')[:80]}")
        print(f"      gate: {node.get('gate_condition', '')[:80]}")

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 2: CREATE TASKS IN STORE
    # ══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("PHASE 2: CREATE TASKS")
    print("=" * 70)

    graph_id = graph.get("id", "city_famous_tree")
    node_to_task: dict[str, str] = {}

    for node in graph.get("nodes", []):
        contract = node.get("contract", {})
        t = create_task(
            subject=node.get("name", node.get("id", "")),
            description=f"graph:{graph_id} node:{node.get('id', '')}",
            input_spec=contract.get("inputs", {}),
            output_spec=contract.get("outputs", {}),
            input_example=node.get("input_example", {}),
            output_example=node.get("output_example", {}),
            necessity_claim=node.get("necessity_claim", ""),
            necessity_audit=node.get("necessity_audit", ""),
            verification_rule=node.get("verification_rule", ""),
            gate_condition=node.get("gate_condition", ""),
            acceptance_status="unchecked",
            compressed_judgment="pending_verification",
            audit_status="io_ready" if contract.get("inputs") and contract.get("outputs") else "missing_io",
            evidence_pointers=[],
            metadata={"graph_id": graph_id, "node_id": node.get("id", "")},
        )
        node_to_task[node.get("id", "")] = t.id
        print(f"  Task #{t.id}: {t.subject}")

    # Wire edges
    print("\n  Wiring edges:")
    for edge in graph.get("edges", []):
        src = edge.get("from", {}).get("nodeId")
        dst = edge.get("to", {}).get("nodeId")
        if src and dst:
            src_id = node_to_task.get(src)
            dst_id = node_to_task.get(dst)
            if src_id and dst_id:
                update_task(dst_id, add_blocked_by=[src_id])
                print(f"    {src} -> {dst}")

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 3: EXECUTE WITH RECOVERY (attempt → retry → decompose)
    # ══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("PHASE 3: EXECUTE WITH RECOVERY")
    print("=" * 70)

    exec_order = _topological_order(graph)
    node_outputs: dict[str, dict] = {}
    node_verifications: dict[str, dict] = {}
    gate_status: dict[str, bool] = {}
    recovery_paths: dict[str, str] = {}
    node_actual_io: dict[str, dict] = {}

    for nid in exec_order:
        node = nodes_by_id.get(nid)
        if not node:
            continue

        print(f"\n  --- {nid}: {node.get('name', '')} ---")

        # Check gate conditions
        task_id = node_to_task.get(nid)
        if task_id:
            can_exec, reason = check_gate_conditions(task_id)
            if not can_exec:
                print(f"    GATE BLOCKED: {reason}")
                log_event(f"{nid}_gate_blocked", reason)
                node_actual_io[nid] = {"inputs": {}, "outputs": {}, "status": "blocked"}
                gate_status[nid] = False
                recovery_paths[nid] = "blocked"
                continue

        # Resolve inputs
        actual_inputs = _resolve_inputs(node, graph, node_outputs)
        print(f"    Input keys: {list(actual_inputs.keys())}")

        # Execute with full recovery pipeline
        result = execute_with_recovery(
            task_id=task_id,
            actual_inputs=actual_inputs,
            system_prompt=system_prompt,
            config=config,
            depth=0,
            max_depth=2,
            custom_verifier=_city_task_verifier,
            log_callback=_log_cb,
        )

        if "error" in result:
            print(f"    ERROR: {result['error']}")
            recovery_paths[nid] = "error"
            gate_status[nid] = False
            continue

        actual_output = result["output"]
        verification = result["verification"]
        recovery = result["recovery"]

        recovery_paths[nid] = recovery
        node_outputs[nid] = actual_output
        node_verifications[nid] = verification
        gate_status[nid] = verification["passed"]

        status_label = "PASS" if verification["passed"] else "FAIL"
        print(f"    Output keys: {list(actual_output.keys()) if isinstance(actual_output, dict) else '?'}")
        print(f"    Verification: {status_label} (via {recovery})")
        if verification["issues"]:
            for issue in verification["issues"]:
                print(f"      - {issue}")

        node_actual_io[nid] = {
            "inputs": actual_inputs,
            "outputs": actual_output,
            "status": "pass" if verification["passed"] else "fail",
            "verification": verification,
            "recovery_path": recovery,
        }

        log_event(f"{nid}_verified",
                  f"passed={verification['passed']}, recovery={recovery}, issues={len(verification['issues'])}")

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 4: PER-MODULE MEMORY FILES
    # ══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("PHASE 4: PER-MODULE MEMORY FILES")
    print("=" * 70)

    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        node = nodes_by_id[nid]
        mod_dir = OUTPUT_DIR / "modules" / nid
        mod_dir.mkdir(parents=True, exist_ok=True)

        aio = node_actual_io.get(nid, {})
        v = node_verifications.get(nid, {})

        mem_content = "\n".join([
            f"# Module: {nid} — {node.get('name', '')}",
            f"",
            f"## Necessity",
            f"- claim: {node.get('necessity_claim', '')}",
            f"- audit: {node.get('necessity_audit', '')}",
            f"",
            f"## Planned I/O",
            f"- input_example: {json.dumps(node.get('input_example'), ensure_ascii=False)}",
            f"- output_example: {json.dumps(node.get('output_example'), ensure_ascii=False)}",
            f"",
            f"## Actual I/O",
            f"- actual_input: {json.dumps(aio.get('inputs'), ensure_ascii=False, indent=2)}",
            f"- actual_output: {json.dumps(aio.get('outputs'), ensure_ascii=False, indent=2)[:3000]}",
            f"",
            f"## Verification",
            f"- status: {aio.get('status', 'unknown')}",
            f"- recovery_path: {aio.get('recovery_path', 'unknown')}",
            f"- rule: {node.get('verification_rule', '')}",
            f"- result: {json.dumps(v, ensure_ascii=False)}",
            f"",
            f"## Gate",
            f"- condition: {node.get('gate_condition', '')}",
            f"- status: {'open' if gate_status.get(nid) else 'closed'}",
            f"",
        ])
        (mod_dir / "memory.md").write_text(mem_content, encoding="utf-8")
        print(f"  {nid}/memory.md")

    log_event("module_memories", f"count={len(exec_order)}")

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 5: WRITE RESULT.TXT
    # ══════════════════════════════════════════════════════════════════════

    print("\n" + "=" * 70)
    print("PHASE 5: WRITE RESULT.TXT")
    print("=" * 70)

    lines = []
    lines.append("=" * 70)
    lines.append("VERIFIABLE GRAPH EXECUTION — RESULT")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Task: {task_desc}")
    lines.append(f"Model: {config.get('model', '')}")
    lines.append(f"Timestamp: {datetime.now().isoformat()}")
    lines.append("")

    # Graph structure
    lines.append("-" * 70)
    lines.append("1. GRAPH STRUCTURE")
    lines.append("-" * 70)
    lines.append("")
    lines.append(f"Nodes: {len(nodes_by_id)}, Edges: {len(graph.get('edges', []))}")
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        node = nodes_by_id[nid]
        contract = node.get("contract", {})
        lines.append(f"  {nid}: {node.get('name', '')}")
        lines.append(f"    inputs:  {json.dumps(contract.get('inputs', {}), ensure_ascii=False)}")
        lines.append(f"    outputs: {json.dumps(contract.get('outputs', {}), ensure_ascii=False)}")
    lines.append("")

    # Planned I/O
    lines.append("-" * 70)
    lines.append("2. PLANNED I/O EXAMPLES")
    lines.append("-" * 70)
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        node = nodes_by_id[nid]
        lines.append(f"  {nid}: {node.get('name', '')}")
        lines.append(f"    input_example:  {json.dumps(node.get('input_example'), ensure_ascii=False)[:200]}")
        lines.append(f"    output_example: {json.dumps(node.get('output_example'), ensure_ascii=False)[:200]}")
        lines.append(f"    necessity: {node.get('necessity_claim', '')}")
        lines.append(f"    verify: {node.get('verification_rule', '')}")
        lines.append(f"    gate: {node.get('gate_condition', '')}")
    lines.append("")

    # Actual I/O
    lines.append("-" * 70)
    lines.append("3. ACTUAL I/O (from real LLM execution with recovery)")
    lines.append("-" * 70)
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        aio = node_actual_io.get(nid, {})
        lines.append(f"  {nid}: {nodes_by_id[nid].get('name', '')}")
        lines.append(f"    status: {aio.get('status', 'unknown')}")
        lines.append(f"    recovery: {aio.get('recovery_path', 'unknown')}")
        lines.append(f"    actual_input:")
        ai_str = json.dumps(aio.get("inputs"), ensure_ascii=False, indent=6)
        for line in ai_str.split("\n")[:10]:
            lines.append(f"      {line}")
        lines.append(f"    actual_output:")
        ao_str = json.dumps(aio.get("outputs"), ensure_ascii=False, indent=6)
        for line in ao_str.split("\n")[:15]:
            lines.append(f"      {line}")
        if ao_str.count("\n") > 14:
            lines.append(f"      ... ({ao_str.count(chr(10))+1} lines total)")
        lines.append("")

    # Verification
    lines.append("-" * 70)
    lines.append("4. VERIFICATION RESULTS (with recovery)")
    lines.append("-" * 70)
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        v = node_verifications.get(nid, {"passed": False, "issues": ["not executed"]})
        status = "PASS" if v.get("passed") else "FAIL"
        recovery = recovery_paths.get(nid, "unknown")
        lines.append(f"  {nid}: [{status}] {nodes_by_id[nid].get('name', '')}")
        lines.append(f"    recovery_path: {recovery}")
        lines.append(f"    rule: {v.get('verification_rule', '')}")
        lines.append(f"    result: {v.get('verification_result', '')}")
        if v.get("issues"):
            for issue in v["issues"]:
                lines.append(f"    issue: {issue}")
    lines.append("")

    # Gate status
    lines.append("-" * 70)
    lines.append("5. GATE STATUS")
    lines.append("-" * 70)
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        status = "OPEN" if gate_status.get(nid) else "CLOSED"
        lines.append(f"  {nid}: [{status}] {nodes_by_id[nid].get('name', '')}")
    lines.append("")

    # Judgment sentences
    lines.append("-" * 70)
    lines.append("6. COMPRESSED JUDGMENT SENTENCES")
    lines.append("-" * 70)
    lines.append("")
    all_passed = all(gate_status.get(nid, False) for nid in exec_order if nid in nodes_by_id)
    lines.append(f"  Overall: {'ALL PASS' if all_passed else 'HAS FAILURES'}")
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        v = node_verifications.get(nid, {})
        recovery = recovery_paths.get(nid, "unknown")
        status = "VERIFIED" if v.get("passed") else "FAILED"
        issues_str = f" | issues: {', '.join(v.get('issues', []))}" if v.get("issues") else ""
        lines.append(f"  [{status}]: {nid} — {nodes_by_id[nid].get('name', '')} (via {recovery}){issues_str}")
        lines.append(f"    evidence: log/02_node_{nid}_*.md, modules/{nid}/memory.md")
    lines.append("")

    # Run log
    lines.append("-" * 70)
    lines.append("7. RUN LOG")
    lines.append("-" * 70)
    lines.append("")
    for entry in run_log:
        lines.append(f"  [{entry['timestamp'][:19]}] {entry['step']}: {entry['detail']}")
    lines.append("")

    # File manifest
    lines.append("-" * 70)
    lines.append("8. FILE MANIFEST")
    lines.append("-" * 70)
    lines.append("")
    lines.append("  result.txt — this file")
    lines.append("  log/01_graph_decomposition.md — graph decomposition LLM call")
    for nid in exec_order:
        if nid in nodes_by_id:
            lines.append(f"  log/02_node_{nid}_*.md — node execution LLM calls")
    for nid in exec_order:
        if nid in nodes_by_id:
            lines.append(f"  modules/{nid}/memory.md — per-module memory")
    lines.append("")

    result_path = OUTPUT_DIR / "result.txt"
    result_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Wrote: {result_path}")
    log_event("result_written", str(result_path))

    print(f"\n{'=' * 70}")
    print(f"DONE — {'ALL PASS' if all_passed else 'HAS FAILURES'}")
    print(f"{'=' * 70}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
