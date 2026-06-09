"""Offline optimizer schema primitives."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .types import utc_now


@dataclass
class EdgeUtility:
    edge_id: str
    source_node_id: str
    target_node_id: str
    utility: float
    success_assoc: float = 0.0
    useful_rate: float = 0.0
    risk_rate: float = 0.0
    cost_contribution: float = 0.0
    evidence_run_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "utility": round(float(self.utility), 6),
            "success_assoc": round(float(self.success_assoc), 6),
            "useful_rate": round(float(self.useful_rate), 6),
            "risk_rate": round(float(self.risk_rate), 6),
            "cost_contribution": round(float(self.cost_contribution), 6),
            "evidence_run_count": int(self.evidence_run_count),
        }


@dataclass
class OptimizerSuggestion:
    suggestion_id: str
    action: str
    target_type: str
    target_id: str
    reason: str
    confidence: float = 0.5
    created_at: str = field(default_factory=utc_now)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "reason": self.reason,
            "confidence": round(float(self.confidence), 6),
            "created_at": self.created_at,
            "evidence": deepcopy(self.evidence),
        }


__all__ = ["EdgeUtility", "OptimizerSuggestion"]
