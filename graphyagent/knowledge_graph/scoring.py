"""Deterministic node-conditioned knowledge scoring."""
from __future__ import annotations

import re
from typing import Any


def score_knowledge_item(
    item: dict[str, Any],
    *,
    node_id: str,
    graph_id: str | None = None,
    query: str = "",
    weights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = " ".join(
        str(value)
        for value in [
            item.get("knowledge_id"),
            item.get("knowledge_type"),
            item.get("summary"),
            " ".join(item.get("structured_tags") or []),
        ]
        if value
    )
    relevance = _token_overlap(query or node_id, text)
    if graph_id and item.get("graph_scope") == graph_id:
        relevance += 0.2
    if item.get("knowledge_type") in {"workflow_node", "node_run"} and node_id in str(item.get("knowledge_id")):
        relevance += 0.25
    node_weights = ((weights or {}).get("node_weights") or {}).get(node_id, {})
    item_weights = node_weights.get(str(item.get("knowledge_id"))) or {}
    background = float(item_weights.get("background", 0.0))
    evidence = float(item_weights.get("evidence", 0.0))
    risk = float(item_weights.get("risk", 0.0))
    freshness = float(item.get("freshness_score", 1.0))
    reliability = float(item.get("reliability_score", 1.0))
    quarantine_penalty = 0.4 if item.get("access_policy") == "quarantine" else 0.0
    score = (0.25 * background) + (0.45 * evidence) + (0.25 * relevance) + (0.05 * freshness) + (0.1 * reliability) - risk - quarantine_penalty
    enriched = dict(item)
    enriched["score"] = round(score, 6)
    enriched["score_features"] = {
        "background_weight": background,
        "evidence_weight": evidence,
        "relevance": round(relevance, 6),
        "risk_penalty": risk,
        "freshness": freshness,
        "reliability": reliability,
        "quarantine_penalty": quarantine_penalty,
    }
    return enriched


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", str(value).lower())
        if token
    }


__all__ = ["score_knowledge_item"]
