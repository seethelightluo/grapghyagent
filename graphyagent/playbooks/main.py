"""Main interface for playbooks module commands."""
from __future__ import annotations

from typing import Any

from .matcher import match_playbooks
from .serializer import promote_reusable_subgraphs, serialize_subgraph


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("playbooks", target_type)


__all__ = ["commands", "match_playbooks", "serialize_subgraph"]
