"""Knowledge graph schemas used by the v0.5 context engine."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .types import utc_now


@dataclass
class KnowledgeNode:
    knowledge_id: str
    knowledge_type: str
    source: str
    project_scope: str | None = None
    graph_scope: str | None = None
    created_from_run_id: str | None = None
    content_locator: str | None = None
    summary: str = ""
    structured_tags: list[str] = field(default_factory=list)
    reliability_score: float = 1.0
    freshness_score: float = 1.0
    access_policy: str = "internal"
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "knowledge_type": self.knowledge_type,
            "source": self.source,
            "project_scope": self.project_scope,
            "graph_scope": self.graph_scope,
            "created_from_run_id": self.created_from_run_id,
            "content_locator": self.content_locator,
            "summary": self.summary,
            "structured_tags": list(self.structured_tags),
            "reliability_score": float(self.reliability_score),
            "freshness_score": float(self.freshness_score),
            "access_policy": self.access_policy,
            "created_at": self.created_at,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeNode":
        return cls(
            knowledge_id=str(data["knowledge_id"]),
            knowledge_type=str(data.get("knowledge_type") or "note"),
            source=str(data.get("source") or "unknown"),
            project_scope=data.get("project_scope"),
            graph_scope=data.get("graph_scope"),
            created_from_run_id=data.get("created_from_run_id"),
            content_locator=data.get("content_locator"),
            summary=str(data.get("summary") or ""),
            structured_tags=[str(item) for item in (data.get("structured_tags") or [])],
            reliability_score=float(data.get("reliability_score", 1.0)),
            freshness_score=float(data.get("freshness_score", 1.0)),
            access_policy=str(data.get("access_policy") or "internal"),
            created_at=str(data.get("created_at") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class KnowledgeEdge:
    source_id: str
    target_id: str
    relation_type: str
    strength: float = 1.0
    created_by: str = "system"
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def edge_id(self) -> str:
        return f"{self.source_id}->{self.relation_type}->{self.target_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "strength": float(self.strength),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "metadata": deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeEdge":
        return cls(
            source_id=str(data.get("source_id") or ""),
            target_id=str(data.get("target_id") or ""),
            relation_type=str(data.get("relation_type") or "related_to"),
            strength=float(data.get("strength", 1.0)),
            created_by=str(data.get("created_by") or "system"),
            created_at=str(data.get("created_at") or utc_now()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class KnowledgeView:
    project_id: str
    graph_id: str
    node_id: str
    created_at: str = field(default_factory=utc_now)
    background_items: list[dict[str, Any]] = field(default_factory=list)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    quarantined_items: list[dict[str, Any]] = field(default_factory=list)
    candidate_count: int = 0
    scoring_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "graphyagent.knowledge_view.v1",
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "created_at": self.created_at,
            "background_items": deepcopy(self.background_items),
            "evidence_items": deepcopy(self.evidence_items),
            "quarantined_items": deepcopy(self.quarantined_items),
            "candidate_count": self.candidate_count,
            "scoring_policy": deepcopy(self.scoring_policy),
        }


__all__ = ["KnowledgeEdge", "KnowledgeNode", "KnowledgeView"]
