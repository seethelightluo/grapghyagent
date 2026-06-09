"""Task set loading for offline evaluation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_task_set(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("task set must be a JSON object")
    data.setdefault("tasks", [])
    return data


__all__ = ["load_task_set"]
