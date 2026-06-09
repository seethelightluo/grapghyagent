"""Shared enum-like constants for GraphyAgent v0.5."""
from __future__ import annotations

NODE_TYPES = (
    "ingest",
    "parse",
    "summarize",
    "classify",
    "retrieve_internal",
    "retrieve_external",
    "analyze",
    "code_execute",
    "data_audit",
    "node_audit",
    "train",
    "evaluate",
    "report",
    "synthesize",
    "human_review",
    "graph_reflection_proxy",
)

EDGE_TYPES = ("data", "control", "evidence", "fallback", "speculative")

KNOWLEDGE_TYPES = (
    "file",
    "file_chunk",
    "schema",
    "trace_summary",
    "audit_result",
    "external_document",
    "playbook",
    "workflow_node",
    "graph_run",
    "node_run",
)

REFLECTION_LABELS = (
    "useful",
    "unused",
    "critical",
    "risky",
    "misleading",
    "insufficient",
)

KNOWLEDGE_CARRY_POLICIES = (
    "none",
    "summary_only",
    "critical_only",
    "all_evidence",
    "all_background_and_evidence",
)

__all__ = [
    "EDGE_TYPES",
    "KNOWLEDGE_CARRY_POLICIES",
    "KNOWLEDGE_TYPES",
    "NODE_TYPES",
    "REFLECTION_LABELS",
]
