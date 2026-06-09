"""Run-level v0.5 trace schema helpers."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunMetrics:
    tokens: int = 0
    latency_ms: int = 0
    tool_calls: int = 0
    external_retrieval_count: int = 0
    quality_score: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "tool_calls": self.tool_calls,
            "external_retrieval_count": self.external_retrieval_count,
            "quality_score": self.quality_score,
            "extra": deepcopy(self.extra),
        }


__all__ = ["RunMetrics"]
