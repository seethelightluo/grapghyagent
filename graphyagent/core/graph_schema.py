"""Graph schema helpers for versioned workflow structures."""
from __future__ import annotations

from typing import Any


def graph_edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_edge(source: Any, target: Any, raw: dict[str, Any] | None = None) -> None:
        source_id = str(source or "")
        target_id = str(target or "")
        if not source_id or not target_id:
            return
        key = (source_id, target_id)
        if key in seen:
            return
        seen.add(key)
        raw_edge = dict(raw or {})
        edge_id = str(raw_edge.get("edge_id") or raw_edge.get("id") or f"{source_id}->{target_id}")
        edge_type = str(raw_edge.get("edge_type") or raw_edge.get("type") or "data")
        normalized = {
            **raw_edge,
            "edge_id": edge_id,
            "source": source_id,
            "target": target_id,
            "source_node_id": source_id,
            "target_node_id": target_id,
            "edge_type": edge_type,
            "required": bool(raw_edge.get("required", True)),
        }
        edges.append(normalized)

    for raw_edge in graph.get("edges") or []:
        if not isinstance(raw_edge, dict):
            continue
        source = (
            raw_edge.get("source_node_id")
            or raw_edge.get("source")
            or raw_edge.get("from_node_id")
            or raw_edge.get("from")
        )
        target = (
            raw_edge.get("target_node_id")
            or raw_edge.get("target")
            or raw_edge.get("to_node_id")
            or raw_edge.get("to")
        )
        add_edge(source, target, raw_edge)

    for node in graph.get("nodes") or []:
        target = str(node.get("id") or node.get("node_id") or "")
        if not target:
            continue
        for source in _node_dependencies(node):
            add_edge(source, target)
    return edges


def _node_dependencies(node: dict[str, Any]) -> list[str]:
    deps = node.get("depends_on")
    if deps is None:
        deps = node.get("deps")
    if isinstance(deps, str):
        return [deps]
    if isinstance(deps, list):
        return [str(item) for item in deps if str(item)]
    return []


__all__ = ["graph_edges"]
