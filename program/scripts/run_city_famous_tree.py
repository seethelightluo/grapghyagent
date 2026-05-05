"""Verifiable graph execution: city famous things tree.

Every LLM call is logged with full prompt + full response.
No template fallback — if the model fails, we report it honestly.
All artifacts go to example/example1/ with full audit trail.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cc_config import load_config
from providers import stream, TextChunk
from memory.store import MemoryEntry, save_memory

OUTPUT_DIR = ROOT.parent / "example" / "example1"
LOG_DIR = OUTPUT_DIR / "log"


# ── Utilities ────────────────────────────────────────────────────────────────

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


def _call_model(system_prompt: str, user_prompt: str, config: dict, log_prefix: str = "") -> tuple[str, dict]:
    """Call the LLM and return (response_text, metadata).

    metadata contains: model, prompt_tokens (est), response_length, duration_s.
    Full prompt and response are written to log files by the caller.
    """
    messages = [{"role": "user", "content": user_prompt}]
    text_out = ""
    t0 = time.time()
    for event in stream(
        model=config["model"],
        system=system_prompt,
        messages=messages,
        tool_schemas=[],
        config=config,
    ):
        if isinstance(event, TextChunk):
            text_out += event.text
    duration = time.time() - t0

    meta = {
        "model": config.get("model", ""),
        "system_prompt_length": len(system_prompt),
        "user_prompt_length": len(user_prompt),
        "response_length": len(text_out),
        "duration_s": round(duration, 2),
    }
    return text_out, meta


def _write_log(log_dir: Path, name: str, system_prompt: str, user_prompt: str,
               response: str, meta: dict) -> None:
    """Write a complete LLM call log to a file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{name}.md"
    lines = [
        f"# Log: {name}",
        f"",
        f"## Metadata",
        f"```json",
        json.dumps(meta, ensure_ascii=False, indent=2),
        f"```",
        f"",
        f"## System Prompt ({len(system_prompt)} chars)",
        f"```",
        system_prompt,
        f"```",
        f"",
        f"## User Prompt ({len(user_prompt)} chars)",
        f"```",
        user_prompt,
        f"```",
        f"",
        f"## Response ({len(response)} chars)",
        f"```",
        response,
        f"```",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# ── Graph decomposition prompt ───────────────────────────────────────────────

def _build_graph_prompt(task_desc: str) -> str:
    return (
        "You are a task decomposition engine. Return a JSON object only — no markdown, no explanation.\n\n"
        "Decompose the following task into a directed graph. Each node must have:\n"
        "- id, name, strategy (direct/decompose/hybrid)\n"
        "- contract with typed inputs and outputs\n"
        "- input_example: concrete sample input data (not type descriptions)\n"
        "- output_example: concrete expected output data\n"
        "- necessity_claim: why this node is indispensable\n"
        "- necessity_audit: what happens if this node is removed (counterfactual)\n"
        "- verification_rule: how to verify the output (specific checks)\n"
        "- gate_condition: condition that must be true before downstream nodes execute\n\n"
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


# ── Per-node execution prompts ───────────────────────────────────────────────

def _build_node_prompt(node: dict, actual_inputs: dict) -> str:
    """Build a prompt for executing a single node."""
    contract = node.get("contract", {})
    output_desc = contract.get("outputs", {})
    output_example = node.get("output_example", {})

    return (
        "You are executing one node in a task graph. Return JSON only — no markdown, no explanation.\n\n"
        f"Node: {node.get('name', '')}\n"
        f"Task: {node.get('name', '')} — {node.get('necessity_claim', '')}\n\n"
        f"Input data:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)}\n\n"
        f"Expected output schema:\n{json.dumps(output_desc, ensure_ascii=False, indent=2)}\n\n"
        f"Output example (for structure reference):\n{json.dumps(output_example, ensure_ascii=False, indent=2)}\n\n"
        f"Verification rule: {node.get('verification_rule', '')}\n\n"
        "Produce the actual output as a JSON object matching the output schema.\n"
    )


def _build_retry_prompt(node: dict, actual_inputs: dict, failed_output: dict,
                        verification: dict) -> str:
    """Build a retry prompt that includes the failure context."""
    contract = node.get("contract", {})
    output_desc = contract.get("outputs", {})
    output_example = node.get("output_example", {})
    issues = verification.get("issues", [])

    return (
        "You are executing one node in a task graph. Return JSON only — no markdown, no explanation.\n\n"
        "## PREVIOUS ATTEMPT FAILED\n"
        f"Failure issues:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        f"Previous output (incorrect):\n{json.dumps(failed_output, ensure_ascii=False, indent=2)[:3000]}\n\n"
        "## FIX INSTRUCTIONS\n"
        "You MUST fix ALL issues listed above. Specifically:\n"
    ) + (
        "- If duplicate scores: assign UNIQUE integer scores 1-100, each used exactly once.\n"
        "- If wrong count: ensure exactly the required number of items.\n"
        "- If not sorted: sort by score descending.\n"
        "- If missing fields: include all required fields.\n\n"
        f"Node: {node.get('name', '')}\n"
        f"Task: {node.get('necessity_claim', '')}\n\n"
        f"Input data:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)}\n\n"
        f"Expected output schema:\n{json.dumps(output_desc, ensure_ascii=False, indent=2)}\n\n"
        f"Output example:\n{json.dumps(output_example, ensure_ascii=False, indent=2)}\n\n"
        f"Verification rule: {node.get('verification_rule', '')}\n\n"
        "Produce the CORRECTED output as a JSON object.\n"
    )


def _build_decompose_prompt(node: dict, actual_inputs: dict, verification: dict) -> str:
    """Ask LLM to decompose a failed node into sub-nodes."""
    contract = node.get("contract", {})
    issues = verification.get("issues", [])

    return (
        "You are a task decomposition specialist. Return JSON only — no markdown.\n\n"
        f"A task node has failed verification. Decompose it into smaller sub-nodes.\n\n"
        f"Failed node: {node.get('name', '')}\n"
        f"Necessity: {node.get('necessity_claim', '')}\n"
        f"Verification rule: {node.get('verification_rule', '')}\n"
        f"Failure issues:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        f"Input data available:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)[:1000]}\n\n"
        f"Required output schema:\n{json.dumps(contract.get('outputs', {}), ensure_ascii=False, indent=2)}\n\n"
        "Decompose into 2-4 sub-nodes. Each sub-node must:\n"
        "- Have a clear, narrow responsibility\n"
        "- Have explicit input/output schema\n"
        "- Be directly executable (not abstract)\n"
        "- Produce COMPLETE results (not samples or subsets)\n"
        "- If the parent needs 100 items, each sub-node must produce its full share\n\n"
        "CRITICAL: The parent node requires the FULL output. If you split work across sub-nodes,\n"
        "each sub-node must produce ALL of its items — do not leave placeholders or summaries.\n\n"
        "Schema:\n"
        "{\n"
        '  "sub_nodes": [\n'
        "    {\n"
        '      "id": "sub_1",\n'
        '      "name": "What this sub-node does",\n'
        '      "inputs": {"field": {"type": "string", "desc": "..."}},\n'
        '      "outputs": {"field": {"type": "string", "desc": "..."}},\n'
        '      "instruction": "Specific instructions for execution"\n'
        "    }\n"
        "  ],\n"
        '  "edges": [\n'
        '    {"from": "sub_1", "to": "sub_2", "port": "field"}\n'
        "  ]\n"
        "}\n"
    )


MAX_DEPTH = 2  # sub-sub-nodes cannot decompose further


def _execute_node_with_recovery(
    node: dict, actual_inputs: dict, config: dict, system_prompt: str,
    log_dir: Path, log_prefix: str, run_log: list, depth: int = 0,
) -> tuple[dict, dict, dict, str]:
    """Execute a node with retry + decomposition recovery.

    Returns (actual_output, verification, meta, recovery_path).
    recovery_path is one of: "direct", "retry", "decompose".
    """
    node_id = node.get("id", "unknown")

    # ── Attempt 1: direct execution ──────────────────────────────────────────

    prompt = _build_node_prompt(node, actual_inputs)
    response, meta = _call_model(system_prompt, prompt, config)
    _write_log(log_dir, f"{log_prefix}_attempt1", system_prompt, prompt, response, meta)
    run_log.append({"timestamp": datetime.now().isoformat(), "step": f"{node_id}_attempt1",
                    "detail": f"depth={depth}, len={len(response)}, dur={meta['duration_s']}s"})

    try:
        output = _extract_json(response)
    except Exception as e:
        output = {"error": str(e), "raw": response[:500]}

    verification = _verify_node_output(node, output)
    if verification["passed"]:
        return output, verification, meta, "direct"

    # ── Attempt 2: retry with failure context ────────────────────────────────

    print(f"    RETRY: {verification['issues']}")
    run_log.append({"timestamp": datetime.now().isoformat(), "step": f"{node_id}_retry",
                    "detail": f"issues={verification['issues']}"})

    retry_prompt = _build_retry_prompt(node, actual_inputs, output, verification)
    retry_response, retry_meta = _call_model(system_prompt, retry_prompt, config)
    _write_log(log_dir, f"{log_prefix}_attempt2_retry", system_prompt, retry_prompt, retry_response, retry_meta)
    run_log.append({"timestamp": datetime.now().isoformat(), "step": f"{node_id}_attempt2",
                    "detail": f"depth={depth}, len={len(retry_response)}, dur={retry_meta['duration_s']}s"})

    try:
        retry_output = _extract_json(retry_response)
    except Exception as e:
        retry_output = {"error": str(e), "raw": retry_response[:500]}

    retry_verification = _verify_node_output(node, retry_output)
    if retry_verification["passed"]:
        return retry_output, retry_verification, retry_meta, "retry"

    # ── Attempt 3: decompose into sub-nodes (if depth allows) ────────────────

    if depth >= MAX_DEPTH:
        print(f"    MAX DEPTH ({MAX_DEPTH}) reached, cannot decompose further")
        run_log.append({"timestamp": datetime.now().isoformat(), "step": f"{node_id}_max_depth",
                        "detail": f"depth={depth}, returning best attempt"})
        # Return retry result even if failed — it's the best we have
        return retry_output, retry_verification, retry_meta, "retry_failed"

    print(f"    DECOMPOSE: breaking into sub-nodes (depth={depth+1})")
    run_log.append({"timestamp": datetime.now().isoformat(), "step": f"{node_id}_decompose",
                    "detail": f"depth={depth+1}"})

    decompose_prompt = _build_decompose_prompt(node, actual_inputs, retry_verification)
    decompose_response, decompose_meta = _call_model(system_prompt, decompose_prompt, config)
    _write_log(log_dir, f"{log_prefix}_decompose_plan", system_prompt, decompose_prompt, decompose_response, decompose_meta)

    try:
        sub_graph = _extract_json(decompose_response)
    except Exception as e:
        print(f"    DECOMPOSE PARSE ERROR: {e}")
        return retry_output, retry_verification, retry_meta, "retry_failed"

    sub_nodes = sub_graph.get("sub_nodes", [])
    sub_edges = sub_graph.get("edges", [])
    if not sub_nodes:
        print(f"    DECOMPOSE returned no sub-nodes")
        return retry_output, retry_verification, retry_meta, "retry_failed"

    print(f"    DECOMPOSED into {len(sub_nodes)} sub-nodes: {[s.get('id') for s in sub_nodes]}")

    # Execute sub-nodes sequentially
    sub_outputs = {}
    all_sub_passed = True
    final_output = {}

    for sub_node in sub_nodes:
        sub_id = sub_node.get("id", "sub_?")
        sub_name = sub_node.get("name", sub_id)

        # Resolve sub-node inputs
        sub_inputs = {}
        sub_input_spec = sub_node.get("inputs", {})
        for field_name in sub_input_spec:
            # Check edges for data flow
            for edge in sub_edges:
                if edge.get("to") == sub_id and edge.get("port") == field_name:
                    from_id = edge.get("from", "")
                    if from_id in sub_outputs:
                        sub_inputs[field_name] = sub_outputs[from_id]
            # Fallback: use parent node's inputs
            if field_name not in sub_inputs:
                if field_name in actual_inputs:
                    sub_inputs[field_name] = actual_inputs[field_name]
                elif field_name in (output if isinstance(output, dict) else {}):
                    sub_inputs[field_name] = output[field_name]

        # Build sub-node execution prompt with the instruction
        sub_prompt = (
            "You are executing a sub-node of a larger task. Return JSON only.\n\n"
            f"Sub-node: {sub_name}\n"
            f"Instruction: {sub_node.get('instruction', '')}\n\n"
            f"Input:\n{json.dumps(sub_inputs, ensure_ascii=False, indent=2)[:2000]}\n\n"
            f"Expected output keys: {list(sub_node.get('outputs', {}).keys())}\n\n"
            "Produce the output as a JSON object.\n"
        )

        sub_response, sub_meta = _call_model(system_prompt, sub_prompt, config)
        sub_log_name = f"{log_prefix}_sub_{sub_id}_d{depth+1}"
        _write_log(log_dir, sub_log_name, system_prompt, sub_prompt, sub_response, sub_meta)
        run_log.append({"timestamp": datetime.now().isoformat(),
                        "step": f"{node_id}_sub_{sub_id}",
                        "detail": f"depth={depth+1}, len={len(sub_response)}, dur={sub_meta['duration_s']}s"})

        try:
            sub_output = _extract_json(sub_response)
        except Exception as e:
            sub_output = {"error": str(e)}
            all_sub_passed = False

        sub_outputs[sub_id] = sub_output

    # Merge sub-node outputs into the parent node's output format
    # Strategy: merge all sub-output dicts, but for list values, concatenate them
    if sub_outputs:
        final_output = {}
        for sub_node in sub_nodes:
            sub_id = sub_node.get("id", "")
            if sub_id not in sub_outputs:
                continue
            sub_out = sub_outputs[sub_id]
            if not isinstance(sub_out, dict):
                continue
            for k, v in sub_out.items():
                if k in final_output and isinstance(final_output[k], list) and isinstance(v, list):
                    final_output[k].extend(v)
                else:
                    final_output[k] = v

        # Special handling for ranked_items: re-sort and re-rank after merge
        if "ranked_items" in final_output and isinstance(final_output["ranked_items"], list):
            ranked = final_output["ranked_items"]
            # Sort by importance_score descending
            ranked.sort(key=lambda x: x.get("importance_score", x.get("score", 0)), reverse=True)
            # Re-assign ranks 1..N
            for i, item in enumerate(ranked):
                item["rank"] = i + 1
            final_output["ranked_items"] = ranked

    final_verification = _verify_node_output(node, final_output)
    run_log.append({"timestamp": datetime.now().isoformat(),
                    "step": f"{node_id}_decompose_result",
                    "detail": f"passed={final_verification['passed']}, sub_nodes={len(sub_nodes)}"})

    if final_verification["passed"]:
        return final_output, final_verification, decompose_meta, "decompose"
    else:
        # Even decompose failed — return best result
        return final_output, final_verification, decompose_meta, "decompose_failed"


# ── Verification ─────────────────────────────────────────────────────────────

def _verify_node_output(node: dict, actual_output: dict) -> dict:
    """Verify a node's actual output against its contract and rules."""
    contract = node.get("contract", {})
    output_spec = contract.get("outputs", {})
    verification_rule = node.get("verification_rule", "")
    issues = []

    # Check output keys match contract
    for key, spec in output_spec.items():
        if key not in actual_output:
            issues.append(f"Missing output key: {key} (expected {spec.get('desc', '')})")

    # Specific checks based on node type
    node_id = node.get("id", "")

    # Check for city list under various key names
    city_list = actual_output.get("cities") or actual_output.get("city_list")
    if city_list is not None:
        if not isinstance(city_list, list):
            issues.append(f"city list should be list, got {type(city_list).__name__}")
        elif len(city_list) != 10:
            issues.append(f"Expected 10 cities, got {len(city_list)}")

    if "famous_things" in actual_output:
        things = actual_output["famous_things"]
        if not isinstance(things, list):
            issues.append(f"famous_things should be list, got {type(things).__name__}")
        else:
            # Support both flat [{city, thing}] and nested [{city, items: [...]}]
            if things and isinstance(things[0], dict) and "items" in things[0]:
                # Nested: [{city, items: [{name, ...}, ...]}]
                total = sum(len(city.get("items", [])) for city in things)
                city_count = len(things)
            elif things and isinstance(things[0], dict) and "thing" in things[0]:
                # Flat: [{city, thing}]
                total = len(things)
                city_count = len(set(t.get("city", "") for t in things))
            else:
                total = len(things)
                city_count = 0
            if total != 100:
                issues.append(f"Expected 100 items total, got {total}")
            if city_count not in (0, 10):
                issues.append(f"Expected 10 cities worth of items, got {city_count}")

    if "all_items" in actual_output:
        items = actual_output["all_items"]
        if not isinstance(items, list):
            issues.append(f"all_items should be list, got {type(items).__name__}")
        elif len(items) != 100:
            issues.append(f"Expected 100 items, got {len(items)}")

    if "ranked_items" in actual_output:
        ranked = actual_output["ranked_items"]
        if not isinstance(ranked, list):
            issues.append(f"ranked_items should be list, got {type(ranked).__name__}")
        elif len(ranked) != 100:
            issues.append(f"Expected 100 ranked items, got {len(ranked)}")
        else:
            # Support both "score" and "importance_score" field names
            scores = [
                r.get("importance_score", r.get("score", 0))
                for r in ranked if isinstance(r, dict)
            ]
            if len(scores) != len(set(scores)):
                dupes = [s for s in set(scores) if scores.count(s) > 1]
                issues.append(f"Duplicate scores found in ranking: {dupes[:5]}")
            sorted_check = all(scores[i] >= scores[i+1] for i in range(len(scores)-1))
            if not sorted_check:
                issues.append("Ranked items not sorted by score descending")

    if "tree_text" in actual_output:
        tree = actual_output["tree_text"]
        if not isinstance(tree, str):
            issues.append(f"tree_text should be string, got {type(tree).__name__}")
        elif len(tree) < 100:
            issues.append(f"tree_text suspiciously short ({len(tree)} chars)")

    if "txt_content" in actual_output:
        txt = actual_output["txt_content"]
        if not isinstance(txt, str):
            issues.append(f"txt_content should be string, got {type(txt).__name__}")
        elif len(txt) < 200:
            issues.append(f"txt_content suspiciously short ({len(txt)} chars)")

    if "is_complete" in actual_output:
        if not isinstance(actual_output["is_complete"], bool):
            issues.append(f"is_complete should be boolean, got {type(actual_output['is_complete']).__name__}")

    if "is_valid_ranking" in actual_output:
        if not isinstance(actual_output["is_valid_ranking"], bool):
            issues.append(f"is_valid_ranking should be boolean, got {type(actual_output['is_valid_ranking']).__name__}")

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "verification_rule": verification_rule,
        "verification_result": "; ".join(issues) if issues else "all checks passed",
    }


# ── Necessity audit ──────────────────────────────────────────────────────────

def _necessity_audit(graph: dict) -> dict[str, dict]:
    """Compute counterfactual necessity for each node via reachability analysis."""
    nodes = [n.get("id", "") for n in graph.get("nodes", [])]
    edges = graph.get("edges", [])
    output_nodes = {v.get("nodeId", "") for v in graph.get("outputMapping", {}).values()}
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        src = e.get("from", {}).get("nodeId", "")
        dst = e.get("to", {}).get("nodeId", "")
        if src and dst:
            adj.setdefault(src, []).append(dst)

    def _reaches_output(start: str) -> bool:
        seen = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if cur in output_nodes:
                return True
            for nxt in adj.get(cur, []):
                stack.append(nxt)
        return False

    results = {}
    for node_id in nodes:
        reaches = _reaches_output(node_id)
        results[node_id] = {
            "counterfactual": f"remove {node_id}",
            "reaches_output": reaches,
            "necessary": reaches,
            "impact": "breaks path to final output" if reaches else "no path to output — possibly redundant",
        }
    return results


# ── Audit agent ──────────────────────────────────────────────────────────────

def _audit_with_agent(audit_payload: dict, config: dict, system_prompt: str) -> tuple[dict, str, str, dict]:
    """Run independent audit agent. Returns (audit_result, user_prompt, response, meta)."""
    user_prompt = (
        "You are an independent audit agent. Return JSON only — no markdown.\n\n"
        "For each node in the payload below, verify:\n"
        "1. Does the actual output match the output_example structure?\n"
        "2. Does the verification_rule pass?\n"
        "3. Is the necessity_claim justified by the necessity_audit?\n"
        "4. Should the gate_condition be open or closed?\n\n"
        "Return:\n"
        "{\n"
        '  "nodes": [\n'
        "    {\n"
        '      "id": "node_id",\n'
        '      "acceptance_status": "pass|fail",\n'
        '      "verification_result": "specific checks and results",\n'
        '      "compressed_judgment": "[VERIFIED/FAILED]: one sentence claim | evidence: pointer",\n'
        '      "evidence_pointer": ["result.txt#section"],\n'
        '      "gate_open": true|false\n'
        "    }\n"
        "  ],\n"
        '  "overall": "pass|fail",\n'
        '  "summary": "one paragraph summary"\n'
        "}\n\n"
        f"Payload:\n{json.dumps(audit_payload, ensure_ascii=False, indent=2)}\n"
    )
    response, meta = _call_model(system_prompt, user_prompt, config, "audit_agent")
    try:
        result = _extract_json(response)
    except Exception:
        result = {"error": "failed to parse audit response", "raw": response[:500]}
    return result, user_prompt, response, meta


# ── Topological execution ────────────────────────────────────────────────────

def _topological_order(graph: dict) -> list[str]:
    """Return node IDs in topological order."""
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


def _resolve_node_inputs(node: dict, graph: dict, node_outputs: dict) -> dict:
    """Resolve a node's actual inputs from edge connections and prior outputs."""
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

    # If no edges resolved, use inputMapping from graph
    if not actual_inputs:
        for mapping_port, mapping in graph.get("inputMapping", {}).items():
            if mapping.get("nodeId") == node_id:
                port = mapping.get("port", "")
                if port in input_spec:
                    actual_inputs[port] = f"<task_input:{mapping_port}>"

    return actual_inputs


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    task_desc = (
        "搜寻世界上前10城市的10个出名的事物共100个，用树结构可视化展现出来，"
        "同时对这100个的重要性排序，排序结果生成txt文件"
    )
    if len(sys.argv) > 1:
        task_desc = " ".join(sys.argv[1:]).strip()

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

    # ── Step 1: Graph decomposition ──────────────────────────────────────────

    print("\n" + "=" * 70)
    print("STEP 1: Graph Decomposition (LLM call)")
    print("=" * 70)

    graph_prompt = _build_graph_prompt(task_desc)
    graph_response, graph_meta = _call_model(system_prompt, graph_prompt, config)
    _write_log(LOG_DIR, "01_graph_decomposition", system_prompt, graph_prompt, graph_response, graph_meta)
    log_event("graph_decomposition", f"response_length={len(graph_response)}, duration={graph_meta['duration_s']}s")

    try:
        graph = _extract_json(graph_response)
    except Exception as e:
        log_event("graph_parse_error", str(e))
        print(f"\nFATAL: Could not parse graph JSON from LLM response. See log/01_graph_decomposition.md")
        return 2

    # Validate graph structure
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

    # ── Step 2: Topological execution ────────────────────────────────────────

    print("\n" + "=" * 70)
    print("STEP 2: Execute Each Node (real LLM calls)")
    print("=" * 70)

    exec_order = _topological_order(graph)
    node_outputs: dict[str, Any] = {}
    node_actual_io: dict[str, dict] = {}
    node_verifications: dict[str, dict] = {}
    gate_status: dict[str, bool] = {}

    recovery_paths: dict[str, str] = {}

    for nid in exec_order:
        node = nodes_by_id.get(nid)
        if not node:
            log_event("skip_unknown_node", nid)
            continue

        print(f"\n  --- {nid}: {node.get('name', '')} ---")

        # Check gate conditions from predecessors
        blocked = False
        for edge in graph.get("edges", []):
            if edge.get("to", {}).get("nodeId") == nid:
                src_id = edge.get("from", {}).get("nodeId", "")
                if src_id in gate_status and not gate_status[src_id]:
                    blocked = True
                    print(f"    GATE BLOCKED by {src_id}")
                    log_event(f"{nid}_gate_blocked", f"blocked by {src_id}")
                    break

        if blocked:
            node_actual_io[nid] = {"inputs": {}, "outputs": {}, "status": "blocked"}
            gate_status[nid] = False
            recovery_paths[nid] = "blocked"
            continue

        # Resolve inputs
        actual_inputs = _resolve_node_inputs(node, graph, node_outputs)
        print(f"    Input keys: {list(actual_inputs.keys())}")

        # Execute with retry + decomposition recovery
        actual_output, verification, node_meta, recovery = _execute_node_with_recovery(
            node, actual_inputs, config, system_prompt,
            LOG_DIR, f"02_node_{nid}", run_log, depth=0,
        )

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

    # ── Step 3: Necessity audit ──────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("STEP 3: Necessity Audit (counterfactual analysis)")
    print("=" * 70)

    necessity_results = _necessity_audit(graph)
    for nid, info in necessity_results.items():
        print(f"  {nid}: necessary={info['necessary']} — {info['impact']}")
    log_event("necessity_audit", f"nodes={len(necessity_results)}")

    # ── Step 4: Independent audit agent ──────────────────────────────────────

    print("\n" + "=" * 70)
    print("STEP 4: Independent Audit Agent (LLM call)")
    print("=" * 70)

    audit_payload = {
        "task": task_desc,
        "nodes": [
            {
                "id": nid,
                "name": nodes_by_id[nid].get("name", ""),
                "necessity_claim": nodes_by_id[nid].get("necessity_claim", ""),
                "necessity_audit": necessity_results.get(nid, {}),
                "input_example": nodes_by_id[nid].get("input_example"),
                "output_example": nodes_by_id[nid].get("output_example"),
                "actual_io": node_actual_io.get(nid, {}),
                "verification": node_verifications.get(nid, {}),
            }
            for nid in exec_order if nid in nodes_by_id
        ]
    }

    audit_result, audit_prompt, audit_response, audit_meta = _audit_with_agent(
        audit_payload, config, system_prompt
    )
    _write_log(LOG_DIR, "03_audit_agent", system_prompt, audit_prompt, audit_response, audit_meta)
    log_event("audit_agent", f"overall={audit_result.get('overall', 'unknown')}")

    # ── Step 5: Write module memory files ────────────────────────────────────

    print("\n" + "=" * 70)
    print("STEP 5: Per-Module Memory Files")
    print("=" * 70)

    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        node = nodes_by_id[nid]
        mod_dir = OUTPUT_DIR / "modules" / nid
        mod_dir.mkdir(parents=True, exist_ok=True)

        audit_node = {}
        for an in audit_result.get("nodes", []):
            if an.get("id") == nid:
                audit_node = an
                break

        mem_content = "\n".join([
            f"# Module: {nid} — {node.get('name', '')}",
            f"",
            f"## Necessity",
            f"- claim: {node.get('necessity_claim', '')}",
            f"- audit: {json.dumps(necessity_results.get(nid, {}), ensure_ascii=False)}",
            f"",
            f"## Planned I/O",
            f"- input_example: {json.dumps(node.get('input_example'), ensure_ascii=False)}",
            f"- output_example: {json.dumps(node.get('output_example'), ensure_ascii=False)}",
            f"",
            f"## Actual I/O",
            f"- actual_input: {json.dumps(node_actual_io.get(nid, {}).get('inputs'), ensure_ascii=False, indent=2)}",
            f"- actual_output: {json.dumps(node_actual_io.get(nid, {}).get('outputs'), ensure_ascii=False, indent=2)[:2000]}",
            f"",
            f"## Verification",
            f"- status: {node_actual_io.get(nid, {}).get('status', 'unknown')}",
            f"- rule: {node.get('verification_rule', '')}",
            f"- result: {json.dumps(node_verifications.get(nid, {}), ensure_ascii=False)}",
            f"",
            f"## Gate",
            f"- condition: {node.get('gate_condition', '')}",
            f"- status: {'open' if gate_status.get(nid) else 'closed'}",
            f"",
            f"## Audit Agent",
            f"- acceptance: {audit_node.get('acceptance_status', 'unknown')}",
            f"- judgment: {audit_node.get('compressed_judgment', '')}",
            f"- evidence: {audit_node.get('evidence_pointer', [])}",
        ])
        (mod_dir / "memory.md").write_text(mem_content, encoding="utf-8")
        print(f"  {nid}/memory.md")
    log_event("module_memories", f"count={len(exec_order)}")

    # ── Step 6: Write result.txt ─────────────────────────────────────────────

    print("\n" + "=" * 70)
    print("STEP 6: Write result.txt")
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
        lines.append(f"  {nid}: {node.get('name', '')}")
        lines.append(f"    strategy: {node.get('strategy', '')}")
        contract = node.get("contract", {})
        lines.append(f"    inputs:  {json.dumps(contract.get('inputs', {}), ensure_ascii=False)}")
        lines.append(f"    outputs: {json.dumps(contract.get('outputs', {}), ensure_ascii=False)}")
    lines.append("")

    # Planned I/O examples
    lines.append("-" * 70)
    lines.append("2. PLANNED I/O EXAMPLES (from graph decomposition)")
    lines.append("-" * 70)
    lines.append("")
    for nid in exec_order:
        if nid not in nodes_by_id:
            continue
        node = nodes_by_id[nid]
        lines.append(f"  {nid}: {node.get('name', '')}")
        lines.append(f"    input_example:  {json.dumps(node.get('input_example'), ensure_ascii=False)[:200]}")
        lines.append(f"    output_example: {json.dumps(node.get('output_example'), ensure_ascii=False)[:200]}")
        lines.append(f"    necessity_claim: {node.get('necessity_claim', '')}")
        lines.append(f"    verification_rule: {node.get('verification_rule', '')}")
        lines.append(f"    gate_condition: {node.get('gate_condition', '')}")
    lines.append("")

    # Actual I/O
    lines.append("-" * 70)
    lines.append("3. ACTUAL I/O (from real LLM execution)")
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
        actual_in_str = json.dumps(aio.get("inputs"), ensure_ascii=False, indent=6)
        for line in actual_in_str.split("\n")[:10]:
            lines.append(f"      {line}")
        if actual_in_str.count("\n") > 9:
            lines.append(f"      ... ({actual_in_str.count(chr(10))+1} lines total)")
        lines.append(f"    actual_output:")
        actual_out_str = json.dumps(aio.get("outputs"), ensure_ascii=False, indent=6)
        for line in actual_out_str.split("\n")[:15]:
            lines.append(f"      {line}")
        if actual_out_str.count("\n") > 14:
            lines.append(f"      ... ({actual_out_str.count(chr(10))+1} lines total)")
        lines.append("")

    # Verification results with recovery paths
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
        cond = nodes_by_id[nid].get("gate_condition", "")
        if cond:
            lines.append(f"    condition: {cond}")
    lines.append("")

    # Necessity audit
    lines.append("-" * 70)
    lines.append("6. NECESSITY AUDIT (counterfactual analysis)")
    lines.append("-" * 70)
    lines.append("")
    for nid, info in necessity_results.items():
        necessary = "YES" if info["necessary"] else "NO"
        lines.append(f"  {nid}: [{necessary}] {info['impact']}")
    lines.append("")

    # Audit agent report
    lines.append("-" * 70)
    lines.append("7. INDEPENDENT AUDIT AGENT REPORT")
    lines.append("-" * 70)
    lines.append("")
    lines.append(f"  Overall: {audit_result.get('overall', 'unknown')}")
    lines.append(f"  Summary: {audit_result.get('summary', 'N/A')}")
    lines.append("")
    for an in audit_result.get("nodes", []):
        lines.append(f"  {an.get('id', '?')}: [{an.get('acceptance_status', '?')}]")
        lines.append(f"    verification: {an.get('verification_result', '')}")
        lines.append(f"    judgment: {an.get('compressed_judgment', '')}")
        lines.append(f"    evidence: {an.get('evidence_pointer', [])}")
        lines.append(f"    gate_open: {an.get('gate_open', '?')}")
    lines.append("")

    # Judgment sentences
    lines.append("-" * 70)
    lines.append("8. COMPRESSED JUDGMENT SENTENCES")
    lines.append("-" * 70)
    lines.append("")
    all_passed = all(gate_status.get(nid, False) for nid in exec_order if nid in nodes_by_id)
    lines.append(f"  Overall status: {'ALL PASS' if all_passed else 'HAS FAILURES'}")
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
    lines.append("9. RUN LOG")
    lines.append("-" * 70)
    lines.append("")
    for entry in run_log:
        lines.append(f"  [{entry['timestamp'][:19]}] {entry['step']}: {entry['detail']}")
    lines.append("")

    # File manifest
    lines.append("-" * 70)
    lines.append("10. FILE MANIFEST")
    lines.append("-" * 70)
    lines.append("")
    lines.append("  result.txt — this file")
    lines.append("  log/01_graph_decomposition.md — full LLM prompt + response for graph")
    for nid in exec_order:
        if nid in nodes_by_id:
            lines.append(f"  log/02_node_{nid}_execution.md — full LLM prompt + response for {nid}")
    lines.append("  log/03_audit_agent.md — full LLM prompt + response for audit")
    for nid in exec_order:
        if nid in nodes_by_id:
            lines.append(f"  modules/{nid}/memory.md — per-module audit memory")
    lines.append("")

    result_path = OUTPUT_DIR / "result.txt"
    result_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Wrote: {result_path}")
    log_event("result_written", str(result_path))

    # Save judgment to project memory
    try:
        save_memory(
            MemoryEntry(
                name="city_famous_tree_run",
                description=f"Verifiable graph run — {'pass' if all_passed else 'fail'}",
                type="project",
                content=f"Status: {'ALL PASS' if all_passed else 'HAS FAILURES'}\nEvidence: {result_path}\nNodes: {len(nodes_by_id)}",
                source="tool",
            ),
            scope="project",
        )
    except Exception:
        pass

    print(f"\n{'=' * 70}")
    print(f"DONE — {'ALL PASS' if all_passed else 'HAS FAILURES'}")
    print(f"{'=' * 70}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
