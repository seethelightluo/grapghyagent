"""Main interface for core graph configuration primitives."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_graph_config
from .schema import GRAPH_CONFIG_SCHEMA


def load(config_path: str | Path) -> Any:
    return load_graph_config(config_path)


def schema() -> dict[str, Any]:
    return GRAPH_CONFIG_SCHEMA


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("core", target_type)


__all__ = ["commands", "load", "load_graph_config", "schema"]
