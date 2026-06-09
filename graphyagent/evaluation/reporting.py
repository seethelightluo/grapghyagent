"""Evaluation report rendering."""
from __future__ import annotations

import json
from typing import Any


def render_evaluation_report(comparison: dict[str, Any]) -> str:
    return "\n".join([
        "# Graph Version Evaluation",
        "",
        f"Promotion recommendation: {comparison.get('promotion_recommendation')}",
        "",
        "```json",
        json.dumps(comparison, indent=2, ensure_ascii=False),
        "```",
    ])


__all__ = ["render_evaluation_report"]
