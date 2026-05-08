"""Thread-safe task store: in-memory dict persisted to .cheetahclaws/tasks.json."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import Task, TaskStatus

_lock = threading.Lock()

# Tasks are keyed by ID, stored per session in <cwd>/.cheetahclaws/tasks.json
# The store is kept in memory; we reload from disk on first access.

_tasks: dict[str, Task] = {}
_loaded = False


# ── persistence ───────────────────────────────────────────────────────────────

def _tasks_file() -> Path:
    return Path.cwd() / ".cheetahclaws" / "tasks.json"


def _load() -> None:
    global _loaded
    if _loaded:
        return
    f = _tasks_file()
    if f.exists():
        try:
            data = json.loads(f.read_text())
            for item in data.get("tasks", []):
                t = Task.from_dict(item)
                _tasks[t.id] = t
        except Exception:
            pass
    _loaded = True


def _save() -> None:
    f = _tasks_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"tasks": [t.to_dict() for t in _tasks.values()]}
    f.write_text(json.dumps(data, indent=2))


def _next_id() -> str:
    """Generate a short sequential numeric ID."""
    if not _tasks:
        return "1"
    max_id = max((int(k) for k in _tasks if k.isdigit()), default=0)
    return str(max_id + 1)


# ── public API ────────────────────────────────────────────────────────────────

def create_task(
    subject: str,
    description: str,
    active_form: str = "",
    metadata: dict[str, Any] | None = None,
    input_spec: dict[str, Any] | None = None,
    output_spec: dict[str, Any] | None = None,
    audit_status: str = "",
    necessity_claim: str = "",
    verification_rule: str = "",
    acceptance_status: str = "",
    compressed_judgment: str = "",
    evidence_pointer: str = "",
    input_example: dict[str, Any] | None = None,
    output_example: dict[str, Any] | None = None,
    gate_condition: str = "",
    necessity_audit: str = "",
    evidence_pointers: list[str] | None = None,
    blocked_by: list[str] | None = None,
) -> Task:
    with _lock:
        _load()
        task = Task(
            id=_next_id(),
            subject=subject,
            description=description,
            active_form=active_form,
            metadata=metadata or {},
            input_spec=input_spec or {},
            output_spec=output_spec or {},
            audit_status=audit_status or "",
            necessity_claim=necessity_claim or "",
            verification_rule=verification_rule or "",
            acceptance_status=acceptance_status or "",
            compressed_judgment=compressed_judgment or "",
            evidence_pointer=evidence_pointer or "",
            input_example=input_example or {},
            output_example=output_example or {},
            gate_condition=gate_condition or "",
            gate_status="pending" if gate_condition else "",
            necessity_audit=necessity_audit or "",
            evidence_pointers=evidence_pointers or [],
        )
        _tasks[task.id] = task
        # Wire blocked_by edges after creation
        if blocked_by:
            for blocker_id in blocked_by:
                blocker = _tasks.get(str(blocker_id))
                if blocker:
                    task.blocked_by.append(str(blocker_id))
                    if str(task.id) not in blocker.blocks:
                        blocker.blocks.append(str(task.id))
        _save()
        return task


def get_task(task_id: str) -> Task | None:
    with _lock:
        _load()
        return _tasks.get(str(task_id))


def list_tasks() -> list[Task]:
    with _lock:
        _load()
        return list(_tasks.values())


def update_task(
    task_id: str,
    subject: str | None = None,
    description: str | None = None,
    status: str | None = None,
    active_form: str | None = None,
    owner: str | None = None,
    add_blocks: list[str] | None = None,
    add_blocked_by: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    input_spec: dict[str, Any] | None = None,
    output_spec: dict[str, Any] | None = None,
    audit_status: str | None = None,
    necessity_claim: str | None = None,
    verification_rule: str | None = None,
    acceptance_status: str | None = None,
    compressed_judgment: str | None = None,
    evidence_pointer: str | None = None,
    input_example: dict[str, Any] | None = None,
    output_example: dict[str, Any] | None = None,
    actual_input: dict[str, Any] | None = None,
    actual_output: dict[str, Any] | None = None,
    verification_result: str | None = None,
    gate_condition: str | None = None,
    gate_status: str | None = None,
    necessity_audit: str | None = None,
    add_audit_log: dict[str, Any] | None = None,
    evidence_pointers: list[str] | None = None,
    memory_path: str | None = None,
    add_run_log: dict[str, Any] | None = None,
    sub_graph: dict[str, Any] | None = None,
) -> tuple[Task | None, list[str]]:
    """Update a task. Returns (updated_task, list_of_updated_fields)."""
    with _lock:
        _load()
        task = _tasks.get(str(task_id))
        if task is None:
            return None, []

        updated_fields: list[str] = []

        if subject is not None and subject != task.subject:
            task.subject = subject
            updated_fields.append("subject")

        if description is not None and description != task.description:
            task.description = description
            updated_fields.append("description")

        if active_form is not None and active_form != task.active_form:
            task.active_form = active_form
            updated_fields.append("active_form")

        if owner is not None and owner != task.owner:
            task.owner = owner
            updated_fields.append("owner")

        if status is not None:
            try:
                new_status = TaskStatus(status)
            except ValueError:
                new_status = None
            if new_status is not None and new_status != task.status:
                task.status = new_status
                updated_fields.append("status")

        if metadata is not None:
            for k, v in metadata.items():
                if v is None:
                    task.metadata.pop(k, None)
                else:
                    task.metadata[k] = v
            updated_fields.append("metadata")

        if input_spec is not None and input_spec != task.input_spec:
            task.input_spec = input_spec
            updated_fields.append("input_spec")

        if output_spec is not None and output_spec != task.output_spec:
            task.output_spec = output_spec
            updated_fields.append("output_spec")

        if audit_status is not None and audit_status != task.audit_status:
            task.audit_status = audit_status
            updated_fields.append("audit_status")

        if necessity_claim is not None and necessity_claim != task.necessity_claim:
            task.necessity_claim = necessity_claim
            updated_fields.append("necessity_claim")

        if verification_rule is not None and verification_rule != task.verification_rule:
            task.verification_rule = verification_rule
            updated_fields.append("verification_rule")

        if acceptance_status is not None and acceptance_status != task.acceptance_status:
            task.acceptance_status = acceptance_status
            updated_fields.append("acceptance_status")

        if compressed_judgment is not None and compressed_judgment != task.compressed_judgment:
            task.compressed_judgment = compressed_judgment
            updated_fields.append("compressed_judgment")

        if evidence_pointer is not None and evidence_pointer != task.evidence_pointer:
            task.evidence_pointer = evidence_pointer
            updated_fields.append("evidence_pointer")

        # ── verifiable graph extensions ──────────────────────────────────────

        if input_example is not None and input_example != task.input_example:
            task.input_example = input_example
            updated_fields.append("input_example")

        if output_example is not None and output_example != task.output_example:
            task.output_example = output_example
            updated_fields.append("output_example")

        if actual_input is not None and actual_input != task.actual_input:
            task.actual_input = actual_input
            updated_fields.append("actual_input")

        if actual_output is not None and actual_output != task.actual_output:
            task.actual_output = actual_output
            updated_fields.append("actual_output")

        if verification_result is not None and verification_result != task.verification_result:
            task.verification_result = verification_result
            updated_fields.append("verification_result")

        if gate_condition is not None and gate_condition != task.gate_condition:
            task.gate_condition = gate_condition
            updated_fields.append("gate_condition")

        if gate_status is not None and gate_status != task.gate_status:
            task.gate_status = gate_status
            updated_fields.append("gate_status")

        if necessity_audit is not None and necessity_audit != task.necessity_audit:
            task.necessity_audit = necessity_audit
            updated_fields.append("necessity_audit")

        if add_audit_log is not None:
            task.audit_log.append(add_audit_log)
            updated_fields.append("audit_log")

        if evidence_pointers is not None and evidence_pointers != task.evidence_pointers:
            task.evidence_pointers = evidence_pointers
            updated_fields.append("evidence_pointers")

        if memory_path is not None and memory_path != task.memory_path:
            task.memory_path = memory_path
            updated_fields.append("memory_path")

        if add_run_log is not None:
            task.run_log.append(add_run_log)
            updated_fields.append("run_log")

        if sub_graph is not None and sub_graph != task.sub_graph:
            task.sub_graph = sub_graph
            updated_fields.append("sub_graph")

        if add_blocks:
            new_blocks = [b for b in add_blocks if b not in task.blocks]
            if new_blocks:
                task.blocks.extend(new_blocks)
                # Also register the reverse edge on the target tasks
                for b_id in new_blocks:
                    target = _tasks.get(str(b_id))
                    if target and str(task_id) not in target.blocked_by:
                        target.blocked_by.append(str(task_id))
                updated_fields.append("blocks")

        if add_blocked_by:
            new_bb = [b for b in add_blocked_by if b not in task.blocked_by]
            if new_bb:
                task.blocked_by.extend(new_bb)
                # Also register the reverse edge
                for blocker_id in new_bb:
                    blocker = _tasks.get(str(blocker_id))
                    if blocker and str(task_id) not in blocker.blocks:
                        blocker.blocks.append(str(task_id))
                updated_fields.append("blocked_by")

        if updated_fields:
            task.updated_at = datetime.now().isoformat()
            _save()

        return task, updated_fields


def delete_task(task_id: str) -> bool:
    with _lock:
        _load()
        task_id = str(task_id)
        if task_id not in _tasks:
            return False
        del _tasks[task_id]
        _save()
        return True


def clear_all_tasks() -> None:
    """Remove all tasks (used in tests)."""
    with _lock:
        _tasks.clear()
        _save()


def reload_from_disk() -> None:
    """Force reload from disk (used in tests)."""
    global _loaded
    with _lock:
        _tasks.clear()
        _loaded = False
        _load()


def check_gate_conditions(task_id: str) -> tuple[bool, str]:
    """Check if all blocked_by tasks have open gate_status.

    Returns (can_execute, reason).
    """
    with _lock:
        _load()
        task = _tasks.get(str(task_id))
        if task is None:
            return False, f"Task #{task_id} not found."
        if not task.blocked_by:
            return True, "No blockers."
        closed_gates = []
        for blocker_id in task.blocked_by:
            blocker = _tasks.get(str(blocker_id))
            if blocker is None:
                continue
            if blocker.gate_condition and blocker.gate_status != "open":
                closed_gates.append(f"#{blocker_id}({blocker.gate_status or 'pending'})")
        if closed_gates:
            return False, f"Gate conditions not met: {', '.join(closed_gates)}"
        return True, "All gate conditions satisfied."
