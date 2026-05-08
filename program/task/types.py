"""Task system types: Task dataclass, TaskStatus enum."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


VALID_STATUSES = {s.value for s in TaskStatus}


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    active_form: str = ""          # e.g. "Running tests"
    owner: str = ""
    blocks: list[str] = field(default_factory=list)      # IDs this task blocks
    blocked_by: list[str] = field(default_factory=list)  # IDs that block this task
    metadata: dict[str, Any] = field(default_factory=dict)
    input_spec: dict[str, Any] = field(default_factory=dict)
    output_spec: dict[str, Any] = field(default_factory=dict)
    audit_status: str = ""
    necessity_claim: str = ""
    verification_rule: str = ""
    acceptance_status: str = ""
    compressed_judgment: str = ""
    evidence_pointer: str = ""

    # ── verifiable graph extensions ─────────────────────────────────────────
    input_example: dict[str, Any] = field(default_factory=dict)
    output_example: dict[str, Any] = field(default_factory=dict)
    actual_input: dict[str, Any] = field(default_factory=dict)
    actual_output: dict[str, Any] = field(default_factory=dict)
    verification_result: str = ""
    gate_condition: str = ""
    gate_status: str = ""           # "open" | "closed" | "pending"
    necessity_audit: str = ""       # counterfactual analysis
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    evidence_pointers: list[str] = field(default_factory=list)
    memory_path: str = ""           # per-node memory file path
    run_log: list[dict[str, Any]] = field(default_factory=list)
    sub_graph: dict[str, Any] = field(default_factory=dict)

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # ── serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "subject":      self.subject,
            "description":  self.description,
            "status":       self.status.value if isinstance(self.status, TaskStatus) else self.status,
            "active_form":  self.active_form,
            "owner":        self.owner,
            "blocks":       self.blocks,
            "blocked_by":   self.blocked_by,
            "metadata":     self.metadata,
            "input_spec":   self.input_spec,
            "output_spec":  self.output_spec,
            "audit_status": self.audit_status,
            "necessity_claim": self.necessity_claim,
            "verification_rule": self.verification_rule,
            "acceptance_status": self.acceptance_status,
            "compressed_judgment": self.compressed_judgment,
            "evidence_pointer": self.evidence_pointer,
            "input_example":    self.input_example,
            "output_example":   self.output_example,
            "actual_input":     self.actual_input,
            "actual_output":    self.actual_output,
            "verification_result": self.verification_result,
            "gate_condition":   self.gate_condition,
            "gate_status":      self.gate_status,
            "necessity_audit":  self.necessity_audit,
            "audit_log":        self.audit_log,
            "evidence_pointers": self.evidence_pointers,
            "memory_path":      self.memory_path,
            "run_log":          self.run_log,
            "sub_graph":        self.sub_graph,
            "created_at":   self.created_at,
            "updated_at":   self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        status_raw = data.get("status", "pending")
        try:
            status = TaskStatus(status_raw)
        except ValueError:
            status = TaskStatus.PENDING
        return cls(
            id=data["id"],
            subject=data.get("subject", ""),
            description=data.get("description", ""),
            status=status,
            active_form=data.get("active_form", ""),
            owner=data.get("owner", ""),
            blocks=data.get("blocks", []),
            blocked_by=data.get("blocked_by", []),
            metadata=data.get("metadata", {}),
            input_spec=data.get("input_spec", {}),
            output_spec=data.get("output_spec", {}),
            audit_status=data.get("audit_status", ""),
            necessity_claim=data.get("necessity_claim", ""),
            verification_rule=data.get("verification_rule", ""),
            acceptance_status=data.get("acceptance_status", ""),
            compressed_judgment=data.get("compressed_judgment", ""),
            evidence_pointer=data.get("evidence_pointer", ""),
            input_example=data.get("input_example", {}),
            output_example=data.get("output_example", {}),
            actual_input=data.get("actual_input", {}),
            actual_output=data.get("actual_output", {}),
            verification_result=data.get("verification_result", ""),
            gate_condition=data.get("gate_condition", ""),
            gate_status=data.get("gate_status", ""),
            necessity_audit=data.get("necessity_audit", ""),
            audit_log=data.get("audit_log", []),
            evidence_pointers=data.get("evidence_pointers", []),
            memory_path=data.get("memory_path", ""),
            run_log=data.get("run_log", []),
            sub_graph=data.get("sub_graph", {}),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    # ── display ────────────────────────────────────────────────────────────────

    def status_icon(self) -> str:
        return {
            TaskStatus.PENDING:     "○",
            TaskStatus.IN_PROGRESS: "●",
            TaskStatus.COMPLETED:   "✓",
            TaskStatus.CANCELLED:   "✗",
        }.get(self.status, "?")

    def one_line(self, resolved_ids: set[str] | None = None) -> str:
        owner_str = f" ({self.owner})" if self.owner else ""
        pending_blockers = [
            b for b in self.blocked_by
            if resolved_ids is None or b not in resolved_ids
        ]
        blocked_str = (
            f" [blocked by #{', #'.join(pending_blockers)}]"
            if pending_blockers else ""
        )
        return f"#{self.id} [{self.status.value}] {self.status_icon()} {self.subject}{owner_str}{blocked_str}"
