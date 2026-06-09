"""Retrieval helpers over the local knowledge graph store."""
from __future__ import annotations

from typing import Any

from .scoring import score_knowledge_item
from .store import KnowledgeGraphStore


def retrieve_for_node(
    store: KnowledgeGraphStore,
    *,
    node_id: str,
    graph_id: str | None = None,
    query: str = "",
    limit: int = 12,
) -> list[dict[str, Any]]:
    weights = store.load_weights()
    scored = [
        score_knowledge_item(item, node_id=node_id, graph_id=graph_id, query=query, weights=weights)
        for item in store.load_nodes()
    ]
    scoped = [
        item for item in scored
        if not graph_id or not item.get("graph_scope") or item.get("graph_scope") == graph_id
    ]
    scoped.sort(key=lambda item: (float(item.get("score", 0.0)), str(item.get("created_at") or "")), reverse=True)
    return scoped[: max(1, int(limit))]


__all__ = ["retrieve_for_node"]
