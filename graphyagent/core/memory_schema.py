"""Node memory packet schema for bounded v0.5 context."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .types import utc_now


@dataclass
class NodeMemoryPacket:
    packet_id: str
    project_id: str
    graph_id: str
    node_id: str
    node_goal: str
    node_purpose: str
    node_role: str = ""
    graph_run_id: str | None = None
    node_run_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    required_upstream_outputs: list[dict[str, Any]] = field(default_factory=list)
    optional_upstream_outputs: list[dict[str, Any]] = field(default_factory=list)
    background_summary: str = ""
    evidence_candidates: list[dict[str, Any]] = field(default_factory=list)
    unresolved_evidence_gaps: list[str] = field(default_factory=list)
    prohibited_assumptions: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    confidence_by_requirement: dict[str, Any] = field(default_factory=dict)
    must_verify_before_output: list[str] = field(default_factory=list)
    tool_usage_hints: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    supplied_knowledge_ids: list[str] = field(default_factory=list)
    lineage_context: dict[str, Any] = field(default_factory=dict)
    context_sources: dict[str, Any] = field(default_factory=dict)
    packet_hash: str | None = None
    retrieval_policy_version: str = "lineage-context-v2"
    budget: dict[str, Any] = field(default_factory=dict)
    usage_log: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "graphyagent.node_memory_packet.v2",
            "packet_id": self.packet_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "graph_run_id": self.graph_run_id,
            "node_run_id": self.node_run_id,
            "created_at": self.created_at,
            "node_goal": self.node_goal,
            "node_purpose": self.node_purpose,
            "node_role": self.node_role,
            "required_upstream_outputs": deepcopy(self.required_upstream_outputs),
            "optional_upstream_outputs": deepcopy(self.optional_upstream_outputs),
            "background_summary": self.background_summary,
            "evidence_candidates": deepcopy(self.evidence_candidates),
            "unresolved_evidence_gaps": list(self.unresolved_evidence_gaps),
            "prohibited_assumptions": list(self.prohibited_assumptions),
            "known_facts": list(self.known_facts),
            "missing_requirements": list(self.missing_requirements),
            "confidence_by_requirement": deepcopy(self.confidence_by_requirement),
            "must_verify_before_output": list(self.must_verify_before_output),
            "tool_usage_hints": list(self.tool_usage_hints),
            "stop_conditions": list(self.stop_conditions),
            "supplied_knowledge_ids": list(self.supplied_knowledge_ids),
            "lineage_context": deepcopy(self.lineage_context),
            "context_sources": deepcopy(self.context_sources),
            "packet_hash": self.packet_hash,
            "retrieval_policy_version": self.retrieval_policy_version,
            "budget": deepcopy(self.budget),
            "usage_log": deepcopy(self.usage_log),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeMemoryPacket":
        return cls(
            packet_id=str(data["packet_id"]),
            project_id=str(data.get("project_id") or "runtime"),
            graph_id=str(data.get("graph_id") or "graph"),
            node_id=str(data.get("node_id") or "node"),
            graph_run_id=data.get("graph_run_id"),
            node_run_id=data.get("node_run_id"),
            created_at=str(data.get("created_at") or utc_now()),
            node_goal=str(data.get("node_goal") or ""),
            node_purpose=str(data.get("node_purpose") or ""),
            node_role=str(data.get("node_role") or ""),
            required_upstream_outputs=list(data.get("required_upstream_outputs") or []),
            optional_upstream_outputs=list(data.get("optional_upstream_outputs") or []),
            background_summary=str(data.get("background_summary") or ""),
            evidence_candidates=list(data.get("evidence_candidates") or []),
            unresolved_evidence_gaps=[str(item) for item in (data.get("unresolved_evidence_gaps") or [])],
            prohibited_assumptions=[str(item) for item in (data.get("prohibited_assumptions") or [])],
            known_facts=[str(item) for item in (data.get("known_facts") or [])],
            missing_requirements=[str(item) for item in (data.get("missing_requirements") or [])],
            confidence_by_requirement=dict(data.get("confidence_by_requirement") or {}),
            must_verify_before_output=[str(item) for item in (data.get("must_verify_before_output") or [])],
            tool_usage_hints=[str(item) for item in (data.get("tool_usage_hints") or [])],
            stop_conditions=[str(item) for item in (data.get("stop_conditions") or [])],
            supplied_knowledge_ids=[str(item) for item in (data.get("supplied_knowledge_ids") or [])],
            lineage_context=dict(data.get("lineage_context") or {}),
            context_sources=dict(data.get("context_sources") or {}),
            packet_hash=data.get("packet_hash"),
            retrieval_policy_version=str(data.get("retrieval_policy_version") or "lineage-context-v2"),
            budget=dict(data.get("budget") or {}),
            usage_log=dict(data.get("usage_log") or {}),
        )


__all__ = ["NodeMemoryPacket"]
