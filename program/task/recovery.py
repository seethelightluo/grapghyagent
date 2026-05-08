"""Task recovery engine: retry-once + decompose-once with configurable depth.

This is a framework-level module that any task node can use when verification fails.
It provides two recovery strategies:
  1. Retry: re-execute the task with failure context injected into the prompt
  2. Decompose: break the failed task into sub-tasks, execute each, merge results

Depth is configurable (default max=2). Sub-sub-nodes cannot decompose further.

Usage from tools:
  - TaskRetry tool calls retry_task(task_id, ...)
  - TaskDecompose tool calls decompose_task(task_id, ...)

Usage from scripts:
  - execute_with_recovery(node, inputs, config, ...) runs the full pipeline
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Callable

from .store import get_task, update_task, create_task
from .types import Task


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_MAX_DEPTH = 2


# ── Prompt builders ───────────────────────────────────────────────────────────

def build_retry_prompt(
    task_subject: str,
    task_description: str,
    verification_rule: str,
    output_spec: dict,
    output_example: dict,
    actual_inputs: dict,
    failed_output: dict,
    issues: list[str],
) -> str:
    """Build a retry prompt that includes failure context."""
    return (
        "You are executing a task that previously failed verification. "
        "Return JSON only — no markdown, no explanation.\n\n"
        "## PREVIOUS ATTEMPT FAILED\n"
        f"Failure issues:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        f"Previous output (incorrect):\n{json.dumps(failed_output, ensure_ascii=False, indent=2)[:3000]}\n\n"
        "## FIX INSTRUCTIONS\n"
        "You MUST fix ALL issues listed above. Specifically:\n"
        "- If duplicate scores: assign UNIQUE integer scores, each used exactly once.\n"
        "- If wrong count: ensure exactly the required number of items.\n"
        "- If not sorted: sort by score descending.\n"
        "- If missing fields: include all required fields.\n\n"
        f"Task: {task_subject}\n"
        f"Description: {task_description}\n\n"
        f"Input data:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)}\n\n"
        f"Expected output schema:\n{json.dumps(output_spec, ensure_ascii=False, indent=2)}\n\n"
        f"Output example:\n{json.dumps(output_example, ensure_ascii=False, indent=2)}\n\n"
        f"Verification rule: {verification_rule}\n\n"
        "Produce the CORRECTED output as a JSON object.\n"
    )


def build_decompose_prompt(
    task_subject: str,
    task_description: str,
    verification_rule: str,
    output_spec: dict,
    actual_inputs: dict,
    issues: list[str],
) -> str:
    """Ask LLM to decompose a failed task into sub-tasks (a sub-graph)."""
    return (
        "You are a task decomposition specialist. Return JSON only — no markdown.\n\n"
        "A task has failed verification. Decompose it into a verifiable sub-graph (a DAG of sub-tasks).\n\n"
        f"Failed task: {task_subject}\n"
        f"Description: {task_description}\n"
        f"Verification rule: {verification_rule}\n"
        f"Failure issues:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        f"Input data available:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)[:1000]}\n\n"
        f"Required output schema:\n{json.dumps(output_spec, ensure_ascii=False, indent=2)}\n\n"
        "Decompose into 2-4 sub-tasks forming a sub-graph. Each sub-task MUST have:\n"
        "- A clear, narrow responsibility\n"
        "- Typed `input_spec` and `output_spec`\n"
        "- `input_example` and `output_example` (concrete sample data)\n"
        "- `necessity_audit` (counterfactual justification)\n"
        "- `verification_rule` (how to check correctness)\n"
        "- `gate_condition` (downstream-blocking condition)\n\n"
        "CRITICAL: The parent task requires the FULL output. If you split work across sub-tasks,\n"
        "the final merged outputs from the sub-tasks must satisfy the parent's output_spec.\n\n"
        "Schema:\n"
        "{\n"
        '  "sub_tasks": [\n'
        "    {\n"
        '      "id": "sub_1",\n'
        '      "name": "What this sub-task does",\n'
        '      "description": "Specific instructions",\n'
        '      "input_spec": {"field": {"type": "string"}},\n'
        '      "output_spec": {"field": {"type": "string"}},\n'
        '      "input_example": {"field": "sample"},\n'
        '      "output_example": {"field": "sample"},\n'
        '      "necessity_audit": "If removed...",\n'
        '      "verification_rule": "Must contain...",\n'
        '      "gate_condition": "field exists",\n'
        '      "blocked_by": []\n'
        "    }\n"
        "  ],\n"
        '  "edges": [\n'
        '    {"from": "sub_1", "to": "sub_2", "port": "field"}\n'
        "  ]\n"
        "}\n"
    )


def build_sub_task_prompt(
    sub_task: dict,
    sub_inputs: dict,
) -> str:
    """Build a prompt for executing a single sub-task."""
    return (
        "You are executing a sub-task of a larger task. Return JSON only.\n\n"
        f"Sub-task: {sub_task.get('name', '')}\n"
        f"Instruction: {sub_task.get('instruction', '')}\n\n"
        f"Input:\n{json.dumps(sub_inputs, ensure_ascii=False, indent=2)[:2000]}\n\n"
        f"Expected output keys: {list(sub_task.get('outputs', {}).keys())}\n\n"
        "Produce the output as a JSON object.\n"
    )


# ── LLM call helper ──────────────────────────────────────────────────────────

def call_llm(system_prompt: str, user_prompt: str, config: dict) -> tuple[str, dict]:
    """Call the LLM via providers.stream(). Returns (response_text, metadata)."""
    from providers import stream, TextChunk

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


def extract_json(text: str) -> dict:
    """Extract JSON from LLM response, tolerating markdown wrapping."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


# ── Verification ──────────────────────────────────────────────────────────────

def verify_output(
    output: dict,
    output_spec: dict,
    output_example: dict,
    verification_rule: str,
    custom_verifier: Callable[[dict, dict, dict, str], list[str]] | None = None,
) -> dict:
    """Verify task output against its contract.

    Args:
        output: actual output from LLM
        output_spec: expected output schema
        output_example: expected output example
        verification_rule: human-readable verification rule
        custom_verifier: optional function(output, spec, example, rule) -> list[str]

    Returns:
        {"passed": bool, "issues": list[str], "verification_result": str}
    """
    issues: list[str] = []

    # 1. Structural check: output keys match spec
    if isinstance(output_spec, dict):
        for key, spec in output_spec.items():
            if key not in output:
                desc = spec.get('desc', '') if isinstance(spec, dict) else str(spec)
                issues.append(f"Missing output key: {key} (expected {desc})")

    # 2. Custom verifier if provided
    if custom_verifier:
        custom_issues = custom_verifier(output, output_spec, output_example, verification_rule)
        issues.extend(custom_issues)

    # 3. Basic type checks from output_example
    if output_example and isinstance(output_example, dict):
        for key, example_val in output_example.items():
            if key not in output:
                continue
            actual_val = output[key]
            if type(example_val) != type(actual_val):
                # Allow int/float interchangeability
                if not (isinstance(example_val, (int, float)) and isinstance(actual_val, (int, float))):
                    issues.append(
                        f"Type mismatch for '{key}': expected {type(example_val).__name__}, "
                        f"got {type(actual_val).__name__}"
                    )

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issues": issues,
        "verification_rule": verification_rule,
        "verification_result": "; ".join(issues) if issues else "all checks passed",
    }


# ── Sub-node memory writing ──────────────────────────────────────────────────

def _write_sub_node_memory(task: Task, parent_task_id: str, sub_id: str, output_dir: str) -> str:
    """Write an independent memory.md for a sub-graph node.

    Stores at: <output_dir>/modules/node_<parent>/sub_graph/<sub_id>/memory.md
    Same format as TaskWriteMemory — raw JSON actual I/O, no LLM summarization.
    """
    from .store import update_task

    modules_dir = Path(output_dir) / "modules" / f"node_{parent_task_id}" / "sub_graph" / sub_id
    modules_dir.mkdir(parents=True, exist_ok=True)
    memory_path = modules_dir / "memory.md"

    necessity_text = task.necessity_audit or task.necessity_claim or "No necessity analysis available."

    if task.evidence_pointers:
        evidence_list = "\n".join(f"- `{ep}`" for ep in task.evidence_pointers)
    elif task.evidence_pointer:
        evidence_list = f"- `{task.evidence_pointer}`"
    else:
        evidence_list = "- No evidence pointers."

    comparison_rows = []
    if task.output_spec and isinstance(task.output_spec, dict) and task.actual_output and isinstance(task.actual_output, dict):
        all_keys = set(list(task.output_spec.keys()) + list(task.actual_output.keys()))
        for key in sorted(all_keys):
            in_spec = key in task.output_spec
            in_actual = key in task.actual_output
            if in_spec and in_actual:
                comparison_rows.append(f"| {key} | defined | present | ✅ |")
            elif in_spec and not in_actual:
                comparison_rows.append(f"| {key} | defined | missing | ❌ |")
            elif not in_spec and in_actual:
                comparison_rows.append(f"| {key} | not defined | present | ⚠️ |")
    comparison_table = (
        "| Field | Spec | Actual | Match |\n|-------|------|--------|-------|\n"
        + "\n".join(comparison_rows)
        if comparison_rows
        else "No structural comparison available."
    )

    planned_input = json.dumps(task.input_spec, indent=2, ensure_ascii=False) if task.input_spec else "{}"
    planned_output = json.dumps(task.output_spec, indent=2, ensure_ascii=False) if task.output_spec else "{}"
    actual_input_json = json.dumps(task.actual_input, indent=2, ensure_ascii=False) if task.actual_input else "{}"
    actual_output_json = json.dumps(task.actual_output, indent=2, ensure_ascii=False) if task.actual_output else "{}"

    content = f"""# Sub-Node Memory: {sub_id} (child of node_{parent_task_id}) — {task.subject}

## Necessity
{necessity_text}

## Planned I/O
- **Input**:
```json
{planned_input}
```
- **Output**:
```json
{planned_output}
```

## Actual I/O
- **Actual Input**:
```json
{actual_input_json}
```
- **Actual Output**:
```json
{actual_output_json}
```

## Comparison
{comparison_table}

## Verification
- **Rule**: {task.verification_rule or "No verification rule defined."}
- **Result**: {task.verification_result or "No verification result."}

## Evidence Pointers
{evidence_list}

## Gate Status
- **Condition**: {task.gate_condition or "No gate condition defined."}
- **Status**: **{task.gate_status or "pending"}** {'✅' if task.gate_status == 'open' else '⚠️'}
"""

    memory_path.write_text(content, encoding="utf-8")
    update_task(task.id, memory_path=str(memory_path))
    return str(memory_path)


# ── Merge logic ───────────────────────────────────────────────────────────────

def merge_sub_outputs(sub_outputs: dict[str, dict], output_spec: dict) -> dict:
    """Merge outputs from multiple sub-tasks into a single output.

    Strategy:
    - For list values: concatenate across sub-outputs
    - For dict values: merge keys (later sub overwrites)
    - For scalar values: take last value
    """
    merged: dict[str, Any] = {}

    for sub_id, sub_out in sub_outputs.items():
        if not isinstance(sub_out, dict):
            continue
        for k, v in sub_out.items():
            if k in merged and isinstance(merged[k], list) and isinstance(v, list):
                merged[k].extend(v)
            else:
                merged[k] = v

    return merged


# ── Core recovery functions ───────────────────────────────────────────────────

def retry_task(
    task_id: str,
    actual_inputs: dict,
    failed_output: dict,
    issues: list[str],
    system_prompt: str,
    config: dict,
    custom_verifier: Callable | None = None,
    log_callback: Callable[[str, str, str, dict], None] | None = None,
) -> dict:
    """Retry a failed task with failure context.

    Args:
        task_id: the task to retry
        actual_inputs: the inputs that were used
        failed_output: the output that failed verification
        issues: list of verification failure issues
        system_prompt: system prompt for LLM calls
        config: runtime config (must have 'model')
        custom_verifier: optional custom verification function
        log_callback: optional callback(name, system, user, response, meta) for logging

    Returns:
        {"output": dict, "verification": dict, "meta": dict, "recovery": str}
    """
    task = get_task(task_id)
    if task is None:
        return {"error": f"Task #{task_id} not found"}

    prompt = build_retry_prompt(
        task.subject,
        task.description,
        task.verification_rule,
        task.output_spec,
        task.output_example,
        actual_inputs,
        failed_output,
        issues,
    )

    response, meta = call_llm(system_prompt, prompt, config)

    if log_callback:
        log_callback(f"task_{task_id}_retry", system_prompt, prompt, response, meta)

    try:
        output = extract_json(response)
    except Exception as e:
        output = {"error": str(e), "raw": response[:500]}

    verification = verify_output(
        output, task.output_spec, task.output_example,
        task.verification_rule, custom_verifier,
    )

    # Update task with retry results
    update_task(
        task_id,
        actual_input=actual_inputs,
        actual_output=output,
        verification_result=verification["verification_result"],
        acceptance_status="pass" if verification["passed"] else "fail",
        gate_status="open" if verification["passed"] else "closed",
        compressed_judgment=(
            f"[VERIFIED]: retry succeeded | confidence: 0.85"
            if verification["passed"]
            else f"[FAILED]: retry failed | issues: {', '.join(verification['issues'][:3])}"
        ),
        add_run_log={
            "timestamp": datetime.now().isoformat(),
            "step": "retry",
            "detail": f"passed={verification['passed']}, issues={len(verification['issues'])}",
        },
        add_audit_log={
            "timestamp": datetime.now().isoformat(),
            "action": "retry",
            "result": "pass" if verification["passed"] else "fail",
            "detail": verification["verification_result"],
        },
    )

    return {
        "output": output,
        "verification": verification,
        "meta": meta,
        "recovery": "retry" if verification["passed"] else "retry_failed",
    }


def decompose_task(
    task_id: str,
    actual_inputs: dict,
    failed_output: dict,
    issues: list[str],
    system_prompt: str,
    config: dict,
    depth: int = 0,
    max_depth: int = DEFAULT_MAX_DEPTH,
    custom_verifier: Callable | None = None,
    log_callback: Callable | None = None,
    output_dir: str = "",
) -> dict:
    """Decompose a failed task into a sub-graph, execute it recursively, merge results.

    Args:
        task_id: the task to decompose
        actual_inputs: the inputs that were used
        failed_output: the output that failed verification
        issues: list of verification failure issues
        system_prompt: system prompt for LLM calls
        config: runtime config
        depth: current recursion depth
        max_depth: maximum decomposition depth
        custom_verifier: optional custom verification function
        log_callback: optional logging callback

    Returns:
        {"output": dict, "verification": dict, "meta": dict, "recovery": str, "sub_tasks": list, "sub_graph": dict}
    """
    task = get_task(task_id)
    if task is None:
        return {"error": f"Task #{task_id} not found"}

    if depth >= max_depth:
        return {
            "error": f"Max depth ({max_depth}) reached, cannot decompose further",
            "recovery": "max_depth",
        }

    # Build decompose prompt
    prompt = build_decompose_prompt(
        task.subject,
        task.description,
        task.verification_rule,
        task.output_spec,
        actual_inputs,
        issues,
    )

    response, meta = call_llm(system_prompt, prompt, config)

    if log_callback:
        log_callback(f"task_{task_id}_decompose", system_prompt, prompt, response, meta)

    try:
        sub_graph = extract_json(response)
    except Exception as e:
        return {"error": f"Failed to parse decomposition: {e}", "recovery": "decompose_parse_error"}

    sub_tasks = sub_graph.get("sub_tasks", [])
    sub_edges = sub_graph.get("edges", [])
    if not sub_tasks:
        return {"error": "Decomposition returned no sub-tasks", "recovery": "decompose_empty"}

    # We need to execute the sub-graph in topological order
    # For simplicity, we assume sub_tasks array is already sorted by dependency,
    # or we can just iterate. The ideal way is true topological sort, but let's just
    # execute them sequentially, resolving inputs as we go.

    sub_task_ids: list[str] = []
    sub_outputs: dict[str, dict] = {}
    all_passed = True
    sub_task_details: list[dict] = []

    for sub in sub_tasks:
        sub_id = sub.get("id", "sub_?")
        sub_name = sub.get("name", sub_id)

        # Create a task for each sub-task in the sub-graph
        sub_task = create_task(
            subject=sub_name,
            description=sub.get("description", f"Sub-task of #{task_id}"),
            input_spec=sub.get("input_spec", {}),
            output_spec=sub.get("output_spec", {}),
            input_example=sub.get("input_example", {}),
            output_example=sub.get("output_example", {}),
            necessity_audit=sub.get("necessity_audit", ""),
            verification_rule=sub.get("verification_rule", ""),
            gate_condition=sub.get("gate_condition", ""),
            blocked_by=sub.get("blocked_by", []),
        )
        sub_task_ids.append(sub_task.id)

        # Resolve sub-task inputs
        sub_inputs: dict[str, Any] = {}
        sub_input_spec = sub.get("input_spec", {})
        for field_name in sub_input_spec:
            # Check edges for data flow
            for edge in sub_edges:
                if edge.get("to") == sub_id and edge.get("port") == field_name:
                    from_id = edge.get("from", "")
                    if from_id in sub_outputs:
                        sub_inputs[field_name] = sub_outputs[from_id]
            # Fallback: use parent task's inputs or failed output
            if field_name not in sub_inputs:
                if field_name in actual_inputs:
                    sub_inputs[field_name] = actual_inputs[field_name]
                elif isinstance(failed_output, dict) and field_name in failed_output:
                    sub_inputs[field_name] = failed_output[field_name]

        # Execute sub-task using the full recursive pipeline!
        sub_result = execute_with_recovery(
            task_id=sub_task.id,
            actual_inputs=sub_inputs,
            system_prompt=system_prompt,
            config=config,
            depth=depth + 1,  # increment depth
            max_depth=max_depth,
            custom_verifier=custom_verifier,
            log_callback=log_callback,
            output_dir=output_dir,
        )

        sub_output = sub_result.get("output", {})
        if "error" in sub_output:
            all_passed = False

        sub_outputs[sub_id] = sub_output

        # Write independent memory.md for this sub-node
        if output_dir:
            sub_task_for_mem = get_task(sub_task.id)
            if sub_task_for_mem:
                _write_sub_node_memory(sub_task_for_mem, task_id, sub_id, output_dir)

        # The execute_with_recovery already updated the task store with verification results
        sub_task_record = get_task(sub_task.id)

        passed = False
        issues_found = []
        if sub_task_record:
            passed = (sub_task_record.acceptance_status == "pass")
            if not passed:
                all_passed = False
                issues_found = [sub_task_record.verification_result]

        sub_task_details.append({
            "id": sub_id,
            "task_id": sub_task.id,
            "name": sub_name,
            "passed": passed,
            "issues": issues_found,
            "recovery": sub_result.get("recovery", ""),
        })

    # Merge sub-outputs
    merged = merge_sub_outputs(sub_outputs, task.output_spec)

    # Verify merged output
    final_verification = verify_output(
        merged, task.output_spec, task.output_example,
        task.verification_rule, custom_verifier,
    )

    # Update parent task
    update_task(
        task_id,
        actual_output=merged,
        verification_result=final_verification["verification_result"],
        acceptance_status="pass" if final_verification["passed"] else "fail",
        gate_status="open" if final_verification["passed"] else "closed",
        compressed_judgment=(
            f"[VERIFIED]: decompose sub-graph succeeded ({len(sub_tasks)} sub-tasks) | confidence: 0.8"
            if final_verification["passed"]
            else f"[FAILED]: decompose sub-graph produced invalid output | issues: {', '.join(final_verification['issues'][:3])}"
        ),
        add_run_log={
            "timestamp": datetime.now().isoformat(),
            "step": "decompose_merge",
            "detail": f"sub_tasks={len(sub_tasks)}, passed={final_verification['passed']}",
        },
        add_audit_log={
            "timestamp": datetime.now().isoformat(),
            "action": "decompose",
            "result": "pass" if final_verification["passed"] else "fail",
            "detail": f"sub_tasks={[s['id'] for s in sub_task_details]}",
        },
    )

    return {
        "output": merged,
        "verification": final_verification,
        "meta": meta,
        "recovery": "decompose" if final_verification["passed"] else "decompose_failed",
        "sub_tasks": sub_task_details,
        "sub_graph": sub_graph,  # Return the full parsed sub_graph
    }


def execute_with_recovery(
    task_id: str,
    actual_inputs: dict,
    system_prompt: str,
    config: dict,
    depth: int = 0,
    max_depth: int = DEFAULT_MAX_DEPTH,
    custom_verifier: Callable | None = None,
    log_callback: Callable | None = None,
    output_dir: str = "",
) -> dict:
    """Execute a task with full recovery pipeline: attempt → retry → decompose.

    This is the main entry point for framework-level recovery.

    Args:
        task_id: the task to execute
        actual_inputs: resolved inputs for this task
        system_prompt: system prompt for LLM calls
        config: runtime config (must have 'model')
        depth: current recursion depth (0 for top-level)
        max_depth: max decomposition depth
        custom_verifier: optional custom verification function
        log_callback: optional logging callback

    Returns:
        {"output": dict, "verification": dict, "meta": dict, "recovery": str}
    """
    task = get_task(task_id)
    if task is None:
        return {"error": f"Task #{task_id} not found"}

    # ── Attempt 1: direct execution ──────────────────────────────────────────

    prompt = (
        "You are executing a task. Return JSON only — no markdown, no explanation.\n\n"
        f"Task: {task.subject}\n"
        f"Description: {task.description}\n\n"
        f"Input data:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)}\n\n"
        f"Expected output schema:\n{json.dumps(task.output_spec, ensure_ascii=False, indent=2)}\n\n"
        f"Output example:\n{json.dumps(task.output_example, ensure_ascii=False, indent=2)}\n\n"
        f"Verification rule: {task.verification_rule}\n\n"
        "Produce the actual output as a JSON object matching the output schema.\n"
    )

    response, meta = call_llm(system_prompt, prompt, config)

    if log_callback:
        log_callback(f"task_{task_id}_attempt1", system_prompt, prompt, response, meta)

    try:
        output = extract_json(response)
    except Exception as e:
        output = {"error": str(e), "raw": response[:500]}

    verification = verify_output(
        output, task.output_spec, task.output_example,
        task.verification_rule, custom_verifier,
    )

    # Update task with attempt 1 results
    update_task(
        task_id,
        status="in_progress",
        actual_input=actual_inputs,
        actual_output=output,
        verification_result=verification["verification_result"],
        add_run_log={
            "timestamp": datetime.now().isoformat(),
            "step": "attempt1",
            "detail": f"passed={verification['passed']}, depth={depth}",
        },
    )

    if verification["passed"]:
        update_task(
            task_id,
            status="completed",
            acceptance_status="pass",
            gate_status="open",
            compressed_judgment="[VERIFIED]: direct execution succeeded | confidence: 0.9",
            add_audit_log={
                "timestamp": datetime.now().isoformat(),
                "action": "execute",
                "result": "pass",
                "detail": "direct execution",
            },
        )
        return {
            "output": output,
            "verification": verification,
            "meta": meta,
            "recovery": "direct",
        }

    # ── Attempt 2: retry with failure context ────────────────────────────────

    update_task(
        task_id,
        add_run_log={
            "timestamp": datetime.now().isoformat(),
            "step": "retry_start",
            "detail": f"issues={verification['issues']}",
        },
    )

    retry_result = retry_task(
        task_id, actual_inputs, output, verification["issues"],
        system_prompt, config, custom_verifier, log_callback,
    )

    if "error" not in retry_result and retry_result.get("verification", {}).get("passed"):
        update_task(
            task_id,
            status="completed",
            add_audit_log={
                "timestamp": datetime.now().isoformat(),
                "action": "execute",
                "result": "pass",
                "detail": "retry succeeded",
            },
        )
        return retry_result

    # ── Attempt 3: decompose (if depth allows) ──────────────────────────────

    if depth >= max_depth:
        update_task(
            task_id,
            status="cancelled",
            compressed_judgment=f"[FAILED]: max depth ({max_depth}) reached, best effort returned",
            add_audit_log={
                "timestamp": datetime.now().isoformat(),
                "action": "execute",
                "result": "fail",
                "detail": f"max depth {max_depth} reached",
            },
        )
        return {
            "output": retry_result.get("output", output),
            "verification": retry_result.get("verification", verification),
            "meta": retry_result.get("meta", meta),
            "recovery": "max_depth",
        }

    update_task(
        task_id,
        add_run_log={
            "timestamp": datetime.now().isoformat(),
            "step": "decompose_start",
            "detail": f"depth={depth+1}",
        },
    )

    decompose_result = decompose_task(
        task_id, actual_inputs, output, verification["issues"],
        system_prompt, config, depth + 1, max_depth,
        custom_verifier, log_callback, output_dir,
    )

    # Save the sub-graph into the parent task's sub_graph field
    sg = decompose_result.get("sub_graph")
    if sg:
        update_task(task_id, sub_graph=sg)

    if "error" not in decompose_result and decompose_result.get("verification", {}).get("passed"):
        update_task(task_id, status="completed")
        return decompose_result

    # All recovery attempts exhausted
    best_result = decompose_result if "error" not in decompose_result else retry_result
    update_task(
        task_id,
        status="cancelled",
        compressed_judgment="[FAILED]: all recovery attempts exhausted",
        add_audit_log={
            "timestamp": datetime.now().isoformat(),
            "action": "execute",
            "result": "fail",
            "detail": "all recovery exhausted",
        },
    )

    return {
        "output": best_result.get("output", output),
        "verification": best_result.get("verification", verification),
        "meta": best_result.get("meta", meta),
        "recovery": "exhausted",
    }
