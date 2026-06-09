"""Persistent workflow snapshots for project graphs."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.types import utc_now
from ..data_manager.project_store import ProjectStore


def save_workflow_version(
    store: ProjectStore,
    project_id: str,
    graph_id: str,
    *,
    graph: dict[str, Any] | None = None,
    note: str | None = None,
    source: str = "agent",
) -> dict[str, Any]:
    """Persist a named version snapshot for a graph workflow."""
    saved_result: dict[str, Any] | None = None
    if graph is not None:
        saved_result = store.save_graph(project_id, graph_id, graph)
        current_graph = saved_result["graph"]
    else:
        current_graph = store.read_graph(project_id, graph_id)

    versions_root = _versions_root(store, project_id, graph_id)
    versions_root.mkdir(parents=True, exist_ok=True)
    version_number = _next_version_number(versions_root)
    created_at = utc_now()
    snapshot = {
        "version_id": f"v{version_number:04d}",
        "project_id": project_id,
        "graph_id": graph_id,
        "created_at": created_at,
        "source": source,
        "note": note or "",
        "graph": _strip_view(current_graph),
        "graph_metadata": {
            "name": current_graph.get("metadata", {}).get("graphyagent", {}).get("name"),
            "version": current_graph.get("metadata", {}).get("graphyagent", {}).get("version"),
            "node_count": len(current_graph.get("nodes") or []),
            "output_nodes": current_graph.get("output_nodes") or [],
        },
    }
    path = versions_root / f"{snapshot['version_id']}_{_timestamp_slug(created_at)}.json"
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "version": _version_summary(path, snapshot),
        "path": str(path),
        "graph": current_graph,
        "save_result": saved_result,
    }


def list_workflow_versions(store: ProjectStore, project_id: str, graph_id: str) -> dict[str, Any]:
    versions = []
    for path in sorted(_versions_root(store, project_id, graph_id).glob("v*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        versions.append(_version_summary(path, data))
    versions.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "project_id": project_id,
        "graph_id": graph_id,
        "versions": versions,
    }


def restore_workflow_version(
    store: ProjectStore,
    project_id: str,
    graph_id: str,
    version_id: str,
) -> dict[str, Any]:
    snapshot_path = _find_version_path(store, project_id, graph_id, version_id)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    graph = deepcopy(snapshot.get("graph") or {})
    if not graph:
        raise ValueError(f"workflow version has no graph: {version_id}")
    graph["graph_id"] = graph_id
    result = store.save_graph(project_id, graph_id, graph)
    restore_note = (
        f"恢复 workflow 版本 `{snapshot.get('version_id')}`。\n"
        f"- 来源：{snapshot_path}\n"
        f"- 原保存时间：{snapshot.get('created_at')}"
    )
    store.append_memory_event(
        project_id,
        graph_id,
        {"type": "graph", "name": graph_id},
        "system",
        restore_note,
    )
    return {
        "restored_from": _version_summary(snapshot_path, snapshot),
        **result,
    }


def export_workflow(
    store: ProjectStore,
    project_id: str,
    graph_id: str,
    *,
    output_path: str | Path | None = None,
    include_versions: bool = False,
) -> dict[str, Any]:
    graph = _strip_view(store.read_graph(project_id, graph_id))
    exports_root = _graph_root(store, project_id, graph_id) / "exports"
    exports_root.mkdir(parents=True, exist_ok=True)
    if output_path:
        export_path = Path(output_path).expanduser().resolve()
        export_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        export_path = exports_root / f"{graph_id}_{_timestamp_slug(utc_now())}.json"
    payload: dict[str, Any] = {
        "project_id": project_id,
        "graph_id": graph_id,
        "exported_at": utc_now(),
        "graph": graph,
    }
    if include_versions:
        payload["versions"] = list_workflow_versions(store, project_id, graph_id)["versions"]
    export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "path": str(export_path),
        "graph_id": graph_id,
        "node_count": len(graph.get("nodes") or []),
        "include_versions": include_versions,
    }


def import_workflow(
    store: ProjectStore,
    project_id: str,
    path: str | Path,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    graph = data.get("graph") if isinstance(data.get("graph"), dict) else data
    if not isinstance(graph, dict):
        raise ValueError("workflow import file must contain a graph object")
    graph_name = name or graph.get("metadata", {}).get("graphyagent", {}).get("name") or graph.get("graph_id") or source.stem
    created = store.create_graph(project_id, str(graph_name), graph)
    save_workflow_version(
        store,
        project_id,
        created["graph_id"],
        note=f"imported from {source}",
        source="import",
    )
    return {
        "graph": created,
        "source": str(source),
    }


def merge_workflow(
    store: ProjectStore,
    project_id: str,
    graph_id: str,
    *,
    source_graph: dict[str, Any] | None = None,
    source_graph_id: str | None = None,
    path: str | Path | None = None,
    prefix: str | None = None,
    attach_to: list[str] | None = None,
    output_policy: str = "append",
    note: str | None = None,
) -> dict[str, Any]:
    """Merge another graph into an existing workflow graph."""
    target_graph = store.read_graph(project_id, graph_id)
    incoming_graph = _load_merge_source(
        store,
        project_id,
        source_graph=source_graph,
        source_graph_id=source_graph_id,
        path=path,
    )
    incoming_nodes = incoming_graph.get("nodes") or []
    if not isinstance(incoming_nodes, list) or not incoming_nodes:
        raise ValueError("merge_workflow source graph must contain nodes")

    target_nodes = target_graph.setdefault("nodes", [])
    existing_node_ids = {str(node.get("id")) for node in target_nodes}
    source_label = (
        prefix
        or incoming_graph.get("metadata", {}).get("graphyagent", {}).get("name")
        or incoming_graph.get("graph_id")
        or "merged"
    )
    safe_prefix = _safe_identifier(str(source_label), fallback="merged")
    node_id_map = _build_node_id_map(incoming_nodes, safe_prefix, existing_node_ids)
    artifact_alias_map = _build_artifact_alias_map(
        incoming_graph.get("initial_artifacts") or {},
        safe_prefix,
        set((target_graph.get("initial_artifacts") or {}).keys()),
    )
    resolved_attach_to = _resolve_attach_targets(target_graph, attach_to or [])
    incoming_roots = {
        str(node.get("id"))
        for node in incoming_nodes
        if not node.get("depends_on") and not node.get("dependencies")
    }

    rewritten_nodes = []
    for source_node in incoming_nodes:
        node = deepcopy(source_node)
        old_node_id = str(node.get("id") or node.get("node_id") or "")
        node["id"] = node_id_map[old_node_id]
        node.pop("node_id", None)
        dependencies = [
            node_id_map[str(dep)]
            for dep in (node.get("depends_on") or node.get("dependencies") or [])
            if str(dep) in node_id_map
        ]
        if old_node_id in incoming_roots:
            dependencies = _ordered_unique([*resolved_attach_to, *dependencies])
        node["depends_on"] = dependencies
        node.pop("dependencies", None)
        node["inputs"] = {
            str(name): _rewrite_input_reference(reference, node_id_map, artifact_alias_map)
            for name, reference in (node.get("inputs") or {}).items()
        }
        node.setdefault("metadata", {}).setdefault("graphyagent", {})["merged_from"] = {
            "source_graph_id": incoming_graph.get("graph_id"),
            "original_node_id": old_node_id,
            "prefix": safe_prefix,
        }
        rewritten_nodes.append(node)

    target_graph.setdefault("initial_artifacts", {}).update(
        {
            artifact_alias_map[str(alias)]: deepcopy(spec)
            for alias, spec in (incoming_graph.get("initial_artifacts") or {}).items()
        }
    )
    target_nodes.extend(rewritten_nodes)
    _merge_context_dict(target_graph, incoming_graph, "context", safe_prefix)
    _merge_context_dict(target_graph, incoming_graph, "experiment", safe_prefix)

    source_outputs = [
        node_id_map[str(node_id)]
        for node_id in (incoming_graph.get("output_nodes") or [])
        if str(node_id) in node_id_map
    ]
    if not source_outputs:
        source_outputs = [rewritten_nodes[-1]["id"]]
    policy = str(output_policy or "append").lower()
    if policy == "replace":
        target_graph["output_nodes"] = source_outputs
    elif policy == "preserve":
        target_graph["output_nodes"] = list(target_graph.get("output_nodes") or [])
    else:
        target_graph["output_nodes"] = _ordered_unique([
            *(target_graph.get("output_nodes") or []),
            *source_outputs,
        ])

    meta = target_graph.setdefault("metadata", {}).setdefault("graphyagent", {})
    merge_record = {
        "source_graph_id": incoming_graph.get("graph_id"),
        "prefix": safe_prefix,
        "node_count": len(rewritten_nodes),
        "attach_to": resolved_attach_to,
        "output_policy": policy,
        "created_at": utc_now(),
    }
    meta.setdefault("merge_history", []).append(merge_record)
    result = store.save_graph(project_id, graph_id, target_graph)
    version = save_workflow_version(
        store,
        project_id,
        graph_id,
        note=note or f"merged workflow {incoming_graph.get('graph_id') or safe_prefix}",
        source="merge",
    )
    return {
        "graph": result["graph"],
        "diff": result.get("diff"),
        "merge": merge_record,
        "node_id_map": node_id_map,
        "artifact_alias_map": artifact_alias_map,
        "version": version["version"],
    }


def list_graph_run_checkpoints(workspace_root: str | Path, graph_run_id: str) -> dict[str, Any]:
    checkpoints_root = _checkpoint_root(workspace_root, graph_run_id)
    checkpoints = []
    for path in sorted(checkpoints_root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        checkpoints.append(_checkpoint_summary(path, data))
    return {
        "graph_run_id": graph_run_id,
        "checkpoints": checkpoints,
    }


def read_graph_run_checkpoint(
    workspace_root: str | Path,
    graph_run_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    checkpoint_path = _find_checkpoint_path(workspace_root, graph_run_id, checkpoint_id)
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    return {
        "checkpoint": checkpoint,
        "summary": _checkpoint_summary(checkpoint_path, checkpoint),
    }


def fork_workflow_from_checkpoint(
    store: ProjectStore,
    project_id: str,
    graph_id: str,
    *,
    graph_run_id: str,
    checkpoint_id: str,
    name: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    checkpoint_result = read_graph_run_checkpoint(store.workspace_root, graph_run_id, checkpoint_id)
    checkpoint = checkpoint_result["checkpoint"]
    checkpoint_state = checkpoint.get("state") or {}
    source_graph = store.read_graph(project_id, graph_id)
    node_id = checkpoint.get("node_id") or checkpoint_result["summary"].get("node_id")
    fork_name = name or f"{source_graph.get('metadata', {}).get('graphyagent', {}).get('name') or graph_id} checkpoint {node_id or checkpoint_id}"
    fork_graph = _strip_view(source_graph)
    fork_graph["graph_id"] = fork_name
    fork_graph["context"] = dict(checkpoint_state.get("context") or fork_graph.get("context") or {})
    fork_graph["experiment"] = dict(checkpoint_state.get("experiment") or fork_graph.get("experiment") or {})
    fork_graph["initial_artifacts"] = _checkpoint_initial_artifacts(checkpoint_state)
    fork_meta = fork_graph.setdefault("metadata", {}).setdefault("graphyagent", {})
    fork_meta["name"] = fork_name
    fork_meta["forked_from_checkpoint"] = {
        "project_id": project_id,
        "graph_id": graph_id,
        "graph_run_id": graph_run_id,
        "checkpoint_id": checkpoint_result["summary"].get("checkpoint_id"),
        "node_id": node_id,
        "checkpoint_path": checkpoint_result["summary"].get("path"),
        "created_at": utc_now(),
    }
    created = store.create_graph(project_id, fork_name, fork_graph)
    version = save_workflow_version(
        store,
        project_id,
        created["graph_id"],
        note=note or f"forked from {graph_run_id}:{checkpoint_id}",
        source="checkpoint_fork",
    )
    return {
        "graph": created,
        "version": version["version"],
        "checkpoint": checkpoint_result["summary"],
    }


def _versions_root(store: ProjectStore, project_id: str, graph_id: str) -> Path:
    return _graph_root(store, project_id, graph_id) / "versions"


def _load_merge_source(
    store: ProjectStore,
    project_id: str,
    *,
    source_graph: dict[str, Any] | None,
    source_graph_id: str | None,
    path: str | Path | None,
) -> dict[str, Any]:
    if source_graph is not None:
        return _unwrap_workflow_payload(deepcopy(source_graph))
    if source_graph_id:
        return _strip_view(store.read_graph(project_id, source_graph_id))
    if path:
        source = Path(path).expanduser().resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        return _unwrap_workflow_payload(data)
    raise ValueError("merge_workflow requires payload.source_graph, source_graph_id, or path")


def _unwrap_workflow_payload(data: dict[str, Any]) -> dict[str, Any]:
    graph = data.get("graph") if isinstance(data.get("graph"), dict) else data
    if not isinstance(graph, dict):
        raise ValueError("workflow payload must contain a graph object")
    return graph


def _build_node_id_map(
    incoming_nodes: list[dict[str, Any]],
    prefix: str,
    existing_node_ids: set[str],
) -> dict[str, str]:
    used = set(existing_node_ids)
    mapping: dict[str, str] = {}
    for node in incoming_nodes:
        old_id = str(node.get("id") or node.get("node_id") or "")
        if not old_id:
            raise ValueError("merge_workflow source node is missing id")
        base = f"{prefix}_{_safe_identifier(old_id, fallback='node')}"
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        mapping[old_id] = candidate
    return mapping


def _build_artifact_alias_map(
    source_artifacts: dict[str, Any],
    prefix: str,
    existing_aliases: set[str],
) -> dict[str, str]:
    used = set(existing_aliases)
    mapping: dict[str, str] = {}
    for alias in source_artifacts:
        old_alias = str(alias)
        base = f"{prefix}_{_safe_identifier(old_alias, fallback='artifact')}"
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        mapping[old_alias] = candidate
    return mapping


def _resolve_attach_targets(graph: dict[str, Any], attach_to: list[str]) -> list[str]:
    existing = {str(node.get("id")) for node in graph.get("nodes", [])}
    targets = []
    for raw in attach_to:
        node_id = str(raw)
        if node_id not in existing:
            raise FileNotFoundError(f"merge_workflow attach target not found: {node_id}")
        targets.append(node_id)
    return _ordered_unique(targets)


def _rewrite_input_reference(
    reference: Any,
    node_id_map: dict[str, str],
    artifact_alias_map: dict[str, str],
) -> Any:
    if isinstance(reference, dict):
        return {
            key: _rewrite_input_reference(value, node_id_map, artifact_alias_map)
            for key, value in reference.items()
        }
    if not isinstance(reference, str):
        return reference
    if reference in artifact_alias_map:
        return artifact_alias_map[reference]
    if reference.startswith("alias:"):
        alias = reference.split(":", 1)[1]
        return f"alias:{artifact_alias_map.get(alias, alias)}"
    if ":" in reference and not reference.startswith("artifact:"):
        node_id, output_name = reference.split(":", 1)
        if node_id in node_id_map:
            return f"{node_id_map[node_id]}:{output_name}"
    return reference


def _merge_context_dict(
    target_graph: dict[str, Any],
    source_graph: dict[str, Any],
    field: str,
    prefix: str,
) -> None:
    source_values = source_graph.get(field) or {}
    if not isinstance(source_values, dict) or not source_values:
        return
    target_values = target_graph.setdefault(field, {})
    for key, value in source_values.items():
        target_key = str(key)
        if target_key in target_values:
            target_key = f"{prefix}.{target_key}"
        target_values[target_key] = deepcopy(value)


def _checkpoint_root(workspace_root: str | Path, graph_run_id: str) -> Path:
    root = Path(workspace_root).expanduser().resolve() / "graphs" / graph_run_id / "checkpoints"
    if not root.exists():
        raise FileNotFoundError(f"checkpoint directory not found for graph run: {graph_run_id}")
    return root


def _graph_root(store: ProjectStore, project_id: str, graph_id: str) -> Path:
    graph_root = store.workspace_root / "projects" / project_id / "graphs" / graph_id
    if not graph_root.exists():
        store.read_graph(project_id, graph_id)
    return graph_root


def _next_version_number(versions_root: Path) -> int:
    highest = 0
    for path in versions_root.glob("v*.json"):
        raw = path.name.split("_", 1)[0].lstrip("v")
        if raw.isdigit():
            highest = max(highest, int(raw))
    return highest + 1


def _find_version_path(store: ProjectStore, project_id: str, graph_id: str, version_id: str) -> Path:
    versions_root = _versions_root(store, project_id, graph_id)
    normalized = str(version_id).strip()
    matches = sorted(versions_root.glob(f"{normalized}_*.json"))
    if not matches and normalized.isdigit():
        matches = sorted(versions_root.glob(f"v{int(normalized):04d}_*.json"))
    if not matches:
        direct = versions_root / normalized
        if direct.exists():
            matches = [direct]
    if not matches:
        raise FileNotFoundError(f"workflow version not found: {version_id}")
    return matches[-1]


def _find_checkpoint_path(workspace_root: str | Path, graph_run_id: str, checkpoint_id: str) -> Path:
    root = _checkpoint_root(workspace_root, graph_run_id)
    normalized = str(checkpoint_id).strip()
    candidates: list[Path] = []
    if normalized.endswith(".json"):
        direct = root / normalized
        if direct.exists():
            candidates.append(direct)
    if normalized.isdigit():
        candidates.extend(sorted(root.glob(f"{int(normalized):04d}_*.json")))
    candidates.extend(sorted(root.glob(f"{normalized}_*.json")))
    candidates.extend(sorted(path for path in root.glob("*.json") if normalized in path.stem))
    if not candidates:
        raise FileNotFoundError(f"checkpoint not found: {graph_run_id}:{checkpoint_id}")
    return candidates[0]


def _version_summary(path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "version_id": snapshot.get("version_id"),
        "created_at": snapshot.get("created_at"),
        "source": snapshot.get("source"),
        "note": snapshot.get("note") or "",
        "path": str(path),
        "graph_metadata": snapshot.get("graph_metadata") or {},
    }


def _checkpoint_summary(path: Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    state = checkpoint.get("state") or {}
    manifest = checkpoint.get("manifest") if isinstance(checkpoint.get("manifest"), dict) else {}
    return {
        "checkpoint_id": checkpoint.get("checkpoint_id") or manifest.get("checkpoint_id") or path.stem.split("_", 1)[0],
        "node_id": checkpoint.get("node_id"),
        "created_at": checkpoint.get("created_at"),
        "path": str(path),
        "manifest": manifest,
        "artifact_count": len(state.get("artifacts") or {}),
        "node_result_count": len(state.get("node_results") or {}),
        "context_keys": sorted((state.get("context") or {}).keys()),
    }


def _checkpoint_initial_artifacts(checkpoint_state: dict[str, Any]) -> dict[str, Any]:
    artifacts = checkpoint_state.get("artifacts") or {}
    aliases = checkpoint_state.get("artifact_aliases") or {}
    initial: dict[str, Any] = {}
    used_aliases: set[str] = set()
    artifact_to_alias = {artifact_id: alias for alias, artifact_id in aliases.items()}
    for artifact_id, artifact in artifacts.items():
        if not isinstance(artifact, dict) or not artifact.get("uri"):
            continue
        raw_alias = artifact_to_alias.get(artifact_id) or artifact.get("name") or artifact_id[:12]
        alias = _safe_artifact_alias(str(raw_alias), used_aliases)
        metadata = dict(artifact.get("metadata") or {})
        metadata.update({
            "checkpoint_artifact_id": artifact_id,
            "checkpoint_source": "graph_state",
        })
        initial[alias] = {
            "path": artifact["uri"],
            "type": artifact.get("type") or "checkpoint_artifact",
            "metadata": metadata,
        }
    return initial


def _safe_artifact_alias(raw: str, used: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw).strip("._")
    alias = cleaned or "artifact"
    candidate = alias
    index = 2
    while candidate in used:
        candidate = f"{alias}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _safe_identifier(raw: str, *, fallback: str) -> str:
    value = re.sub(r"[^0-9A-Za-z_.-]+", "_", raw).strip("._-")
    return value or fallback


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _strip_view(graph: dict[str, Any]) -> dict[str, Any]:
    graph = deepcopy(graph)
    graph.pop("view", None)
    return graph


def _timestamp_slug(value: str) -> str:
    return "".join(ch if ch.isdigit() else "-" for ch in value).strip("-")
