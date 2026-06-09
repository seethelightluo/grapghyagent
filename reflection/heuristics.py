"""Deterministic online reflection heuristics."""
from __future__ import annotations

from typing import Any


def label_upstream_usage(input_snapshot: dict[str, Any], *, status: str) -> list[dict[str, Any]]:
    labels = []
    for node_id, result in sorted((input_snapshot.get("depends_on") or {}).items()):
        result_status = str((result or {}).get("status") or "unknown")
        outputs = (result or {}).get("outputs") or {}
        if status == "success" and result_status == "success" and outputs:
            label = "useful"
            reason = "upstream output was available to a successful node"
        elif result_status != "success":
            label = "insufficient"
            reason = "upstream did not complete successfully"
        else:
            label = "unused"
            reason = "upstream provided no materialized outputs"
        labels.append({
            "node_id": str(node_id),
            "label": label,
            "reason": reason,
        })
    return labels


def label_knowledge_usage(packet: dict[str, Any], *, status: str) -> list[dict[str, Any]]:
    labels = []
    evidence_ids = {
        str(item.get("knowledge_id"))
        for item in packet.get("evidence_candidates") or []
        if item.get("knowledge_id")
    }
    gaps = packet.get("unresolved_evidence_gaps") or []
    for knowledge_id in packet.get("supplied_knowledge_ids") or []:
        if status != "success":
            label = "insufficient"
            reason = "node did not complete successfully"
        elif knowledge_id in evidence_ids and not gaps:
            label = "critical"
            reason = "evidence item was supplied and no unresolved evidence gap remained"
        elif knowledge_id in evidence_ids:
            label = "useful"
            reason = "evidence item was supplied with remaining gaps"
        else:
            label = "useful"
            reason = "background item supported node framing"
        labels.append({
            "knowledge_id": str(knowledge_id),
            "label": label,
            "reason": reason,
        })
    if not labels and gaps:
        labels.append({
            "knowledge_id": None,
            "label": "insufficient",
            "reason": "; ".join(str(gap) for gap in gaps),
        })
    return labels


def suggested_weight_updates(labels: list[dict[str, Any]]) -> dict[str, float]:
    updates: dict[str, float] = {}
    for item in labels:
        knowledge_id = item.get("knowledge_id")
        if not knowledge_id:
            continue
        label = item.get("label")
        if label == "critical":
            updates[str(knowledge_id)] = 0.35
        elif label == "useful":
            updates[str(knowledge_id)] = 0.18
        elif label == "unused":
            updates[str(knowledge_id)] = -0.08
        elif label == "risky":
            updates[str(knowledge_id)] = -0.12
        elif label == "misleading":
            updates[str(knowledge_id)] = -0.2
        elif label == "insufficient":
            updates[str(knowledge_id)] = -0.04
    return updates


__all__ = ["label_knowledge_usage", "label_upstream_usage", "suggested_weight_updates"]
