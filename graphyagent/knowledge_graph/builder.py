"""Build and update project knowledge graphs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.graph_schema import graph_edges
from ..core.knowledge_schema import KnowledgeEdge, KnowledgeNode
from ..core.types import utc_now
from .policies import access_policy_for_source, should_index_file
from .store import KnowledgeGraphStore
from .views import build_node_knowledge_view


def build_for_project(
    project_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = KnowledgeGraphStore(workspace, project_id)
    nodes: list[KnowledgeNode] = []
    edges: list[KnowledgeEdge] = []
    graphs = _project_graphs(workspace, project_id, graph)
    project_files = _project_files(workspace, project_id)

    for file_record in project_files:
        if not should_index_file(file_record):
            continue
        nodes.append(_knowledge_node_from_file(project_id, None, file_record))

    for graph_item in graphs:
        graph_id = str(graph_item.get("graph_id") or "graph")
        graph_node_id = f"graph:{graph_id}"
        upstream_by_target: dict[str, list[str]] = {}
        for edge in graph_edges(graph_item):
            target = str(edge.get("target_node_id") or "")
            source = str(edge.get("source_node_id") or "")
            if target and source:
                upstream_by_target.setdefault(target, []).append(source)
        nodes.append(KnowledgeNode(
            knowledge_id=graph_node_id,
            knowledge_type="workflow_graph",
            source="workflow_graph",
            project_scope=project_id,
            graph_scope=graph_id,
            summary=_graph_summary(graph_item),
            structured_tags=["workflow", "graph"],
            metadata={"node_count": len(graph_item.get("nodes") or [])},
        ))
        for file_record in _graph_files(graph_item):
            if not should_index_file(file_record):
                continue
            file_node = _knowledge_node_from_file(project_id, graph_id, file_record)
            nodes.append(file_node)
            edges.append(KnowledgeEdge(graph_node_id, file_node.knowledge_id, "contains", created_by="knowledge_graph.build_for_project"))
        for node in graph_item.get("nodes") or []:
            node_id = str(node.get("id") or node.get("node_id") or "")
            if not node_id:
                continue
            knowledge_id = f"workflow_node:{graph_id}:{node_id}"
            upstream_ids = upstream_by_target.get(node_id, [])
            nodes.append(KnowledgeNode(
                knowledge_id=knowledge_id,
                knowledge_type="workflow_node",
                source="workflow_graph",
                project_scope=project_id,
                graph_scope=graph_id,
                summary=_node_summary(node),
                structured_tags=[node_id, str(node.get("task_type") or "task")],
                metadata={
                    "node_id": node_id,
                    "depends_on": upstream_ids,
                    "executor_type": (node.get("executor") or node.get("runner") or {}).get("type"),
                },
            ))
            edges.append(KnowledgeEdge(graph_node_id, knowledge_id, "contains", created_by="knowledge_graph.build_for_project"))
            for dep in upstream_ids:
                edges.append(KnowledgeEdge(
                    f"workflow_node:{graph_id}:{dep}",
                    knowledge_id,
                    "upstream_of",
                    created_by="knowledge_graph.build_for_project",
                ))

    changed_nodes = store.upsert_nodes(nodes)
    changed_edges = store.upsert_edges(edges)
    return {
        "schema": "graphyagent.knowledge_build.v1",
        "project_id": project_id,
        "workspace": str(Path(workspace).expanduser().resolve()),
        "node_count": len(store.load_nodes()),
        "edge_count": len(store.load_edges()),
        "changed_nodes": changed_nodes,
        "changed_edges": changed_edges,
        "created_at": utc_now(),
        "paths": {
            "nodes": str(store.nodes_path),
            "edges": str(store.edges_path),
            "weights": str(store.weights_path),
        },
    }


def refresh_from_run(
    graph_run_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    project_id: str | None = None,
) -> dict[str, Any]:
    run_dir = Path(workspace).expanduser().resolve() / "graphs" / str(graph_run_id)
    run_path = run_dir / "graph_run.json"
    if not run_path.exists():
        raise FileNotFoundError(f"graph run not found: {graph_run_id}")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    graph_config = run.get("graph_config") or {}
    graph_id = str(run.get("graph_id") or graph_config.get("graph_id") or "graph")
    meta = (graph_config.get("metadata") or {}).get("graphyagent") or {}
    resolved_project_id = str(project_id or meta.get("project_id") or "runtime")
    store = KnowledgeGraphStore(workspace, resolved_project_id)
    nodes = [
        KnowledgeNode(
            knowledge_id=f"graph_run:{graph_run_id}",
            knowledge_type="graph_run",
            source="graph_runner",
            project_scope=resolved_project_id,
            graph_scope=graph_id,
            created_from_run_id=str(graph_run_id),
            content_locator=str(run_path),
            summary=f"GraphRun {graph_run_id} finished with status {run.get('status')}",
            structured_tags=["graph_run", str(run.get("status") or "unknown")],
            reliability_score=1.0 if run.get("status") == "success" else 0.6,
            metadata={
                "status": run.get("status"),
                "node_run_count": len(run.get("node_runs") or []),
                "output_dir": run.get("output_dir"),
            },
        )
    ]
    edges: list[KnowledgeEdge] = []
    node_runs = _read_node_runs(run_dir)
    for node_run in node_runs:
        node_id = str(node_run.get("node_id") or "")
        node_run_id = str(node_run.get("node_run_id") or "")
        if not node_run_id:
            continue
        status = str(node_run.get("status") or "unknown")
        nodes.append(KnowledgeNode(
            knowledge_id=f"node_run:{node_run_id}",
            knowledge_type="node_run",
            source="graph_runner",
            project_scope=resolved_project_id,
            graph_scope=graph_id,
            created_from_run_id=str(graph_run_id),
            content_locator=str(_node_run_dir(run_dir, node_run)),
            summary=f"NodeRun {node_id} finished with status {status}",
            structured_tags=["node_run", node_id, status],
            reliability_score=1.0 if status == "success" else 0.5,
            metadata={
                "node_id": node_id,
                "status": status,
                "duration_ms": node_run.get("duration_ms"),
                "online_reflection": (node_run.get("output_snapshot") or {}).get("online_reflection"),
            },
        ))
        edges.append(KnowledgeEdge(
            f"graph_run:{graph_run_id}",
            f"node_run:{node_run_id}",
            "contains",
            created_by="knowledge_graph.refresh_from_run",
        ))
        if node_id:
            edges.append(KnowledgeEdge(
                f"workflow_node:{graph_id}:{node_id}",
                f"node_run:{node_run_id}",
                "used_by",
                created_by="knowledge_graph.refresh_from_run",
            ))
    changed_nodes = store.upsert_nodes(nodes)
    changed_edges = store.upsert_edges(edges)
    return {
        "schema": "graphyagent.knowledge_refresh.v1",
        "project_id": resolved_project_id,
        "graph_id": graph_id,
        "graph_run_id": graph_run_id,
        "changed_nodes": changed_nodes,
        "changed_edges": changed_edges,
        "node_count": len(store.load_nodes()),
        "edge_count": len(store.load_edges()),
        "paths": {"nodes": str(store.nodes_path), "edges": str(store.edges_path)},
    }


def build_view_for_node(
    project_id: str,
    graph_id: str,
    node_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph: dict[str, Any] | None = None,
    query: str = "",
    limit: int = 12,
) -> dict[str, Any]:
    store = KnowledgeGraphStore(workspace, project_id)
    if graph is not None:
        build_for_project(project_id, workspace=workspace, graph=graph)
    return build_node_knowledge_view(
        store,
        project_id=project_id,
        graph_id=graph_id,
        node_id=node_id,
        query=query,
        limit=limit,
    )


def update_weights_from_feedback(
    node_run_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    graph_run_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    node_run = _find_node_run(workspace, str(node_run_id), graph_run_id=graph_run_id)
    if not node_run:
        raise FileNotFoundError(f"node run not found: {node_run_id}")
    reflection = (node_run.get("output_snapshot") or {}).get("online_reflection") or {}
    labels = {
        str(item.get("knowledge_id")): str(item.get("label"))
        for item in reflection.get("knowledge_usage_labels") or []
        if isinstance(item, dict) and item.get("knowledge_id") and item.get("label")
    }
    upstream_labels = [
        item for item in reflection.get("upstream_usage_labels") or []
        if isinstance(item, dict) and item.get("node_id") and item.get("label")
    ]
    graph_id = str(node_run.get("graph_id") or "")
    resolved_project_id = str(project_id or node_run.get("project_id") or "runtime")
    if not graph_id and graph_run_id:
        run_path = Path(workspace).expanduser().resolve() / "graphs" / str(graph_run_id) / "graph_run.json"
        if run_path.exists():
            run = json.loads(run_path.read_text(encoding="utf-8"))
            graph_id = str(run.get("graph_id") or "")
            meta = ((run.get("graph_config") or {}).get("metadata") or {}).get("graphyagent") or {}
            resolved_project_id = str(project_id or meta.get("project_id") or resolved_project_id)
    store = KnowledgeGraphStore(workspace, resolved_project_id)
    weights = store.update_weights_from_labels(
        str(node_run.get("node_id") or ""),
        labels,
        source_node_run_id=str(node_run_id),
    )
    edge_weights = store.update_edge_weights_from_labels(
        str(node_run.get("node_id") or ""),
        upstream_labels,
        source_node_run_id=str(node_run_id),
    )
    decay_result = store.decay_stale_weights()
    return {
        "schema": "graphyagent.knowledge_feedback_update.v1",
        "project_id": resolved_project_id,
        "graph_id": graph_id,
        "node_id": node_run.get("node_id"),
        "node_run_id": node_run_id,
        "label_count": len(labels),
        "edge_label_count": len(upstream_labels),
        "weights": decay_result.get("weights") or edge_weights or weights,
        "decay": {
            "decay": decay_result.get("decay"),
            "decayed_items": decay_result.get("decayed_items"),
        },
        "paths": {"weights": str(store.weights_path)},
    }


def decay_noisy_items(
    project_id: str,
    *,
    workspace: str | Path = ".graphyagent",
    decay: float = 0.05,
) -> dict[str, Any]:
    store = KnowledgeGraphStore(workspace, project_id)
    return store.decay_stale_weights(decay=decay)


def _project_graphs(workspace: str | Path, project_id: str, graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    if graph is not None:
        return [graph]
    try:
        from ..data_manager.project_store import ProjectStore

        store = ProjectStore(workspace)
        project = store.read_project(project_id)
        graphs = []
        for item in project.get("graphs") or []:
            graph_id = item.get("graph_id")
            if graph_id:
                graphs.append(store.read_graph(project_id, str(graph_id)))
        return graphs
    except Exception:
        return []


def _project_files(workspace: str | Path, project_id: str) -> list[dict[str, Any]]:
    try:
        from ..data_manager.project_store import PROJECT_UNCLASSIFIED, ProjectStore

        project = ProjectStore(workspace).read_project(project_id)
        return list((project.get("files") or {}).get(PROJECT_UNCLASSIFIED, []))
    except Exception:
        return []


def _graph_files(graph: dict[str, Any]) -> list[dict[str, Any]]:
    files_meta = (graph.get("metadata") or {}).get("graphyagent", {}).get("files", {})
    records = list(files_meta.get("unclassified") or [])
    for items in (files_meta.get("nodes") or {}).values():
        records.extend(items or [])
    return records


def _knowledge_node_from_file(project_id: str, graph_id: str | None, file_record: dict[str, Any]) -> KnowledgeNode:
    path = str(file_record.get("storage_path") or file_record.get("path") or "")
    file_id = str(file_record.get("file_id") or file_record.get("sha256") or path)
    analysis = file_record.get("analysis") if isinstance(file_record.get("analysis"), dict) else {}
    return KnowledgeNode(
        knowledge_id=f"file:{file_id}",
        knowledge_type="file",
        source=path,
        project_scope=project_id,
        graph_scope=graph_id,
        content_locator=path,
        summary=str(analysis.get("summary") or file_record.get("name") or path),
        structured_tags=[str(file_record.get("name") or ""), str((analysis.get("audit") or {}).get("verdict") or "")],
        access_policy=access_policy_for_source(path, file_record.get("metadata") if isinstance(file_record.get("metadata"), dict) else None),
        metadata={
            "file_id": file_id,
            "name": file_record.get("name"),
            "size": file_record.get("size"),
            "sha256": file_record.get("sha256"),
            "analysis": analysis,
        },
    )


def _graph_summary(graph: dict[str, Any]) -> str:
    return (
        f"Workflow graph {graph.get('graph_id')} with {len(graph.get('nodes') or [])} nodes "
        f"and output nodes {', '.join(str(item) for item in (graph.get('output_nodes') or []))}."
    )


def _node_summary(node: dict[str, Any]) -> str:
    meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    return " ".join(
        str(item)
        for item in [
            node.get("id"),
            node.get("task_type"),
            meta.get("description"),
            node.get("gate_condition"),
        ]
        if item
    )


def _read_node_runs(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "traces" / "node_runs.jsonl"
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


def _node_run_dir(run_dir: Path, node_run: dict[str, Any]) -> Path:
    return run_dir / "nodes" / str(node_run.get("node_id") or "") / "runs" / str(node_run.get("node_run_id") or "")


def _find_node_run(workspace: str | Path, node_run_id: str, *, graph_run_id: str | None = None) -> dict[str, Any] | None:
    graphs_root = Path(workspace).expanduser().resolve() / "graphs"
    run_dirs = [graphs_root / graph_run_id] if graph_run_id else sorted(graphs_root.glob("*"))
    for run_dir in run_dirs:
        for item in _read_node_runs(run_dir):
            if item.get("node_run_id") == node_run_id:
                if graph_run_id:
                    item["graph_run_id"] = graph_run_id
                return item
    return None


__all__ = [
    "build_for_project",
    "build_view_for_node",
    "decay_noisy_items",
    "refresh_from_run",
    "update_weights_from_feedback",
]
