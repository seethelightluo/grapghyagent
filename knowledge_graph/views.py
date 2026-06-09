"""Node-conditioned knowledge view construction."""
from __future__ import annotations

from typing import Any

from ..core.knowledge_schema import KnowledgeView
from .retrieval import retrieve_for_node
from .store import KnowledgeGraphStore
from .summarizer import summarize_items


def build_node_knowledge_view(
    store: KnowledgeGraphStore,
    *,
    project_id: str,
    graph_id: str,
    node_id: str,
    query: str = "",
    limit: int = 12,
) -> dict[str, Any]:
    candidates = retrieve_for_node(store, node_id=node_id, graph_id=graph_id, query=query, limit=limit)
    quarantined = [item for item in candidates if item.get("access_policy") == "quarantine"]
    internal = [item for item in candidates if item.get("access_policy") != "quarantine"]
    evidence = [
        item for item in internal
        if item.get("knowledge_type") in {"file", "file_chunk", "schema", "audit_result", "node_run", "trace_summary"}
    ][: max(1, limit // 2)]
    background = [item for item in internal if item not in evidence][: max(1, limit - len(evidence))]
    if not background and evidence:
        background = evidence[:1]
    view = KnowledgeView(
        project_id=project_id,
        graph_id=graph_id,
        node_id=node_id,
        background_items=background,
        evidence_items=evidence,
        quarantined_items=quarantined,
        candidate_count=len(candidates),
        scoring_policy={
            "background_summary_chars": 2400,
            "evidence_limit": len(evidence),
            "external_items_quarantined": len(quarantined),
        },
    ).to_dict()
    view["background_summary"] = summarize_items(background, max_chars=2400)
    return view


__all__ = ["build_node_knowledge_view"]
