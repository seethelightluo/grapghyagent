"""Persistent store for project-scoped knowledge graphs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..core.knowledge_schema import KnowledgeEdge, KnowledgeNode
from ..core.types import utc_now


class KnowledgeGraphStore:
    """JSONL-backed knowledge graph store.

    The store intentionally uses transparent files so optimizer and debugging
    tools can inspect state without a database service.
    """

    def __init__(self, workspace: str | Path, project_id: str | None = None):
        self.workspace = Path(workspace).expanduser().resolve()
        self.project_id = _safe_id(project_id or "runtime")
        if self.project_id == "runtime":
            self.root = self.workspace / "knowledge" / "runtime"
        else:
            self.root = self.workspace / "projects" / self.project_id / "knowledge"
        self.nodes_path = self.root / "nodes.jsonl"
        self.edges_path = self.root / "edges.jsonl"
        self.weights_path = self.root / "weights.json"
        self.usage_path = self.root / "context_usage.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)

    def load_nodes(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.nodes_path)

    def load_edges(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.edges_path)

    def load_weights(self) -> dict[str, Any]:
        try:
            data = json.loads(self.weights_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"node_weights": {}, "updated_at": None}
        return data if isinstance(data, dict) else {"node_weights": {}, "updated_at": None}

    def upsert_nodes(self, nodes: list[KnowledgeNode | dict[str, Any]]) -> int:
        existing = {str(item.get("knowledge_id")): item for item in self.load_nodes()}
        changed = 0
        for raw in nodes:
            item = raw.to_dict() if isinstance(raw, KnowledgeNode) else dict(raw)
            knowledge_id = str(item.get("knowledge_id") or "")
            if not knowledge_id:
                continue
            previous = existing.get(knowledge_id)
            if previous != item:
                changed += 1
            existing[knowledge_id] = item
        _write_jsonl(self.nodes_path, existing.values())
        return changed

    def upsert_edges(self, edges: list[KnowledgeEdge | dict[str, Any]]) -> int:
        existing = {_edge_key(item): item for item in self.load_edges()}
        changed = 0
        for raw in edges:
            item = raw.to_dict() if isinstance(raw, KnowledgeEdge) else dict(raw)
            key = _edge_key(item)
            if not key:
                continue
            previous = existing.get(key)
            if previous != item:
                changed += 1
            existing[key] = item
        _write_jsonl(self.edges_path, existing.values())
        return changed

    def record_context_usage(self, usage: dict[str, Any]) -> dict[str, Any]:
        record = dict(usage)
        record.setdefault("schema", "graphyagent.context_usage.v1")
        record.setdefault("created_at", utc_now())
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def update_weights_from_labels(
        self,
        node_id: str,
        labels: dict[str, str],
        *,
        source_node_run_id: str | None = None,
    ) -> dict[str, Any]:
        weights = self.load_weights()
        node_weights = weights.setdefault("node_weights", {}).setdefault(str(node_id), {})
        for knowledge_id, label in labels.items():
            item = node_weights.setdefault(
                str(knowledge_id),
                {
                    "background": 0.0,
                    "evidence": 0.0,
                    "risk": 0.0,
                    "uses": 0,
                    "unused": 0,
                    "updated_at": None,
                },
            )
            delta_b, delta_e, delta_r = _label_delta(str(label))
            item["background"] = round(float(item.get("background", 0.0)) + delta_b, 6)
            item["evidence"] = round(float(item.get("evidence", 0.0)) + delta_e, 6)
            item["risk"] = max(0.0, round(float(item.get("risk", 0.0)) + delta_r, 6))
            if label in {"useful", "critical"}:
                item["uses"] = int(item.get("uses", 0)) + 1
            if label == "unused":
                item["unused"] = int(item.get("unused", 0)) + 1
            item["last_label"] = label
            item["last_node_run_id"] = source_node_run_id
            item["updated_at"] = utc_now()
        weights["updated_at"] = utc_now()
        self.weights_path.write_text(json.dumps(weights, indent=2, ensure_ascii=False), encoding="utf-8")
        return weights


    def update_edge_weights_from_labels(
        self,
        target_node_id: str,
        labels: list[dict[str, Any]],
        *,
        source_node_run_id: str | None = None,
    ) -> dict[str, Any]:
        weights = self.load_weights()
        target_weights = weights.setdefault("edge_weights", {}).setdefault(str(target_node_id), {})
        for label_record in labels:
            source_node_id = str(label_record.get("node_id") or "")
            label = str(label_record.get("label") or "")
            if not source_node_id or not label:
                continue
            item = target_weights.setdefault(
                source_node_id,
                {
                    "utility": 0.0,
                    "useful": 0,
                    "critical": 0,
                    "unused": 0,
                    "risky": 0,
                    "misleading": 0,
                    "insufficient": 0,
                    "observations": 0,
                    "updated_at": None,
                },
            )
            item["utility"] = round(float(item.get("utility", 0.0)) + _edge_label_delta(label), 6)
            if label in {"useful", "critical", "unused", "risky", "misleading", "insufficient"}:
                item[label] = int(item.get(label, 0)) + 1
            item["observations"] = int(item.get("observations", 0)) + 1
            item["last_label"] = label
            item["last_node_run_id"] = source_node_run_id
            item["updated_at"] = utc_now()
        weights["updated_at"] = utc_now()
        self.weights_path.write_text(json.dumps(weights, indent=2, ensure_ascii=False), encoding="utf-8")
        return weights

    def decay_stale_weights(self, *, decay: float = 0.05) -> dict[str, Any]:
        weights = self.load_weights()
        decay = max(0.0, min(1.0, float(decay)))
        decayed_items = 0
        for node_weights in (weights.get("node_weights") or {}).values():
            for item in node_weights.values():
                uses = int(item.get("uses", 0))
                unused = int(item.get("unused", 0))
                risk = float(item.get("risk", 0.0))
                if unused > uses or risk > 0.25:
                    item["background"] = round(float(item.get("background", 0.0)) * (1.0 - decay), 6)
                    item["evidence"] = round(float(item.get("evidence", 0.0)) * (1.0 - decay), 6)
                    item["risk"] = round(max(0.0, risk + (decay / 2 if unused > uses else 0.0)), 6)
                    item["decayed_at"] = utc_now()
                    decayed_items += 1
        for target_weights in (weights.get("edge_weights") or {}).values():
            for item in target_weights.values():
                positive = int(item.get("useful", 0)) + int(item.get("critical", 0))
                negative = (
                    int(item.get("unused", 0))
                    + int(item.get("risky", 0))
                    + int(item.get("misleading", 0))
                    + int(item.get("insufficient", 0))
                )
                if negative > positive:
                    item["utility"] = round(float(item.get("utility", 0.0)) * (1.0 - decay), 6)
                    item["decayed_at"] = utc_now()
                    decayed_items += 1
        weights["updated_at"] = utc_now()
        weights["last_decay"] = {"decay": decay, "decayed_items": decayed_items, "created_at": utc_now()}
        self.weights_path.write_text(json.dumps(weights, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "schema": "graphyagent.knowledge_decay.v1",
            "project_id": self.project_id,
            "decay": decay,
            "decayed_items": decayed_items,
            "weights": weights,
            "paths": {"weights": str(self.weights_path)},
        }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _write_jsonl(path: Path, values: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in sorted(values, key=lambda value: str(value.get("knowledge_id") or value.get("edge_id") or "")):
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def _edge_key(item: dict[str, Any]) -> str:
    edge_id = str(item.get("edge_id") or "")
    if edge_id:
        return edge_id
    source = str(item.get("source_id") or "")
    target = str(item.get("target_id") or "")
    relation = str(item.get("relation_type") or "")
    return f"{source}->{relation}->{target}" if source and target and relation else ""


def _label_delta(label: str) -> tuple[float, float, float]:
    if label == "critical":
        return 0.05, 0.35, -0.02
    if label == "useful":
        return 0.05, 0.18, -0.01
    if label == "unused":
        return -0.03, -0.08, 0.0
    if label == "risky":
        return -0.05, -0.12, 0.18
    if label == "misleading":
        return -0.08, -0.2, 0.28
    if label == "insufficient":
        return 0.0, -0.04, 0.05
    return 0.0, 0.0, 0.0


def _edge_label_delta(label: str) -> float:
    if label == "critical":
        return 0.35
    if label == "useful":
        return 0.18
    if label == "unused":
        return -0.08
    if label == "risky":
        return -0.12
    if label == "misleading":
        return -0.2
    if label == "insufficient":
        return -0.04
    return 0.0


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-.")
    return cleaned or "runtime"


__all__ = ["KnowledgeGraphStore"]
