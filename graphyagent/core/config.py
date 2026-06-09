"""Graph configuration loading."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import GraphConfig


def normalize_graph_config_data(data: dict[str, Any]) -> dict[str, Any]:
    """Accept raw graph configs and Windows template wrappers."""
    graph = data.get("graph")
    if isinstance(graph, dict) and not data.get("nodes"):
        normalized = dict(graph)
        metadata = dict(normalized.get("metadata") or {})
        template_meta = dict(metadata.get("template") or {})
        if data.get("name") and not template_meta.get("name"):
            template_meta["name"] = data["name"]
        if template_meta:
            metadata["template"] = template_meta
            normalized["metadata"] = metadata
        return normalized
    return data


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "YAML graph configs require PyYAML; use JSON or install pyyaml."
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"graph config must load to an object: {path}")
    return data


def load_graph_config(path: str | Path) -> GraphConfig:
    config_path = Path(path).expanduser().resolve()
    suffix = config_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        raw = _load_yaml(config_path)
    else:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"graph config must load to an object: {config_path}")
    return GraphConfig.from_dict(normalize_graph_config_data(raw))
