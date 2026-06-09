"""Policy-level optimizer checks."""
from __future__ import annotations

from typing import Any


def promotion_gate(analysis: dict[str, Any]) -> dict[str, Any]:
    suggestions = analysis.get("suggestions") or []
    risky = [
        item for item in suggestions
        if item.get("action") == "soft_deprecate" and float(item.get("confidence", 0.0)) < 0.55
    ]
    return {
        "can_promote": not risky,
        "risk_count": len(risky),
        "suggestion_count": len(suggestions),
        "reason": "all optimizer suggestions have sufficient confidence" if not risky else "low-confidence deprecation suggestions require review",
    }


__all__ = ["promotion_gate"]
