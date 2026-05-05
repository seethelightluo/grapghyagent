"""Task tools: TaskCreate, TaskUpdate, TaskGet, TaskList — registered into tool_registry."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from tool_registry import ToolDef, register_tool
from .store import create_task, get_task, list_tasks, update_task, delete_task, check_gate_conditions
from .types import TaskStatus


# ── Schemas ───────────────────────────────────────────────────────────────────

_TASK_CREATE_SCHEMA = {
    "name": "TaskCreate",
    "description": (
        "Create a new task in the task list. "
        "Use this to track work items, to-dos, and multi-step plans. "
        "Returns the new task's ID and subject."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "A brief title for the task",
            },
            "description": {
                "type": "string",
                "description": "What needs to be done",
            },
            "active_form": {
                "type": "string",
                "description": (
                    "Present-continuous label shown while in_progress "
                    "(e.g. 'Running tests', 'Writing docs')"
                ),
            },
            "metadata": {
                "type": "object",
                "description": "Arbitrary key-value metadata to attach to the task",
            },
            "input_spec": {
                "type": "object",
                "description": "Input contract/schema for this task",
            },
            "output_spec": {
                "type": "object",
                "description": "Output contract/schema for this task",
            },
            "audit_status": {
                "type": "string",
                "description": "Audit status for this task",
            },
            "necessity_claim": {
                "type": "string",
                "description": "Why this task is necessary for the goal",
            },
            "verification_rule": {
                "type": "string",
                "description": "Rule used to verify the task output",
            },
            "acceptance_status": {
                "type": "string",
                "description": "Verification outcome (e.g. pass/fail/unchecked)",
            },
            "compressed_judgment": {
                "type": "string",
                "description": "Short judgment sentence summarizing the outcome",
            },
            "evidence_pointer": {
                "type": "string",
                "description": "Pointer to evidence (file path or URL)",
            },
            "input_example": {
                "type": "object",
                "description": "Example input data for this task (planning phase I/O sample)",
            },
            "output_example": {
                "type": "object",
                "description": "Expected output data for this task (planning phase I/O sample)",
            },
            "gate_condition": {
                "type": "string",
                "description": "Condition that must be satisfied before downstream tasks can execute (e.g. 'count == 10 AND no duplicates')",
            },
            "necessity_audit": {
                "type": "string",
                "description": "Counterfactual analysis: what happens if this node is removed? Why is it indispensable?",
            },
            "evidence_pointers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Fine-grained evidence pointers (e.g. ['result.txt#section_a', 'log.txt#line_42'])",
            },
        },
        "required": ["subject", "description"],
    },
}

_TASK_UPDATE_SCHEMA = {
    "name": "TaskUpdate",
    "description": (
        "Update an existing task. Can change subject, description, status, owner, "
        "dependency edges (blocks / blocked_by), and metadata. "
        "Set status='deleted' to remove the task. "
        "Valid statuses: pending, in_progress, completed, cancelled, deleted."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to update",
            },
            "subject": {
                "type": "string",
                "description": "New title for the task",
            },
            "description": {
                "type": "string",
                "description": "New description for the task",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed", "cancelled", "deleted"],
                "description": "New status ('deleted' removes the task)",
            },
            "active_form": {
                "type": "string",
                "description": "Present-continuous label while in_progress",
            },
            "owner": {
                "type": "string",
                "description": "Agent/user responsible for this task",
            },
            "add_blocks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs that this task now blocks",
            },
            "add_blocked_by": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Task IDs that block this task",
            },
            "metadata": {
                "type": "object",
                "description": "Keys to merge into task metadata (null value = delete key)",
            },
            "input_spec": {
                "type": "object",
                "description": "Replace the task input contract/schema",
            },
            "output_spec": {
                "type": "object",
                "description": "Replace the task output contract/schema",
            },
            "audit_status": {
                "type": "string",
                "description": "Update the task audit status",
            },
            "necessity_claim": {
                "type": "string",
                "description": "Update the necessity rationale",
            },
            "verification_rule": {
                "type": "string",
                "description": "Update the verification rule",
            },
            "acceptance_status": {
                "type": "string",
                "description": "Update the verification outcome",
            },
            "compressed_judgment": {
                "type": "string",
                "description": "Update the compressed judgment sentence",
            },
            "evidence_pointer": {
                "type": "string",
                "description": "Update the evidence pointer",
            },
            "input_example": {
                "type": "object",
                "description": "Update the example input data",
            },
            "output_example": {
                "type": "object",
                "description": "Update the expected output data",
            },
            "actual_input": {
                "type": "object",
                "description": "Record the actual input received during execution",
            },
            "actual_output": {
                "type": "object",
                "description": "Record the actual output produced during execution",
            },
            "verification_result": {
                "type": "string",
                "description": "Actual verification result (e.g. 'exact_count_check=true; duplicates=false')",
            },
            "gate_condition": {
                "type": "string",
                "description": "Update the gate condition for downstream execution",
            },
            "gate_status": {
                "type": "string",
                "enum": ["open", "closed", "pending"],
                "description": "Gate status: 'open' = downstream can execute, 'closed' = blocked, 'pending' = not yet evaluated",
            },
            "necessity_audit": {
                "type": "string",
                "description": "Update the counterfactual necessity analysis",
            },
            "add_audit_log": {
                "type": "object",
                "description": "Append an audit log entry (e.g. {'timestamp': '...', 'action': '...', 'result': '...'})",
            },
            "evidence_pointers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Replace fine-grained evidence pointers array",
            },
            "memory_path": {
                "type": "string",
                "description": "Path to per-node memory file",
            },
            "add_run_log": {
                "type": "object",
                "description": "Append a run log entry (e.g. {'timestamp': '...', 'step': '...', 'detail': '...'})",
            },
        },
        "required": ["task_id"],
    },
}

_TASK_GET_SCHEMA = {
    "name": "TaskGet",
    "description": "Retrieve a single task by ID. Returns full task details.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to retrieve",
            },
        },
        "required": ["task_id"],
    },
}

_TASK_LIST_SCHEMA = {
    "name": "TaskList",
    "description": (
        "List all tasks. Returns id, subject, status, owner, and pending blockers. "
        "Use this to review the current plan or find the next available task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_TASK_GATE_CHECK_SCHEMA = {
    "name": "TaskGateCheck",
    "description": (
        "Check if a task's gate conditions are satisfied (all blocked_by tasks have open gates). "
        "Call this BEFORE executing a task to verify upstream dependencies are validated. "
        "Returns whether execution is allowed and which gates are still closed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to check gate conditions for",
            },
        },
        "required": ["task_id"],
    },
}

_TASK_RETRY_SCHEMA = {
    "name": "TaskRetry",
    "description": (
        "Retry a failed task with failure context injected into the prompt. "
        "The framework will re-execute the task's LLM call with the previous output and failure issues "
        "included so the model can self-correct. Use this when a task fails verification. "
        "Returns the new output, verification result, and whether the retry succeeded."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the failed task to retry",
            },
            "actual_inputs": {
                "type": "object",
                "description": "The actual inputs that were used for the original execution",
            },
            "failed_output": {
                "type": "object",
                "description": "The output that failed verification",
            },
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of verification failure issues to fix",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for the LLM call (defaults to empty)",
            },
        },
        "required": ["task_id", "actual_inputs", "failed_output", "issues"],
    },
}

_TASK_DECOMPOSE_SCHEMA = {
    "name": "TaskDecompose",
    "description": (
        "Decompose a failed task into sub-tasks, execute each, and merge results. "
        "Use this when a retry also fails and the task is too complex for a single LLM call. "
        "The framework will ask the LLM to break the task into 2-4 sub-tasks, execute each, "
        "and merge their outputs. Respects max depth (default 2 levels)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the failed task to decompose",
            },
            "actual_inputs": {
                "type": "object",
                "description": "The actual inputs that were used for the original execution",
            },
            "failed_output": {
                "type": "object",
                "description": "The output that failed verification",
            },
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of verification failure issues",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for LLM calls (defaults to empty)",
            },
            "depth": {
                "type": "integer",
                "description": "Current recursion depth (default 0)",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum decomposition depth (default 2)",
            },
            "log_dir": {
                "type": "string",
                "description": "Directory to write evidence logs",
            },
        },
        "required": ["task_id", "actual_inputs", "failed_output", "issues"],
    },
}

_TASK_EXECUTE_RECOVERY_SCHEMA = {
    "name": "TaskExecuteRecovery",
    "description": (
        "Execute a task with the full recovery pipeline: direct attempt → retry with failure context → "
        "decompose into sub-tasks. This is the recommended way to execute a task node that may fail. "
        "It handles all recovery automatically and returns the best result. "
        "Automatically writes evidence logs (LLM prompt/response) to log_dir if specified."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to execute with recovery",
            },
            "actual_inputs": {
                "type": "object",
                "description": "Resolved inputs for this task",
            },
            "system_prompt": {
                "type": "string",
                "description": "System prompt for LLM calls (defaults to empty)",
            },
            "depth": {
                "type": "integer",
                "description": "Current recursion depth (default 0)",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum decomposition depth (default 2)",
            },
            "log_dir": {
                "type": "string",
                "description": "Directory to write evidence logs (e.g. 'e:/project/log'). If omitted, no logs are written.",
            },
        },
        "required": ["task_id", "actual_inputs"],
    },
}

_TASK_WRITE_MEMORY_SCHEMA = {
    "name": "TaskWriteMemory",
    "description": (
        "Write a module memory.md file from task data. "
        "Generates the full file programmatically with raw JSON for actual I/O — no LLM summarization. "
        "This ensures memory files contain verbatim data, not summaries."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The ID of the task to write memory for",
            },
            "output_dir": {
                "type": "string",
                "description": "Base output directory (e.g. 'e:/project/example1')",
            },
            "node_id": {
                "type": "string",
                "description": "Node identifier (e.g. 'node_1')",
            },
        },
        "required": ["task_id", "output_dir", "node_id"],
    },
}


# ── Evidence logging ──────────────────────────────────────────────────────────

def _make_log_callback(log_dir: str | None = None):
    """Create a log_callback that writes LLM call evidence to log_dir/."""
    if not log_dir:
        # Default: look for 'log/' relative to common output dirs
        for candidate in [Path.cwd() / "log", Path.cwd() / "example" / "example1" / "log"]:
            if candidate.parent.exists():
                log_dir = str(candidate)
                break
        else:
            log_dir = str(Path.cwd() / "log")

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    def _log(name: str, system_prompt: str, user_prompt: str, response: str, meta: dict):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{ts}.md"
        filepath = log_path / filename
        content = (
            f"# Evidence Log: {name}\n\n"
            f"**Timestamp**: {datetime.now().isoformat()}\n"
            f"**Model**: {meta.get('model', 'unknown')}\n"
            f"**Duration**: {meta.get('duration_s', 0)}s\n\n"
            f"---\n\n"
            f"## System Prompt\n\n```\n{system_prompt[:2000]}\n```\n\n"
            f"## User Prompt\n\n```\n{user_prompt[:5000]}\n```\n\n"
            f"## LLM Response\n\n```\n{response[:10000]}\n```\n\n"
            f"## Metadata\n\n```json\n{meta}\n```\n"
        )
        filepath.write_text(content, encoding="utf-8")
        # Also write a short version with just the key for evidence_pointers
        short_file = log_path / f"{name}.md"
        short_file.write_text(content, encoding="utf-8")

    return _log


# ── Implementations ────────────────────────────────────────────────────────────

def _task_create(
    subject: str,
    description: str,
    active_form: str = "",
    metadata: dict = None,
    input_spec: dict = None,
    output_spec: dict = None,
    audit_status: str = "",
    necessity_claim: str = "",
    verification_rule: str = "",
    acceptance_status: str = "",
    compressed_judgment: str = "",
    evidence_pointer: str = "",
    input_example: dict = None,
    output_example: dict = None,
    gate_condition: str = "",
    necessity_audit: str = "",
    evidence_pointers: list = None,
) -> str:
    task = create_task(
        subject,
        description,
        active_form=active_form,
        metadata=metadata,
        input_spec=input_spec,
        output_spec=output_spec,
        audit_status=audit_status,
        necessity_claim=necessity_claim,
        verification_rule=verification_rule,
        acceptance_status=acceptance_status,
        compressed_judgment=compressed_judgment,
        evidence_pointer=evidence_pointer,
        input_example=input_example,
        output_example=output_example,
        gate_condition=gate_condition,
        necessity_audit=necessity_audit,
        evidence_pointers=evidence_pointers,
    )
    return f"Task #{task.id} created: {task.subject}"


def _task_update(
    task_id: str,
    subject: str = None,
    description: str = None,
    status: str = None,
    active_form: str = None,
    owner: str = None,
    add_blocks: list = None,
    add_blocked_by: list = None,
    metadata: dict = None,
    input_spec: dict = None,
    output_spec: dict = None,
    audit_status: str = None,
    necessity_claim: str = None,
    verification_rule: str = None,
    acceptance_status: str = None,
    compressed_judgment: str = None,
    evidence_pointer: str = None,
    input_example: dict = None,
    output_example: dict = None,
    actual_input: dict = None,
    actual_output: dict = None,
    verification_result: str = None,
    gate_condition: str = None,
    gate_status: str = None,
    necessity_audit: str = None,
    add_audit_log: dict = None,
    evidence_pointers: list = None,
    memory_path: str = None,
    add_run_log: dict = None,
) -> str:
    # Handle deletion
    if status == "deleted":
        ok = delete_task(task_id)
        if ok:
            return f"Task #{task_id} deleted."
        return f"Error: task #{task_id} not found."

    task, updated_fields = update_task(
        task_id,
        subject=subject,
        description=description,
        status=status,
        active_form=active_form,
        owner=owner,
        add_blocks=add_blocks or [],
        add_blocked_by=add_blocked_by or [],
        metadata=metadata,
        input_spec=input_spec,
        output_spec=output_spec,
        audit_status=audit_status,
        necessity_claim=necessity_claim,
        verification_rule=verification_rule,
        acceptance_status=acceptance_status,
        compressed_judgment=compressed_judgment,
        evidence_pointer=evidence_pointer,
        input_example=input_example,
        output_example=output_example,
        actual_input=actual_input,
        actual_output=actual_output,
        verification_result=verification_result,
        gate_condition=gate_condition,
        gate_status=gate_status,
        necessity_audit=necessity_audit,
        add_audit_log=add_audit_log,
        evidence_pointers=evidence_pointers,
        memory_path=memory_path,
        add_run_log=add_run_log,
    )
    if task is None:
        return f"Error: task #{task_id} not found."
    if not updated_fields:
        return f"Task #{task_id}: no changes (fields already match)."
    return f"Task #{task_id} updated — changed: {', '.join(updated_fields)}."


def _task_get(task_id: str) -> str:
    task = get_task(task_id)
    if task is None:
        return f"Task #{task_id} not found."
    lines = [
        f"Task #{task.id}: {task.subject}",
        f"Status:      {task.status.value}",
        f"Description: {task.description}",
    ]
    if task.owner:
        lines.append(f"Owner:       {task.owner}")
    if task.active_form:
        lines.append(f"Active form: {task.active_form}")
    if task.blocked_by:
        lines.append(f"Blocked by:  #{', #'.join(task.blocked_by)}")
    if task.blocks:
        lines.append(f"Blocks:      #{', #'.join(task.blocks)}")
    if task.metadata:
        lines.append(f"Metadata:    {task.metadata}")
    if task.input_spec:
        lines.append(f"Input spec:  {task.input_spec}")
    if task.output_spec:
        lines.append(f"Output spec: {task.output_spec}")
    if task.audit_status:
        lines.append(f"Audit:       {task.audit_status}")
    if task.necessity_claim:
        lines.append(f"Necessity:   {task.necessity_claim}")
    if task.verification_rule:
        lines.append(f"Verify:      {task.verification_rule}")
    if task.acceptance_status:
        lines.append(f"Acceptance:  {task.acceptance_status}")
    if task.compressed_judgment:
        lines.append(f"Judgment:    {task.compressed_judgment}")
    if task.evidence_pointer:
        lines.append(f"Evidence:    {task.evidence_pointer}")
    if task.input_example:
        lines.append(f"In Example:  {task.input_example}")
    if task.output_example:
        lines.append(f"Out Example: {task.output_example}")
    if task.actual_input:
        lines.append(f"Actual In:\n```json\n{json.dumps(task.actual_input, indent=2, ensure_ascii=False)}\n```")
    if task.actual_output:
        lines.append(f"Actual Out:\n```json\n{json.dumps(task.actual_output, indent=2, ensure_ascii=False)}\n```")
    if task.verification_result:
        lines.append(f"Verify Res:  {task.verification_result}")
    if task.gate_condition:
        lines.append(f"Gate Cond:   {task.gate_condition}")
    if task.gate_status:
        lines.append(f"Gate Status: {task.gate_status}")
    if task.necessity_audit:
        lines.append(f"Necessity:   {task.necessity_audit}")
    if task.evidence_pointers:
        lines.append(f"Evidence[]:  {task.evidence_pointers}")
    if task.memory_path:
        lines.append(f"Memory:      {task.memory_path}")
    if task.audit_log:
        lines.append(f"Audit Log:   {len(task.audit_log)} entries")
    if task.run_log:
        lines.append(f"Run Log:     {len(task.run_log)} entries")
    lines.append(f"Created:     {task.created_at[:19]}")
    lines.append(f"Updated:     {task.updated_at[:19]}")
    return "\n".join(lines)


def _task_list() -> str:
    tasks = list_tasks()
    if not tasks:
        return "No tasks."
    resolved = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}
    lines = []
    for task in tasks:
        pending_blockers = [b for b in task.blocked_by if b not in resolved]
        owner_str   = f" ({task.owner})" if task.owner else ""
        blocked_str = f" [blocked by #{', #'.join(pending_blockers)}]" if pending_blockers else ""
        gate_str = f" [gate:{task.gate_status}]" if task.gate_condition else ""
        lines.append(
            f"#{task.id} [{task.status.value}] {task.status_icon()} "
            f"{task.subject}{owner_str}{blocked_str}{gate_str}"
        )
    return "\n".join(lines)


def _task_gate_check(task_id: str) -> str:
    can_execute, reason = check_gate_conditions(task_id)
    task = get_task(task_id)
    if task is None:
        return f"Task #{task_id} not found."
    status = "PASS" if can_execute else "BLOCKED"
    return f"Gate check for #{task_id}: {status}\n{reason}"


def _task_retry(
    task_id: str,
    actual_inputs: dict,
    failed_output: dict,
    issues: list,
    system_prompt: str = "",
) -> str:
    from .recovery import retry_task
    import os
    from cc_config import load_config

    config = load_config()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model

    if not system_prompt:
        system_prompt = "You are a precise task execution assistant."

    result = retry_task(
        task_id, actual_inputs, failed_output, issues,
        system_prompt, config,
    )

    if "error" in result:
        return f"Error: {result['error']}"

    v = result["verification"]
    status = "PASS" if v["passed"] else "FAIL"
    lines = [
        f"TaskRetry #{task_id}: {status}",
        f"Recovery: {result['recovery']}",
        f"Verification: {v['verification_result']}",
    ]
    if v["issues"]:
        for issue in v["issues"]:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


def _task_decompose(
    task_id: str,
    actual_inputs: dict,
    failed_output: dict,
    issues: list,
    system_prompt: str = "",
    depth: int = 0,
    max_depth: int = 2,
    log_dir: str = "",
) -> str:
    from .recovery import decompose_task
    import os
    from cc_config import load_config

    config = load_config()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model

    if not system_prompt:
        system_prompt = "You are a precise task execution assistant."

    log_callback = _make_log_callback(log_dir) if log_dir else None

    result = decompose_task(
        task_id, actual_inputs, failed_output, issues,
        system_prompt, config, depth, max_depth,
        log_callback=log_callback,
    )

    if "error" in result:
        return f"Error: {result['error']}"

    v = result["verification"]
    status = "PASS" if v["passed"] else "FAIL"
    lines = [
        f"TaskDecompose #{task_id}: {status}",
        f"Recovery: {result['recovery']}",
        f"Sub-tasks: {len(result.get('sub_tasks', []))}",
        f"Verification: {v['verification_result']}",
    ]
    for st in result.get("sub_tasks", []):
        st_status = "PASS" if st["passed"] else "FAIL"
        lines.append(f"  - {st['id']} ({st['name']}): {st_status}")
    if v["issues"]:
        for issue in v["issues"]:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


def _task_execute_recovery(
    task_id: str,
    actual_inputs: dict,
    system_prompt: str = "",
    depth: int = 0,
    max_depth: int = 2,
    log_dir: str = "",
) -> str:
    from .recovery import execute_with_recovery
    import os
    from cc_config import load_config

    config = load_config()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model

    if not system_prompt:
        system_prompt = "You are a precise task execution assistant."

    log_callback = _make_log_callback(log_dir) if log_dir else None

    try:
        result = execute_with_recovery(
            task_id, actual_inputs, system_prompt, config, depth, max_depth,
            log_callback=log_callback,
        )
    except Exception as e:
        import traceback
        return f"Error in execute_with_recovery: {e}\n{traceback.format_exc()}"

    if "error" in result:
        return f"Error: {result['error']}"

    v = result["verification"]
    status = "PASS" if v["passed"] else "FAIL"
    lines = [
        f"TaskExecuteRecovery #{task_id}: {status}",
        f"Recovery path: {result['recovery']}",
        f"Verification: {v['verification_result']}",
    ]
    if v["issues"]:
        for issue in v["issues"]:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


def _task_write_memory(task_id: str, output_dir: str, node_id: str) -> str:
    task = get_task(task_id)
    if task is None:
        return f"Task #{task_id} not found."

    modules_dir = Path(output_dir) / "modules" / node_id
    modules_dir.mkdir(parents=True, exist_ok=True)
    memory_path = modules_dir / "memory.md"

    # Necessity text
    necessity_text = task.necessity_audit or task.necessity_claim or "No necessity analysis available."

    # Evidence list
    if task.evidence_pointers:
        evidence_list = "\n".join(f"- `{ep}`" for ep in task.evidence_pointers)
    elif task.evidence_pointer:
        evidence_list = f"- `{task.evidence_pointer}`"
    else:
        evidence_list = "- No evidence pointers."

    # Build comparison table from output_spec keys vs actual_output keys
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

    # Build planned I/O section
    planned_input = json.dumps(task.input_spec, indent=2, ensure_ascii=False) if task.input_spec else "{}"
    planned_output = json.dumps(task.output_spec, indent=2, ensure_ascii=False) if task.output_spec else "{}"

    # Build actual I/O section — raw JSON, not summarized
    actual_input_json = json.dumps(task.actual_input, indent=2, ensure_ascii=False) if task.actual_input else "{}"
    actual_output_json = json.dumps(task.actual_output, indent=2, ensure_ascii=False) if task.actual_output else "{}"

    content = f"""# Module Memory: {node_id} — {task.subject}

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

## Actual I/O (from TaskGet)
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

    # Update task with memory_path
    update_task(task_id, memory_path=str(memory_path))

    return f"Memory written: {memory_path}"


# ── Registration ───────────────────────────────────────────────────────────────

def _register() -> None:
    defs = [
        ToolDef(
            name="TaskCreate",
            schema=_TASK_CREATE_SCHEMA,
            func=lambda p, c: _task_create(
                p["subject"],
                p["description"],
                p.get("active_form", ""),
                p.get("metadata"),
                p.get("input_spec"),
                p.get("output_spec"),
                p.get("audit_status", ""),
                p.get("necessity_claim", ""),
                p.get("verification_rule", ""),
                p.get("acceptance_status", ""),
                p.get("compressed_judgment", ""),
                p.get("evidence_pointer", ""),
                p.get("input_example"),
                p.get("output_example"),
                p.get("gate_condition", ""),
                p.get("necessity_audit", ""),
                p.get("evidence_pointers"),
            ),
            read_only=False,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskUpdate",
            schema=_TASK_UPDATE_SCHEMA,
            func=lambda p, c: _task_update(
                p["task_id"],
                subject=p.get("subject"),
                description=p.get("description"),
                status=p.get("status"),
                active_form=p.get("active_form"),
                owner=p.get("owner"),
                add_blocks=p.get("add_blocks"),
                add_blocked_by=p.get("add_blocked_by"),
                metadata=p.get("metadata"),
                input_spec=p.get("input_spec"),
                output_spec=p.get("output_spec"),
                audit_status=p.get("audit_status"),
                necessity_claim=p.get("necessity_claim"),
                verification_rule=p.get("verification_rule"),
                acceptance_status=p.get("acceptance_status"),
                compressed_judgment=p.get("compressed_judgment"),
                evidence_pointer=p.get("evidence_pointer"),
                input_example=p.get("input_example"),
                output_example=p.get("output_example"),
                actual_input=p.get("actual_input"),
                actual_output=p.get("actual_output"),
                verification_result=p.get("verification_result"),
                gate_condition=p.get("gate_condition"),
                gate_status=p.get("gate_status"),
                necessity_audit=p.get("necessity_audit"),
                add_audit_log=p.get("add_audit_log"),
                evidence_pointers=p.get("evidence_pointers"),
                memory_path=p.get("memory_path"),
                add_run_log=p.get("add_run_log"),
            ),
            read_only=False,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskGet",
            schema=_TASK_GET_SCHEMA,
            func=lambda p, c: _task_get(p["task_id"]),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskList",
            schema=_TASK_LIST_SCHEMA,
            func=lambda p, c: _task_list(),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskGateCheck",
            schema=_TASK_GATE_CHECK_SCHEMA,
            func=lambda p, c: _task_gate_check(p["task_id"]),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="TaskRetry",
            schema=_TASK_RETRY_SCHEMA,
            func=lambda p, c: _task_retry(
                p["task_id"],
                p.get("actual_inputs", {}),
                p.get("failed_output", {}),
                p.get("issues", []),
                p.get("system_prompt", ""),
            ),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="TaskDecompose",
            schema=_TASK_DECOMPOSE_SCHEMA,
            func=lambda p, c: _task_decompose(
                p["task_id"],
                p.get("actual_inputs", {}),
                p.get("failed_output", {}),
                p.get("issues", []),
                p.get("system_prompt", ""),
                p.get("depth", 0),
                p.get("max_depth", 2),
                p.get("log_dir", ""),
            ),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="TaskExecuteRecovery",
            schema=_TASK_EXECUTE_RECOVERY_SCHEMA,
            func=lambda p, c: _task_execute_recovery(
                p["task_id"],
                p.get("actual_inputs", {}),
                p.get("system_prompt", ""),
                p.get("depth", 0),
                p.get("max_depth", 2),
                p.get("log_dir", ""),
            ),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="TaskWriteMemory",
            schema=_TASK_WRITE_MEMORY_SCHEMA,
            func=lambda p, c: _task_write_memory(
                p["task_id"],
                p["output_dir"],
                p["node_id"],
            ),
            read_only=False,
            concurrent_safe=False,
        ),
    ]
    for td in defs:
        register_tool(td)


_register()
