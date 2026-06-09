"""Version comparison helper used before promotion."""
from __future__ import annotations

from typing import Any

from ..evaluation.compare_versions import compare_graph_versions


def compare_candidate_version(base_graph: dict[str, Any], candidate_graph: dict[str, Any]) -> dict[str, Any]:
    return compare_graph_versions(base_graph, candidate_graph)


__all__ = ["compare_candidate_version"]
