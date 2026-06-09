"""Graph-native evaluation metrics."""
from __future__ import annotations

from typing import Any

from ..core.graph_schema import graph_edges


def graph_metrics(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") or []
    edges = graph_edges(graph)
    output_nodes = graph.get("output_nodes") or []
    incoming = _incoming_by_node(graph)
    backbone_edges = 0
    fallback_edges = 0
    for node in nodes:
        policies = ((node.get("metadata") or {}).get("edge_policies") or {})
        for policy in policies.values():
            if policy.get("priority") == "backbone":
                backbone_edges += 1
            if policy.get("priority") == "fallback" or policy.get("soft_deprecated"):
                fallback_edges += 1
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "output_node_count": len(output_nodes),
        "root_count": sum(
            1
            for node in nodes
            if not incoming.get(str(node.get("id") or node.get("node_id") or ""))
        ),
        "estimated_path_length": _estimated_path_length(graph),
        "backbone_edge_count": backbone_edges,
        "fallback_edge_count": fallback_edges,
        "llm_node_count": sum(
            1
            for node in nodes
            if ((node.get("executor") or node.get("runner") or {}).get("type") == "llm")
        ),
        "external_retrieval_node_count": sum(1 for node in nodes if str(node.get("task_type") or "") == "retrieve_external"),
    }


def _estimated_path_length(graph: dict[str, Any]) -> int:
    nodes = {
        str(node.get("id") or node.get("node_id")): node
        for node in graph.get("nodes") or []
        if node.get("id") or node.get("node_id")
    }
    incoming = _incoming_by_node(graph)
    memo: dict[str, int] = {}

    def depth(node_id: str) -> int:
        if node_id in memo:
            return memo[node_id]
        deps = [str(dep) for dep in incoming.get(node_id, []) if str(dep) in nodes]
        memo[node_id] = 1 + (max((depth(dep) for dep in deps), default=0))
        return memo[node_id]

    outputs = [str(item) for item in (graph.get("output_nodes") or []) if str(item) in nodes] or list(nodes)
    return max((depth(node_id) for node_id in outputs), default=0)


def _incoming_by_node(graph: dict[str, Any]) -> dict[str, list[str]]:
    incoming: dict[str, list[str]] = {
        str(node.get("id") or node.get("node_id")): []
        for node in graph.get("nodes") or []
        if node.get("id") or node.get("node_id")
    }
    for edge in graph_edges(graph):
        target = str(edge.get("target_node_id") or "")
        source = str(edge.get("source_node_id") or "")
        if target in incoming and source:
            incoming[target].append(source)
    return incoming


__all__ = ["graph_metrics"]
