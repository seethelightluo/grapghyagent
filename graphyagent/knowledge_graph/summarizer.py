"""Knowledge item compression for node memory packets."""
from __future__ import annotations

from typing import Any


def summarize_items(items: list[dict[str, Any]], *, max_chars: int = 2400) -> str:
    parts = []
    remaining = max(0, int(max_chars))
    for item in items:
        summary = str(item.get("summary") or item.get("knowledge_id") or "")
        if not summary:
            continue
        prefix = f"- {item.get('knowledge_id')}: "
        line = prefix + summary
        if len(line) > remaining:
            line = line[:remaining]
        if not line:
            break
        parts.append(line)
        remaining -= len(line) + 1
        if remaining <= 0:
            break
    return "\n".join(parts)


__all__ = ["summarize_items"]
