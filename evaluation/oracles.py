"""Evaluation oracle helpers."""
from __future__ import annotations

from typing import Any


def deterministic_run_oracle(run: dict[str, Any]) -> dict[str, Any]:
    success = run.get("status") == "success"
    return {
        "success": success,
        "score": 1.0 if success else 0.0,
        "reason": "GraphRun status is success" if success else str(run.get("error") or "GraphRun did not succeed"),
    }


__all__ = ["deterministic_run_oracle"]
