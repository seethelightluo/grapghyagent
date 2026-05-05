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
    """Ask LLM to decompose a failed task into sub-tasks."""
    return (
        "You are a task decomposition specialist. Return JSON only — no markdown.\n\n"
        "A task has failed verification. Decompose it into smaller sub-tasks.\n\n"
        f"Failed task: {task_subject}\n"
        f"Description: {task_description}\n"
        f"Verification rule: {verification_rule}\n"
        f"Failure issues:\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        f"Input data available:\n{json.dumps(actual_inputs, ensure_ascii=False, indent=2)[:1000]}\n\n"
        f"Required output schema:\n{json.dumps(output_spec, ensure_ascii=False, indent=2)}\n\n"
        "Decompose into 2-4 sub-tasks. Each sub-task must:\n"
        "- Have a clear, narrow responsibility\n"
        "- Have explicit input/output schema\n"
        "- Be directly executable (not abstract)\n"
        "- Produce COMPLETE results (not samples or subsets)\n"
        "- If the parent needs N items, each sub-task must produce its full share\n\n"
        "CRITICAL: The parent task requires the FULL output. If you split work across sub-tasks,\n"
        "each sub-task must produce ALL of its items — do not leave placeholders or summaries.\n\n"
        "Schema:\n"
        "{\n"
        '  "sub_tasks": [\n'
        "    {\n"
        '      "id": "sub_1",\n'
        '      "name": "What this sub-task does",\n'
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
) -> dict:
    """Decompose a failed task into sub-tasks, execute each, merge results.

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
        {"output": dict, "verification": dict, "meta": dict, "recovery": str, "sub_tasks": list}
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

    # Create sub-tasks in the store and execute them
    sub_task_ids: list[str] = []
    sub_outputs: dict[str, dict] = {}
    all_passed = True
    sub_task_details: list[dict] = []

    for sub in sub_tasks:
        sub_id = sub.get("id", "sub_?")
        sub_name = sub.get("name", sub_id)

        # Create a task for each sub-task
        sub_task = create_task(
            subject=sub_name,
            description=f"Sub-task of #{task_id}: {sub.get('instruction', '')}",
            input_spec=sub.get("inputs", {}),
            output_spec=sub.get("outputs", {}),
            gate_condition=f"parent_task_{task_id}_decomposed",
        )
        sub_task_ids.append(sub_task.id)

        # Resolve sub-task inputs
        sub_inputs: dict[str, Any] = {}
        sub_input_spec = sub.get("inputs", {})
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

        # Execute sub-task
        sub_prompt = build_sub_task_prompt(sub, sub_inputs)
        sub_response, sub_meta = call_llm(system_prompt, sub_prompt, config)

        if log_callback:
            log_callback(
                f"task_{task_id}_sub_{sub_id}_d{depth+1}",
                system_prompt, sub_prompt, sub_response, sub_meta,
            )

        try:
            sub_output = extract_json(sub_response)
        except Exception as e:
            sub_output = {"error": str(e)}
            all_passed = False

        sub_outputs[sub_id] = sub_output

        # Verify sub-output
        sub_verification = verify_output(
            sub_output, sub.get("outputs", {}), {},
            "", custom_verifier,
        )

        update_task(
            sub_task.id,
            actual_input=sub_inputs,
            actual_output=sub_output,
            verification_result=sub_verification["verification_result"],
            acceptance_status="pass" if sub_verification["passed"] else "fail",
            gate_status="open" if sub_verification["passed"] else "closed",
            add_run_log={
                "timestamp": datetime.now().isoformat(),
                "step": f"sub_{sub_id}_execute",
                "detail": f"depth={depth+1}, passed={sub_verification['passed']}",
            },
        )

        if not sub_verification["passed"]:
            all_passed = False

        sub_task_details.append({
            "id": sub_id,
            "task_id": sub_task.id,
            "name": sub_name,
            "passed": sub_verification["passed"],
            "issues": sub_verification["issues"],
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
            f"[VERIFIED]: decompose succeeded ({len(sub_tasks)} sub-tasks) | confidence: 0.8"
            if final_verification["passed"]
            else f"[FAILED]: decompose produced invalid output | issues: {', '.join(final_verification['issues'][:3])}"
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
        custom_verifier, log_callback,
    )

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
