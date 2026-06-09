"""Serialize reusable subgraphs into playbook records."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.graph_schema import graph_edges
from ..core.types import utc_now


def serialize_subgraph(
    graph: dict[str, Any],
    node_ids: list[str],
    *,
    name: str | None = None,
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
    write: bool = False,
    source: str = "explicit_serialization",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = [str(item) for item in node_ids]
    selected_set = set(selected)
    nodes = [
        deepcopy(node)
        for node in graph.get("nodes") or []
        if _node_id(node) in selected_set
    ]
    if not nodes:
        raise ValueError("serialize_subgraph requires at least one matching node")
    deps_by_target = _selected_dependencies(graph, selected_set)
    for node in nodes:
        node_id = _node_id(node)
        node["id"] = node_id
        node["depends_on"] = deps_by_target.get(node_id, [])
    playbook_name = name or "subgraph_" + hashlib.sha256(",".join(selected).encode("utf-8")).hexdigest()[:10]
    record = {
        "schema": "graphyagent.playbook.v1",
        "playbook_id": _playbook_id(playbook_name, selected),
        "name": playbook_name,
        "source_graph_id": graph.get("graph_id"),
        "created_at": utc_now(),
        "nodes": nodes,
        "entry_nodes": [node.get("id") for node in nodes if not node.get("depends_on")],
        "exit_nodes": [node.get("id") for node in nodes if node.get("id") not in _depended_on(nodes)],
        "metadata": {"node_count": len(nodes), "source": source, **(metadata or {})},
    }
    if write:
        path = _catalog_path(workspace, project_id, record["playbook_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        record["path"] = str(path)
    return record


def promote_reusable_subgraphs(
    graph: dict[str, Any],
    subgraph_candidates: list[dict[str, Any]],
    *,
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
    min_support: int = 2,
    write: bool = True,
) -> dict[str, Any]:
    promoted = []
    rejected = []
    for candidate in subgraph_candidates:
        nodes = [str(item) for item in (candidate.get("nodes") or []) if str(item)]
        support = int(candidate.get("support") or 0)
        if len(nodes) < 2 or support < int(min_support) or candidate.get("source") != "historical_successful_runs":
            rejected.append({
                "nodes": nodes,
                "support": support,
                "reason": "requires repeated historical successful runs",
            })
            continue
        name = str(candidate.get("template_name") or candidate.get("purpose") or "reusable_subgraph").replace(" ", "_")
        promoted.append(serialize_subgraph(
            graph,
            nodes,
            name=name,
            workspace=workspace,
            project_id=project_id,
            write=write,
            source="optimizer_repeated_success",
            metadata={
                "support": support,
                "min_support": int(min_support),
                "optimizer_candidate": candidate,
            },
        ))
    return {
        "schema": "graphyagent.playbook_promotion.v1",
        "min_support": int(min_support),
        "promoted_count": len(promoted),
        "rejected_count": len(rejected),
        "playbooks": promoted,
        "rejected": rejected,
    }


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or node.get("node_id") or "")


def _selected_dependencies(graph: dict[str, Any], selected_set: set[str]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {node_id: [] for node_id in selected_set}
    for edge in graph_edges(graph):
        source = str(edge.get("source_node_id") or "")
        target = str(edge.get("target_node_id") or "")
        if source in selected_set and target in selected_set and source not in deps.setdefault(target, []):
            deps[target].append(source)
    return deps


def _depended_on(nodes: list[dict[str, Any]]) -> set[str]:
    return {str(dep) for node in nodes for dep in (node.get("depends_on") or [])}


def _playbook_id(name: str, node_ids: list[str]) -> str:
    digest = hashlib.sha256(f"{name}:{','.join(node_ids)}".encode("utf-8")).hexdigest()[:12]
    return f"playbook-{digest}"


def _catalog_path(workspace: str | Path, project_id: str | None, playbook_id: str) -> Path:
    root = Path(workspace).expanduser().resolve()
    if project_id:
        return root / "projects" / str(project_id) / "knowledge" / "playbooks" / f"{playbook_id}.json"
    return root / "knowledge" / "playbooks" / f"{playbook_id}.json"


__all__ = ["promote_reusable_subgraphs", "serialize_subgraph"]
