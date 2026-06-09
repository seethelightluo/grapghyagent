"""Project, graph, and virtual file management for the GraphyAgent canvas."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.graph_schema import graph_edges as normalized_graph_edges
from ..core.config import normalize_graph_config_data
from ..core.types import GraphConfig, GraphState, utc_now
from ..agent_runtime.common_tools import summarize_file_for_prompt
from ..agent_runtime.context_budget import resolve_max_tokens
from ..model_routing.llm_client import LLMCallError, chat_completion
from ..model_routing.routing import route_model
from ..task_decompose.builder import build_workflow_graph


PROJECT_UNCLASSIFIED = "project_unclassified"
GRAPH_UNCLASSIFIED = "graph_unclassified"
NODE_FILES = "node"


_DEPENDENCY_RULES = [
    {
        "source_terms": ["引用意图", "依赖度", "分类"],
        "target_terms": ["论文结论", "论点", "提取"],
        "source_fallback": "引用意图与依赖度分类",
        "target_fallback": "论文结论与论点提取",
        "reason": "论文结论与论点提取需要先知道引用意图与依赖度分类，不能与其并行。",
    }
]


class ProjectStore:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.projects_root = self.workspace_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.projects_root / "index.json"
        if not self.index_path.exists():
            self._write_index({
                "current_project_id": None,
                "projects": [],
            })

    def bootstrap(self, default_config_path: str | Path | None = None) -> dict[str, Any]:
        index = self._read_index()
        if index.get("projects"):
            current = self.get_current_project()
            if current and current.get("current_graph_id"):
                return self.snapshot()
        project = self.create_project("Default Project")
        graph_data = _default_graph(default_config_path)
        graph = self.create_graph(project["project_id"], graph_data.get("graph_id", "default_graph"), graph_data)
        self.select_graph(project["project_id"], graph["graph_id"])
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        index = self._read_index()
        current_project = self.get_current_project()
        current_graph = None
        if current_project and current_project.get("current_graph_id"):
            current_graph = self.read_graph(
                current_project["project_id"],
                current_project["current_graph_id"],
            )
        return {
            "projects": index.get("projects", []),
            "current_project": current_project,
            "current_graph": current_graph,
            "virtual_tree": self.virtual_tree(),
            "ai_suggestions": self.ai_suggestions(current_graph),
        }

    def list_projects(self) -> list[dict[str, Any]]:
        return list(self._read_index().get("projects", []))

    def create_project(self, name: str) -> dict[str, Any]:
        clean_name = name.strip() or "Untitled Project"
        project_id = _slug(clean_name) or f"project-{uuid.uuid4().hex[:8]}"
        project_id = self._unique_project_id(project_id)
        now = utc_now()
        project = {
            "project_id": project_id,
            "name": clean_name,
            "created_at": now,
            "updated_at": now,
            "current_graph_id": None,
            "graphs": [],
            "files": {PROJECT_UNCLASSIFIED: []},
        }
        project_dir = self._project_dir(project_id)
        (project_dir / "files" / PROJECT_UNCLASSIFIED).mkdir(parents=True, exist_ok=True)
        (project_dir / "graphs").mkdir(parents=True, exist_ok=True)
        self._write_project(project)
        index = self._read_index()
        index["projects"].append(_project_summary(project))
        index["current_project_id"] = project_id
        self._write_index(index)
        return project

    def select_project(self, project_id: str) -> dict[str, Any]:
        project = self.read_project(project_id)
        index = self._read_index()
        index["current_project_id"] = project_id
        self._write_index(index)
        return project

    def delete_project(self, project_id: str) -> dict[str, Any]:
        index = self._read_index()
        if project_id not in {item["project_id"] for item in index.get("projects", [])}:
            raise FileNotFoundError(f"project not found: {project_id}")
        project_dir = self._project_dir(project_id)
        _remove_inside(self.projects_root, project_dir)
        index["projects"] = [
            item for item in index.get("projects", [])
            if item["project_id"] != project_id
        ]
        if index.get("current_project_id") == project_id:
            index["current_project_id"] = (
                index["projects"][0]["project_id"] if index["projects"] else None
            )
        self._write_index(index)
        return {"deleted_project_id": project_id}

    def get_current_project(self) -> dict[str, Any] | None:
        index = self._read_index()
        project_id = index.get("current_project_id")
        if not project_id:
            return None
        try:
            return self.read_project(project_id)
        except FileNotFoundError:
            index["current_project_id"] = None
            self._write_index(index)
            return None

    def read_project(self, project_id: str) -> dict[str, Any]:
        project_path = self._project_path(project_id)
        if not project_path.exists():
            raise FileNotFoundError(f"project not found: {project_id}")
        return json.loads(project_path.read_text(encoding="utf-8"))

    def create_graph(
        self,
        project_id: str,
        name: str,
        graph_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.read_project(project_id)
        clean_name = name.strip() or "Untitled Graph"
        graph_id = _slug(clean_name) or f"graph-{uuid.uuid4().hex[:8]}"
        graph_id = self._unique_graph_id(project_id, graph_id)
        now = utc_now()
        graph = _strip_graph_view(deepcopy(graph_data)) if graph_data else _blank_graph(graph_id)
        graph["graph_id"] = graph.get("graph_id") or graph_id
        graph_id = _slug(str(graph["graph_id"])) or graph_id
        graph_id = self._unique_graph_id(project_id, graph_id)
        graph["graph_id"] = graph_id
        graph.setdefault("nodes", [])
        graph.setdefault("output_nodes", [])
        graph.setdefault("metadata", {})
        meta = graph["metadata"].setdefault("graphyagent", {})
        meta.setdefault("name", clean_name)
        meta.setdefault("created_at", now)
        meta.setdefault("version", 1)
        meta["project_id"] = project_id
        meta["graph_id"] = graph_id
        meta["updated_at"] = now
        meta.setdefault("files", {"unclassified": [], "nodes": {}})
        meta.setdefault("layout", {})
        graph, _ = correct_graph_dependencies(graph)
        _refresh_node_necessity_audits(graph)

        graph_dir = self._graph_dir(project_id, graph_id)
        (graph_dir / "files" / GRAPH_UNCLASSIFIED).mkdir(parents=True, exist_ok=True)
        (graph_dir / "files" / "nodes").mkdir(parents=True, exist_ok=True)
        self._write_graph(project_id, graph_id, graph)
        self._ensure_graph_assets(project_id, graph_id, graph)

        project["graphs"].append({
            "graph_id": graph_id,
            "name": clean_name,
            "created_at": now,
            "updated_at": now,
        })
        project["current_graph_id"] = graph_id
        self._write_project(project)
        self._sync_project_summary(project)
        return self.read_graph(project_id, graph_id)

    def select_graph(self, project_id: str, graph_id: str) -> dict[str, Any]:
        project = self.read_project(project_id)
        self._ensure_graph_exists(project_id, graph_id)
        project["current_graph_id"] = graph_id
        project["updated_at"] = utc_now()
        self._write_project(project)
        self._sync_project_summary(project)
        return self.read_graph(project_id, graph_id)

    def delete_graph(self, project_id: str, graph_id: str) -> dict[str, Any]:
        project = self.read_project(project_id)
        self._ensure_graph_exists(project_id, graph_id)
        _remove_inside(self._project_dir(project_id), self._graph_dir(project_id, graph_id))
        project["graphs"] = [
            item for item in project.get("graphs", [])
            if item["graph_id"] != graph_id
        ]
        if project.get("current_graph_id") == graph_id:
            project["current_graph_id"] = (
                project["graphs"][0]["graph_id"] if project["graphs"] else None
            )
        project["updated_at"] = utc_now()
        self._write_project(project)
        self._sync_project_summary(project)
        return {"deleted_graph_id": graph_id}

    def read_graph(self, project_id: str, graph_id: str) -> dict[str, Any]:
        graph_path = self._graph_path(project_id, graph_id)
        if not graph_path.exists():
            raise FileNotFoundError(f"graph not found: {graph_id}")
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        return enrich_graph(graph)

    def graph_folder_info(self, project_id: str, graph_id: str) -> dict[str, Any]:
        self._ensure_graph_exists(project_id, graph_id)
        graph_dir = self._graph_dir(project_id, graph_id).resolve()
        return {
            "project_id": project_id,
            "graph_id": graph_id,
            "folder_path": str(graph_dir),
            "graph_json_path": str((graph_dir / "graph.json").resolve()),
            "memory_path": str((graph_dir / "memory").resolve()),
            "files_path": str((graph_dir / "files").resolve()),
        }

    def save_graph(
        self,
        project_id: str,
        graph_id: str,
        graph_data: dict[str, Any],
    ) -> dict[str, Any]:
        old_graph = self.read_graph(project_id, graph_id)
        new_graph = _strip_graph_view(deepcopy(graph_data))
        _normalize_graph_shape(new_graph)
        new_graph["graph_id"] = graph_id
        new_graph.setdefault("metadata", {})
        meta = new_graph["metadata"].setdefault("graphyagent", {})
        old_meta = old_graph.get("metadata", {}).get("graphyagent", {})
        meta["updated_at"] = utc_now()
        meta["version"] = int(old_meta.get("version") or 1) + 1
        meta["project_id"] = project_id
        meta["graph_id"] = graph_id
        meta.setdefault("files", old_meta.get("files", {"unclassified": [], "nodes": {}}))
        meta.setdefault("layout", old_meta.get("layout", {}))
        corrected_graph, corrections = correct_graph_dependencies(new_graph)
        metadata_prune = _prune_graphyagent_node_state(corrected_graph)
        diff = diff_graphs(old_graph, deepcopy(corrected_graph))
        auto_audit = _refresh_node_necessity_audits(corrected_graph)
        if corrections:
            diff.setdefault("dependency_corrections", []).extend(corrections)
        if metadata_prune:
            diff.setdefault("metadata_pruned", metadata_prune)
        diff.setdefault("auto_node_audit", auto_audit)
        self._write_graph(project_id, graph_id, corrected_graph)
        self._ensure_graph_assets(project_id, graph_id, corrected_graph)
        project = self.read_project(project_id)
        for summary in project.get("graphs", []):
            if summary["graph_id"] == graph_id:
                summary["name"] = meta.get("name") or graph_id
                summary["updated_at"] = meta["updated_at"]
        project["updated_at"] = meta["updated_at"]
        self._write_project(project)
        self._sync_project_summary(project)
        return {
            "graph": self.read_graph(project_id, graph_id),
            "diff": diff,
            "ai_suggestions": self.ai_suggestions(corrected_graph),
        }

    def update_node_task(
        self,
        project_id: str,
        graph_id: str,
        node_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        graph = self.read_graph(project_id, graph_id)
        resolved_node_id = _find_node_id(graph, node_id)
        if not resolved_node_id:
            raise FileNotFoundError(f"node not found: {node_id}")
        new_node_id = str(name or resolved_node_id).strip() or resolved_node_id
        node = next(item for item in graph.get("nodes", []) if item.get("id") == resolved_node_id)
        node["id"] = new_node_id
        metadata = node.setdefault("metadata", {})
        metadata["name"] = new_node_id
        if description is not None:
            metadata["description"] = str(description)
        if new_node_id != resolved_node_id:
            for other in graph.get("nodes", []):
                other["depends_on"] = [
                    new_node_id if str(dep) == resolved_node_id else dep
                    for dep in (other.get("depends_on") or [])
                ]
            graph["output_nodes"] = [
                new_node_id if str(item) == resolved_node_id else item
                for item in (graph.get("output_nodes") or [])
            ]
            graph_meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {})
            layout = graph_meta.get("layout")
            if isinstance(layout, dict) and resolved_node_id in layout:
                layout[new_node_id] = layout.pop(resolved_node_id)
            node_files = graph_meta.setdefault("files", {"unclassified": [], "nodes": {}}).setdefault("nodes", {})
            if resolved_node_id in node_files:
                node_files[new_node_id] = node_files.pop(resolved_node_id)
            for spec in (graph.get("initial_artifacts") or {}).values():
                if isinstance(spec, dict) and (spec.get("metadata") or {}).get("node_id") == resolved_node_id:
                    spec.setdefault("metadata", {})["node_id"] = new_node_id
        result = self.save_graph(project_id, graph_id, graph)
        self.append_memory_event(
            project_id,
            graph_id,
            {"type": "node", "name": new_node_id},
            "user",
            (
                "节点任务字段更新。\n"
                f"- 原节点：{resolved_node_id}\n"
                f"- 当前名称：{new_node_id}\n"
                f"- 当前说明：{metadata.get('description') or ''}"
            ),
        )
        return {
            "old_node_id": resolved_node_id,
            "node_id": new_node_id,
            **result,
        }

    def append_memory_event(
        self,
        project_id: str,
        graph_id: str,
        target: dict[str, str],
        role: str,
        content: str,
    ) -> None:
        self._append_memory_event(project_id, graph_id, target, role, content)

    def read_memory(self, project_id: str, graph_id: str, target: dict[str, str]) -> str:
        return self._read_memory(project_id, graph_id, target)

    def import_file(
        self,
        project_id: str,
        scope: str,
        graph_id: str | None = None,
        node_id: str | None = None,
        path: str | None = None,
        name: str | None = None,
        content_base64: str | None = None,
    ) -> dict[str, Any]:
        project = self.read_project(project_id)
        content: bytes
        source_path: str | None = None
        if content_base64:
            content = base64.b64decode(content_base64)
        elif path:
            source = Path(path).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(f"file not found: {source}")
            content = source.read_bytes()
            source_path = str(source)
            name = name or source.name
        else:
            raise ValueError("import_file requires path or contentBase64")
        file_name = _safe_filename(name or "dropped-file")
        file_id = f"file-{hashlib.sha256(content).hexdigest()[:16]}"
        target_dir = self._file_target_dir(project_id, scope, graph_id, node_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{file_id}-{file_name}"
        if not target_path.exists():
            target_path.write_bytes(content)
        file_record = {
            "file_id": file_id,
            "name": file_name,
            "storage_path": str(target_path),
            "source_path": source_path,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "analysis": _analysis_report(file_name, len(content), source_path),
        }

        if scope == PROJECT_UNCLASSIFIED:
            _upsert_file(project.setdefault("files", {}).setdefault(PROJECT_UNCLASSIFIED, []), file_record)
            project["updated_at"] = utc_now()
            self._write_project(project)
            self._sync_project_summary(project)
        else:
            if not graph_id:
                raise ValueError("graph_id is required for graph or node files")
            graph = self.read_graph(project_id, graph_id)
            files_meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {}).setdefault("files", {"unclassified": [], "nodes": {}})
            if scope == GRAPH_UNCLASSIFIED:
                _upsert_file(files_meta.setdefault("unclassified", []), file_record)
            elif scope == NODE_FILES:
                if not node_id:
                    raise ValueError("node_id is required for node files")
                files_meta.setdefault("nodes", {}).setdefault(node_id, [])
                self._auto_audit_node_file(project, project_id, graph_id, graph, node_id, file_record)
                _sync_node_file_input(graph, node_id, file_record)
                _upsert_file(files_meta["nodes"][node_id], file_record)
            else:
                raise ValueError(f"unknown file scope: {scope}")
            self._write_graph(project_id, graph_id, graph)
            self._ensure_graph_assets(project_id, graph_id, graph)
        return file_record

    def move_file(
        self,
        project_id: str,
        file_id: str,
        target_scope: str,
        graph_id: str | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        project = self.read_project(project_id)
        source = self._pop_file(project, project_id, file_id)
        if not source:
            raise FileNotFoundError(f"file not found: {file_id}")
        file_record = source["file"]
        target_dir = self._file_target_dir(project_id, target_scope, graph_id, node_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        old_path = Path(file_record["storage_path"])
        new_path = target_dir / old_path.name
        if old_path.exists() and old_path.resolve() != new_path.resolve():
            shutil.move(str(old_path), str(new_path))
        file_record["storage_path"] = str(new_path)

        if target_scope == PROJECT_UNCLASSIFIED:
            _upsert_file(project.setdefault("files", {}).setdefault(PROJECT_UNCLASSIFIED, []), file_record)
            project["updated_at"] = utc_now()
            self._write_project(project)
        else:
            if not graph_id:
                graph_id = source.get("graph_id")
            if not graph_id:
                raise ValueError("graph_id is required for graph or node file targets")
            graph = self.read_graph(project_id, graph_id)
            files_meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {}).setdefault("files", {"unclassified": [], "nodes": {}})
            if target_scope == GRAPH_UNCLASSIFIED:
                _upsert_file(files_meta.setdefault("unclassified", []), file_record)
            elif target_scope == NODE_FILES:
                if not node_id:
                    raise ValueError("node_id is required for node file targets")
                self._auto_audit_node_file(project, project_id, graph_id, graph, node_id, file_record)
                _sync_node_file_input(graph, node_id, file_record)
                _upsert_file(files_meta.setdefault("nodes", {}).setdefault(node_id, []), file_record)
            else:
                raise ValueError(f"unknown target scope: {target_scope}")
            self._write_graph(project_id, graph_id, graph)
            self._ensure_graph_assets(project_id, graph_id, graph)
            self._write_project(project)
        self._sync_project_summary(project)
        return {
            "file": file_record,
            "from": {k: source.get(k) for k in ("scope", "graph_id", "node_id")},
            "to": {"scope": target_scope, "graph_id": graph_id, "node_id": node_id},
        }

    def delete_file(self, project_id: str, file_id: str) -> dict[str, Any]:
        project = self.read_project(project_id)
        source = self._pop_file(project, project_id, file_id)
        if not source:
            raise FileNotFoundError(f"file not found: {file_id}")
        file_record = source["file"]
        storage_path = Path(file_record.get("storage_path") or "")
        try:
            storage_path.resolve().relative_to(self.workspace_root)
        except (OSError, ValueError):
            pass
        else:
            if storage_path.is_file():
                storage_path.unlink()
        project["updated_at"] = utc_now()
        self._write_project(project)
        self._sync_project_summary(project)
        return {
            "deleted_file_id": file_id,
            "deleted_file": file_record,
            "from": {k: source.get(k) for k in ("scope", "graph_id", "node_id")},
        }

    def link_artifact_to_file_tree(
        self,
        project_id: str,
        artifact_id: str,
        target_scope: str,
        *,
        graph_id: str | None = None,
        node_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        from .artifacts import ArtifactStore

        store = ArtifactStore(self.workspace_root)
        artifact = store.describe_artifact(artifact_id)
        artifact_path = Path(str(artifact.get("uri") or artifact.get("path") or ""))
        if not artifact_path.is_file():
            raise FileNotFoundError(f"artifact file not found: {artifact_id}")
        project = self.read_project(project_id)
        file_name = _safe_filename(name or artifact.get("name") or artifact_path.name)
        file_id = f"file-{str(artifact.get('artifact_id'))[:16]}"
        target_dir = self._file_target_dir(project_id, target_scope, graph_id, node_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{file_id}-{file_name}"
        if not target_path.exists():
            try:
                target_path.symlink_to(artifact_path)
            except OSError:
                shutil.copy2(str(artifact_path), str(target_path))
        source_paths = artifact.get("source_paths") or []
        source_path = source_paths[0] if source_paths else None
        file_record = {
            "file_id": file_id,
            "name": file_name,
            "storage_path": str(target_path),
            "source_path": source_path,
            "size": artifact.get("size") or (artifact.get("metadata") or {}).get("size"),
            "sha256": artifact.get("sha256") or artifact.get("artifact_id"),
            "artifact_id": artifact.get("artifact_id"),
            "artifact_uri": artifact.get("uri") or artifact.get("path"),
            "artifact_type": artifact.get("type"),
            "analysis": _analysis_report(file_name, int(artifact.get("size") or 0), source_path),
        }
        file_record["analysis"]["artifact"] = _artifact_reference_summary(artifact)

        if target_scope == PROJECT_UNCLASSIFIED:
            _upsert_file(project.setdefault("files", {}).setdefault(PROJECT_UNCLASSIFIED, []), file_record)
            project["updated_at"] = utc_now()
            self._write_project(project)
            self._sync_project_summary(project)
        else:
            if not graph_id:
                raise ValueError("graph_id is required for graph or node file targets")
            graph = self.read_graph(project_id, graph_id)
            files_meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {}).setdefault("files", {"unclassified": [], "nodes": {}})
            if target_scope == GRAPH_UNCLASSIFIED:
                _upsert_file(files_meta.setdefault("unclassified", []), file_record)
            elif target_scope == NODE_FILES:
                if not node_id:
                    raise ValueError("node_id is required for node file targets")
                self._auto_audit_node_file(project, project_id, graph_id, graph, node_id, file_record)
                _sync_node_file_input(graph, node_id, file_record)
                _upsert_file(files_meta.setdefault("nodes", {}).setdefault(node_id, []), file_record)
            else:
                raise ValueError(f"unknown target scope: {target_scope}")
            self._write_graph(project_id, graph_id, graph)
            self._ensure_graph_assets(project_id, graph_id, graph)
            project["updated_at"] = utc_now()
            self._write_project(project)
            self._sync_project_summary(project)
        return {
            "file": file_record,
            "artifact": artifact,
            "to": {"scope": target_scope, "graph_id": graph_id, "node_id": node_id},
        }

    def sync_artifact_index(
        self,
        project_id: str,
        *,
        graph_id: str | None = None,
    ) -> dict[str, Any]:
        from .artifacts import ArtifactStore

        store = ArtifactStore(self.workspace_root)
        project = self.read_project(project_id)
        synced: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []

        def sync_record(
            file_record: dict[str, Any],
            scope: str,
            *,
            current_graph_id: str | None,
            current_node_id: str | None,
        ) -> bool:
            path = Path(str(file_record.get("storage_path") or ""))
            if not path.is_file():
                missing.append({
                    "file_id": file_record.get("file_id"),
                    "scope": scope,
                    "graph_id": current_graph_id,
                    "node_id": current_node_id,
                    "storage_path": str(path),
                })
                return False
            artifact = store.register_file(
                path,
                artifact_type=_artifact_type_for_file(file_record),
                metadata={
                    "graphyagent_file_id": file_record.get("file_id"),
                    "project_id": project_id,
                    "graph_id": current_graph_id,
                    "node_id": current_node_id,
                    "scope": scope,
                    "managed_file": True,
                },
                name=file_record.get("name"),
            )
            before = file_record.get("artifact_id")
            file_record["artifact_id"] = artifact.artifact_id
            file_record["artifact_uri"] = artifact.uri
            file_record["artifact_type"] = artifact.type
            file_record["sha256"] = artifact.artifact_id
            file_record["size"] = artifact.metadata.get("size", file_record.get("size"))
            file_record.setdefault("analysis", {})["artifact"] = _artifact_reference_summary(artifact.to_dict())
            synced.append({
                "file_id": file_record.get("file_id"),
                "artifact_id": artifact.artifact_id,
                "scope": scope,
                "graph_id": current_graph_id,
                "node_id": current_node_id,
                "changed": before != artifact.artifact_id,
            })
            return before != artifact.artifact_id

        project_changed = False
        for file_record in project.setdefault("files", {}).setdefault(PROJECT_UNCLASSIFIED, []):
            project_changed = sync_record(file_record, PROJECT_UNCLASSIFIED, current_graph_id=None, current_node_id=None) or project_changed
        if project_changed:
            project["updated_at"] = utc_now()
            self._write_project(project)

        graph_ids = [
            str(item.get("graph_id"))
            for item in project.get("graphs", [])
            if item.get("graph_id") and (not graph_id or str(item.get("graph_id")) == graph_id)
        ]
        for current_graph_id in graph_ids:
            graph = self.read_graph(project_id, current_graph_id)
            files_meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {}).setdefault("files", {"unclassified": [], "nodes": {}})
            graph_changed = False
            for file_record in files_meta.setdefault("unclassified", []):
                graph_changed = sync_record(file_record, GRAPH_UNCLASSIFIED, current_graph_id=current_graph_id, current_node_id=None) or graph_changed
            for current_node_id, files in files_meta.setdefault("nodes", {}).items():
                for file_record in files:
                    graph_changed = sync_record(file_record, NODE_FILES, current_graph_id=current_graph_id, current_node_id=current_node_id) or graph_changed
                    _sync_node_file_input(graph, current_node_id, file_record)
            if graph_changed:
                graph.setdefault("metadata", {}).setdefault("graphyagent", {})["updated_at"] = utc_now()
                self._write_graph(project_id, current_graph_id, graph)
                self._ensure_graph_assets(project_id, current_graph_id, graph)

        if project_changed:
            self._sync_project_summary(self.read_project(project_id))
        return {
            "project_id": project_id,
            "graph_id": graph_id,
            "synced_count": len(synced),
            "missing_count": len(missing),
            "synced": synced,
            "missing": missing,
            "artifact_index_path": str(self.workspace_root / "artifacts" / "index.json"),
        }

    def audit_node_necessity(self, project_id: str, graph_id: str, node_id: str) -> dict[str, Any]:
        graph = self.read_graph(project_id, graph_id)
        resolved_node_id = _find_node_id(graph, node_id)
        if not resolved_node_id:
            raise FileNotFoundError(f"node not found: {node_id}")
        audit = _evaluate_node_necessity(graph, resolved_node_id)
        for node in graph.get("nodes", []):
            if node.get("id") == resolved_node_id:
                metadata = node.setdefault("metadata", {})
                metadata["necessity_audit"] = audit
                break
        result = self.save_graph(project_id, graph_id, graph)
        self._append_memory_event(
            project_id,
            graph_id,
            {"type": "node", "name": resolved_node_id},
            "system",
            _necessity_audit_memory_text(audit),
        )
        return {
            "node_id": resolved_node_id,
            "necessity_audit": audit,
            **result,
        }

    def decompose_node(
        self,
        project_id: str,
        graph_id: str,
        node_id: str,
        child_names: list[str] | None = None,
    ) -> dict[str, Any]:
        graph = self.read_graph(project_id, graph_id)
        resolved_node_id = _find_node_id(graph, node_id)
        if not resolved_node_id:
            raise FileNotFoundError(f"node not found: {node_id}")
        names = [name.strip() for name in (child_names or []) if str(name).strip()]
        if len(names) < 2:
            names = _default_subgraph_nodes(resolved_node_id)
        if not _split_node(graph, resolved_node_id, names):
            raise ValueError(f"failed to decompose node: {resolved_node_id}")
        result = self.save_graph(project_id, graph_id, graph)
        self._append_memory_event(
            project_id,
            graph_id,
            {"type": "graph", "name": graph_id},
            "system",
            f"任务拆解：节点 `{resolved_node_id}` 已拆解为：{', '.join(names)}。",
        )
        return {
            "message": f"已将节点 `{resolved_node_id}` 拆解为 {len(names)} 个子节点。",
            "decomposed_node": resolved_node_id,
            "child_nodes": names,
            **result,
        }

    def decompose_task_to_graph(
        self,
        project_id: str,
        prompt: str,
        *,
        graph_id: str | None = None,
        name: str | None = None,
        create_new_graph: bool = True,
    ) -> dict[str, Any]:
        memory_target, normalized = _parse_memory_prompt(str(prompt or "").strip())
        if not normalized:
            raise ValueError("decompose_task_to_graph requires prompt")
        graph_name = (name or _task_graph_name(normalized)).strip() or "Decomposed Task"
        if create_new_graph or not graph_id:
            graph = build_workflow_graph(
                {
                    "graph_id": _task_graph_id(graph_name, normalized),
                    "context": {},
                    "metadata": {"graphyagent": {"name": graph_name}},
                },
                normalized,
            )
            graph.setdefault("metadata", {}).setdefault("graphyagent", {})["name"] = graph_name
            created = self.create_graph(project_id, graph_name, graph)
            self._append_memory_event(
                project_id,
                created["graph_id"],
                {"type": "graph", "name": created["graph_id"]},
                "system",
                f"任务拆解成图：根据用户描述生成 workflow。\n\n{normalized}",
            )
            return {
                "message": "已根据任务描述创建 workflow 图。",
                "created": True,
                "prompt": normalized,
                "decomposition": _task_graph_summary(created),
                "graph": created,
            }

        graph = self.read_graph(project_id, graph_id)
        graph = build_workflow_graph(graph, normalized)
        graph.setdefault("metadata", {}).setdefault("graphyagent", {})["name"] = graph_name
        result = self.save_graph(project_id, graph_id, graph)
        self._append_memory_event(
            project_id,
            graph_id,
            memory_target if memory_target.get("type") in {"project", "graph"} else {"type": "graph", "name": graph_id},
            "system",
            f"任务拆解成图：当前 workflow 已按用户描述重建。\n\n{normalized}",
        )
        return {
            "message": "已根据任务描述重建当前 workflow 图。",
            "created": False,
            "prompt": normalized,
            "decomposition": _task_graph_summary(result["graph"]),
            **result,
        }

    def record_graph_run(
        self,
        project_id: str,
        graph_id: str,
        run: dict[str, Any],
        *,
        command_record: dict[str, Any] | None = None,
        scope: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        graph = self.read_graph(project_id, graph_id)
        meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {})
        now = utc_now()
        run_record = _graph_run_record(run, command_record, scope)
        meta["latest_run"] = run_record
        history = meta.setdefault("run_history", [])
        history.append(run_record)
        meta["run_history"] = history[-50:]
        meta["updated_at"] = now

        node_traces = _node_run_trace_index(run)
        output_index = _node_output_index_from_run(run)
        node_results = (run.get("final_state") or {}).get("node_results") or {}
        existing_nodes = {str(node.get("id")): node for node in graph.get("nodes", [])}
        latest_runs = meta.setdefault("node_latest_runs", {})
        latest_outputs = meta.setdefault("last_node_outputs", {})

        for node_id, result in node_results.items():
            if node_id not in existing_nodes:
                continue
            node_record = _node_run_record(
                node_id,
                result,
                run_record,
                output_index.get(node_id, []),
                node_traces.get(node_id),
            )
            latest_runs[node_id] = node_record
            latest_outputs[node_id] = node_record["outputs"]
            node_meta = existing_nodes[node_id].setdefault("metadata", {})
            node_meta["latest_run"] = node_record
            node_meta["latest_outputs"] = node_record["outputs"]
            self._append_memory_event(
                project_id,
                graph_id,
                {"type": "node", "name": node_id},
                "system",
                _node_run_memory_text(node_record),
            )

        self._append_memory_event(
            project_id,
            graph_id,
            {"type": "graph", "name": graph_id},
            "system",
            _graph_run_memory_text(run_record, output_index),
        )
        self._write_graph(project_id, graph_id, graph)
        self._ensure_graph_assets(project_id, graph_id, graph)

        project = self.read_project(project_id)
        for summary in project.get("graphs", []):
            if summary["graph_id"] == graph_id:
                summary["updated_at"] = now
                summary["latest_run_status"] = run_record["status"]
                summary["latest_graph_run_id"] = run_record["graph_run_id"]
        project["updated_at"] = now
        self._write_project(project)
        self._sync_project_summary(project)
        return {
            "graph_run": run_record,
            "node_outputs": output_index,
            "graph": self.read_graph(project_id, graph_id),
        }

    def virtual_tree(self) -> dict[str, Any]:
        project = self.get_current_project()
        if not project:
            return {"project": None, "folders": []}
        folders: list[dict[str, Any]] = [{
            "id": PROJECT_UNCLASSIFIED,
            "label": "项目未分类",
            "scope": PROJECT_UNCLASSIFIED,
            "files": project.get("files", {}).get(PROJECT_UNCLASSIFIED, []),
        }]
        current_graph = None
        if project.get("current_graph_id"):
            current_graph = self.read_graph(project["project_id"], project["current_graph_id"])
            graph_files = current_graph.get("metadata", {}).get("graphyagent", {}).get("files", {})
            folders.append({
                "id": GRAPH_UNCLASSIFIED,
                "label": "当前图未分类",
                "scope": GRAPH_UNCLASSIFIED,
                "graph_id": current_graph["graph_id"],
                "files": graph_files.get("unclassified", []),
            })
            node_files = graph_files.get("nodes", {})
            folders.append({
                "id": "nodes",
                "label": "节点文件",
                "scope": NODE_FILES,
                "children": [
                    {
                        "id": node.get("id"),
                        "label": node.get("id"),
                        "scope": NODE_FILES,
                        "graph_id": current_graph["graph_id"],
                        "node_id": node.get("id"),
                        "files": node_files.get(node.get("id"), []),
                    }
                    for node in current_graph.get("nodes", [])
                ],
            })
        return {
            "project": _project_summary(project),
            "graph": _graph_summary(current_graph) if current_graph else None,
            "folders": folders,
        }

    def ai_suggestions(self, graph: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not graph:
            return []
        suggestions = []
        _, corrections = correct_graph_dependencies(graph)
        suggestions.extend(corrections)
        orphan_nodes = [
            node.get("id")
            for node in graph.get("nodes", [])
            if not node.get("depends_on") and node.get("id") not in set(graph.get("output_nodes", []))
        ]
        for node_id in orphan_nodes:
            suggestions.append({
                "type": "review_node",
                "node_id": node_id,
                "message": f"检查 {node_id} 是否应该依赖某个上游节点。",
            })
        graph_files = graph.get("metadata", {}).get("graphyagent", {}).get("files", {})
        if graph_files.get("unclassified"):
            suggestions.append({
                "type": "classify_files",
                "message": "当前图还有未分类文件。明确用途后可拖入对应节点。",
            })
        return suggestions

    def chat_graph(self, project_id: str, graph_id: str, prompt: str) -> dict[str, Any]:
        graph = self.read_graph(project_id, graph_id)
        memory_target, normalized = _parse_memory_prompt(prompt.strip())
        self._append_memory_event(project_id, graph_id, memory_target, "user", normalized)
        llm_edit = _apply_llm_chat_edit(graph, memory_target, normalized)
        if llm_edit:
            if llm_edit.get("changed"):
                result = self.save_graph(project_id, graph_id, graph)
                message = str(llm_edit.get("message") or "图修改已保存，差异如下。")
                self._append_memory_event(project_id, graph_id, memory_target, "assistant", message)
                return {
                    "message": message,
                    "open_canvas": True,
                    "llm_edit": llm_edit.get("plan"),
                    **result,
                }
            message = str(llm_edit.get("message") or "图无变化。")
            self._append_memory_event(project_id, graph_id, memory_target, "assistant", message)
            return {
                "message": message,
                "open_canvas": True,
                "graph": graph,
                "diff": {"summary": "图无变化。"},
                "llm_edit": llm_edit.get("plan"),
            }
        return self._chat_memory_with_llm(project_id, graph_id, graph, memory_target, normalized)

    def _chat_memory_with_llm(
        self,
        project_id: str,
        graph_id: str,
        graph: dict[str, Any],
        target: dict[str, str],
        prompt: str,
    ) -> dict[str, Any]:
        target_type = target.get("type") or "project"
        target_name = target.get("name") or target.get("id") or target_type
        profile = "complex" if target_type in ("graph", "project") else "simple"
        fallback = ["complex"] if target_type == "node" else []
        memory = self._read_memory(project_id, graph_id, target)
        context = _memory_chat_context(graph, target_type, target_name)
        files_prompt = _memory_chat_files_prompt(
            self.virtual_tree(),
            target_type,
            target_name,
            workspace_root=self.workspace_root,
        )
        full_prompt = f"{context}{files_prompt}\n\n## 既有记忆\n{memory[-6000:]}\n\n## 用户问题\n{prompt}"

        try:
            result = chat_completion(
                full_prompt,
                profile=profile,
                fallback_profiles=fallback,
                system="你是 GraphyAgent 的智能助手。基于当前图、节点、已有记忆以及关联文件内容，回答用户的问题或直接处理数据。如果用户提供关联文件并请求对文件内容进行总结、分析或格式转换（例如整理为 CSV），请直接使用文件内容进行计算、提取并给出完整的回答或表格，不要拒绝处理文件。",
                max_tokens=resolve_max_tokens(profile=profile, prompt=full_prompt),
                temperature=0.2,
            )
        except LLMCallError as exc:
            if target_type == "node":
                return {
                    "message": "节点简单 API 和复杂 API 都调用失败。是否允许将该节点拆解为子图后再继续？",
                    "open_canvas": True,
                    "graph": graph,
                    "diff": {"summary": "图无变化。"},
                    "requires_decomposition": True,
                    "decomposition_node": target_name,
                    "error": str(exc),
                }
            return {
                "message": f"记忆 API 调用失败：{exc}",
                "open_canvas": True,
                "graph": graph,
                "diff": {"summary": "图无变化。"},
            }
        self._append_memory_event(project_id, graph_id, target, "assistant", result["text"])
        return {
            "message": result["text"],
            "open_canvas": True,
            "graph": graph,
            "diff": {"summary": "图无变化。"},
            "llm": {
                "profile": result["profile"],
                "api_format": result["api_format"],
                "model": result["model"],
            },
        }

    def _append_memory_event(
        self,
        project_id: str,
        graph_id: str,
        target: dict[str, str],
        role: str,
        content: str,
    ) -> None:
        if not content.strip():
            return
        path = self._memory_path(project_id, graph_id, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            title = target.get("name") or target.get("type") or "memory"
            path.write_text(f"# 记忆：{title}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"## {utc_now()} {role}\n{content.strip()}\n\n")

    def _read_memory(self, project_id: str, graph_id: str, target: dict[str, str]) -> str:
        path = self._memory_path(project_id, graph_id, target)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def _memory_path(self, project_id: str, graph_id: str, target: dict[str, str]) -> Path:
        target_type = target.get("type") or "project"
        if target_type == "node":
            node_name = target.get("name") or target.get("id") or "node"
            return self._graph_dir(project_id, graph_id) / "memory" / "nodes" / f"{_node_asset_name(node_name)}.md"
        if target_type == "graph":
            return self._graph_dir(project_id, graph_id) / "memory" / "graph.md"
        return self._project_dir(project_id) / "memory" / "project.md"

    def _pop_file(self, project: dict[str, Any], project_id: str, file_id: str) -> dict[str, Any] | None:
        project_files = project.setdefault("files", {}).setdefault(PROJECT_UNCLASSIFIED, [])
        found = _pop_from_list(project_files, file_id)
        if found:
            return {"scope": PROJECT_UNCLASSIFIED, "file": found}
        for graph_summary in project.get("graphs", []):
            graph_id = graph_summary["graph_id"]
            graph = self.read_graph(project_id, graph_id)
            files_meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {}).setdefault("files", {"unclassified": [], "nodes": {}})
            found = _pop_from_list(files_meta.setdefault("unclassified", []), file_id)
            if found:
                self._write_graph(project_id, graph_id, graph)
                self._ensure_graph_assets(project_id, graph_id, graph)
                return {"scope": GRAPH_UNCLASSIFIED, "graph_id": graph_id, "file": found}
            for node_id, files in list(files_meta.setdefault("nodes", {}).items()):
                found = _pop_from_list(files, file_id)
                if found:
                    _unsync_node_file_input(graph, node_id, found)
                    self._write_graph(project_id, graph_id, graph)
                    self._ensure_graph_assets(project_id, graph_id, graph)
                    return {"scope": NODE_FILES, "graph_id": graph_id, "node_id": node_id, "file": found}
        return None

    def _file_target_dir(
        self,
        project_id: str,
        scope: str,
        graph_id: str | None,
        node_id: str | None,
    ) -> Path:
        project_dir = self._project_dir(project_id)
        if scope == PROJECT_UNCLASSIFIED:
            return project_dir / "files" / PROJECT_UNCLASSIFIED
        if scope == GRAPH_UNCLASSIFIED:
            if not graph_id:
                raise ValueError("graph_id is required")
            return self._graph_dir(project_id, graph_id) / "files" / GRAPH_UNCLASSIFIED
        if scope == NODE_FILES:
            if not graph_id or not node_id:
                raise ValueError("graph_id and node_id are required")
            return self._graph_dir(project_id, graph_id) / "files" / "nodes" / _slug(node_id)
        raise ValueError(f"unknown scope: {scope}")

    def _read_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _write_index(self, index: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    def _project_dir(self, project_id: str) -> Path:
        return self.projects_root / _slug(project_id)

    def _project_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "project.json"

    def _graph_dir(self, project_id: str, graph_id: str) -> Path:
        return self._project_dir(project_id) / "graphs" / _slug(graph_id)

    def _graph_path(self, project_id: str, graph_id: str) -> Path:
        return self._graph_dir(project_id, graph_id) / "graph.json"

    def _write_project(self, project: dict[str, Any]) -> None:
        project_path = self._project_path(project["project_id"])
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_path.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_graph(self, project_id: str, graph_id: str, graph: dict[str, Any]) -> None:
        graph_path = self._graph_path(project_id, graph_id)
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        clean_graph = _strip_graph_view(deepcopy(graph))
        graph_path.write_text(json.dumps(clean_graph, indent=2, ensure_ascii=False), encoding="utf-8")

    def _ensure_graph_assets(self, project_id: str, graph_id: str, graph: dict[str, Any]) -> None:
        graph_dir = self._graph_dir(project_id, graph_id)
        memory_dir = graph_dir / "memory"
        module_dir = graph_dir / "modules"
        node_memory_dir = memory_dir / "nodes"
        node_module_dir = module_dir / "nodes"
        for path in (memory_dir, module_dir, node_memory_dir, node_module_dir):
            path.mkdir(parents=True, exist_ok=True)

        graph_name = graph.get("metadata", {}).get("graphyagent", {}).get("name") or graph_id
        graph_meta = graph.get("metadata", {}).get("graphyagent", {})
        try:
            project = self.read_project(project_id)
        except FileNotFoundError:
            project = {"files": {PROJECT_UNCLASSIFIED: []}}
        file_index = _graph_file_index(project, graph)
        (module_dir / "file_index.json").write_text(
            json.dumps(file_index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _write_if_missing(
            memory_dir / "graph.md",
            f"# 图记忆：{graph_name}\n\n",
        )
        (module_dir / "graph_module.json").write_text(
            json.dumps(
                {
                    "graph_id": graph_id,
                    "name": graph_name,
                    "node_count": len(graph.get("nodes", [])),
                    "output_nodes": graph.get("output_nodes", []),
                    "memory_path": str(memory_dir / "graph.md"),
                    "file_index_path": str(module_dir / "file_index.json"),
                    "file_count": len(file_index),
                    "audit_summary": _file_index_audit_summary(file_index),
                    "latest_run": graph_meta.get("latest_run"),
                    "run_history": graph_meta.get("run_history", [])[-10:],
                    "node_latest_runs": graph_meta.get("node_latest_runs", {}),
                    "last_node_outputs": graph_meta.get("last_node_outputs", {}),
                    "updated_at": utc_now(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        valid_node_modules = {
            f"{_node_asset_name(str(node.get('id') or 'node'))}.json"
            for node in graph.get("nodes", [])
        }
        for stale in node_module_dir.glob("*.json"):
            if stale.name not in valid_node_modules:
                stale.unlink()
        for node in graph.get("nodes", []):
            node_id = str(node.get("id") or "node")
            asset_name = _node_asset_name(node_id)
            node_files = _node_file_records(graph, node_id)
            node_meta = node.get("metadata") or {}
            _write_if_missing(
                node_memory_dir / f"{asset_name}.md",
                f"# 节点记忆：{node_id}\n\n",
            )
            (node_module_dir / f"{asset_name}.json").write_text(
                json.dumps(
                    {
                        "node_id": node_id,
                        "task_type": node.get("task_type"),
                        "depends_on": node.get("depends_on") or [],
                        "inputs": node.get("inputs") or {},
                        "output_roles": node.get("output_roles") or {},
                        "executor": node.get("executor") or {},
                        "metadata": node_meta,
                        "task_name": node_meta.get("name") or node_meta.get("title") or node_id,
                        "task_description": node_meta.get("description"),
                        "memory_path": str(node_memory_dir / f"{asset_name}.md"),
                        "files": node_files,
                        "audit_summary": _node_files_audit_summary(node_files),
                        "latest_run": graph_meta.get("node_latest_runs", {}).get(node_id)
                        or node_meta.get("latest_run"),
                        "latest_outputs": graph_meta.get("last_node_outputs", {}).get(node_id)
                        or node_meta.get("latest_outputs", []),
                        "updated_at": utc_now(),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    def _auto_audit_node_file(
        self,
        project: dict[str, Any],
        project_id: str,
        graph_id: str,
        graph: dict[str, Any],
        node_id: str,
        file_record: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not _is_auditable_dataset_file(file_record):
            return None

        from ..data_audit import audit_dataset, write_audit_outputs

        reused_audit = _completed_audit_for_file(project, graph, file_record)
        if reused_audit:
            audit_meta = deepcopy(reused_audit)
            audit_meta.update({
                "status": "completed",
                "automatic": True,
                "trigger": "node_file_assigned",
                "reused": True,
                "reused_at": utc_now(),
                "project_id": project_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "dataset_path": file_record.get("storage_path"),
            })
            analysis = file_record.setdefault("analysis", {})
            analysis["audit"] = audit_meta
            analysis["summary"] = _audit_summary_text(file_record["name"], audit_meta)
            self._append_memory_event(
                project_id,
                graph_id,
                {"type": "node", "name": node_id},
                "system",
                _node_audit_reuse_memory_text(file_record, audit_meta),
            )
            return audit_meta

        node = next((item for item in graph.get("nodes", []) if item.get("id") == node_id), {})
        audit_dir = (
            self._graph_dir(project_id, graph_id)
            / "audits"
            / "nodes"
            / _node_asset_name(node_id)
            / str(file_record["file_id"])
        )
        metadata_file = self._find_audit_metadata_file(project, graph, exclude_file_id=file_record["file_id"])
        metadata_path = metadata_file.get("storage_path") if metadata_file else None
        analysis = file_record.setdefault("analysis", {})
        audit_meta: dict[str, Any] = {
            "status": "running",
            "automatic": True,
            "trigger": "node_file_assigned",
            "audited_at": utc_now(),
            "project_id": project_id,
            "graph_id": graph_id,
            "node_id": node_id,
            "dataset_path": file_record.get("storage_path"),
            "metadata_path": metadata_path,
            "output_dir": str(audit_dir),
        }
        analysis["audit"] = audit_meta

        try:
            report = audit_dataset(
                file_record["storage_path"],
                metadata_path=metadata_path,
                metadata={
                    "task_spec": {
                        "intended_use": "模型后训练数据节点输入",
                        "graph_id": graph_id,
                        "node_id": node_id,
                        "node_task_type": node.get("task_type"),
                        "node_description": (node.get("metadata") or {}).get("description"),
                    },
                    "graphyagent_context": {
                        "project_id": project_id,
                        "graph_name": graph.get("metadata", {}).get("graphyagent", {}).get("name"),
                        "node_inputs": node.get("inputs") or {},
                        "node_outputs": node.get("output_roles") or {},
                    },
                },
            )
            paths = write_audit_outputs(report, audit_dir)
            audit_meta.update(_audit_record_from_report(report, paths))
            self._write_audit_llm_summary(audit_meta, report, audit_dir)
            analysis["summary"] = _audit_summary_text(file_record["name"], audit_meta)
            self._append_memory_event(
                project_id,
                graph_id,
                {"type": "node", "name": node_id},
                "system",
                _node_audit_memory_text(file_record, audit_meta),
            )
        except Exception as exc:  # noqa: BLE001
            audit_meta.update({
                "status": "failed",
                "error": str(exc),
                "failed_at": utc_now(),
            })
            analysis["summary"] = f"{file_record['name']} 自动审计失败：{exc}"
            self._append_memory_event(
                project_id,
                graph_id,
                {"type": "node", "name": node_id},
                "system",
                f"自动数据审计失败：文件 `{file_record['name']}`，错误：{exc}",
            )
        return audit_meta

    def _write_audit_llm_summary(
        self,
        audit_meta: dict[str, Any],
        report: dict[str, Any],
        audit_dir: Path,
    ) -> None:
        prompt_payload = json.dumps(report["llm_summary_input"], ensure_ascii=False, indent=2)
        prompt = (
            "你是 GraphyAgent 的数据质量审计总结助手。只能基于下面 JSON 结构化证据作答，"
            "不得补充未给出的事实，不得把单一异常直接断言为造假。请用中文输出：\n"
            "1. 事实证据；2. 风险推断；3. 证据限制；4. 是否适合进入模型后训练；"
            "5. 隔离、去重、补元数据或人工复核动作。\n\n"
            f"{prompt_payload}"
        )
        summary_path = audit_dir / "llm_summary.md"
        try:
            result = chat_completion(
                prompt,
                profile="complex",
                system="你只能总结结构化审计证据，必须区分事实、推断、限制和建议。",
                max_tokens=1600,
                temperature=0.1,
            )
            summary_path.write_text(result["text"], encoding="utf-8")
            audit_meta["llm_summary"] = {
                "status": "completed",
                "profile": result["profile"],
                "api_format": result["api_format"],
                "model": result["model"],
                "path": str(summary_path),
            }
        except LLMCallError as exc:
            summary_path.write_text(
                "LLM 总结失败，但本地审计报告已生成。\n\n"
                f"错误：{exc}\n",
                encoding="utf-8",
            )
            audit_meta["llm_summary"] = {
                "status": "failed",
                "profile": "complex",
                "error": str(exc),
                "path": str(summary_path),
            }

    def _find_audit_metadata_file(
        self,
        project: dict[str, Any],
        graph: dict[str, Any],
        *,
        exclude_file_id: str,
    ) -> dict[str, Any] | None:
        candidates = []
        initial = graph.get("initial_artifacts") or {}
        for alias, spec in initial.items():
            path = spec if isinstance(spec, str) else spec.get("path")
            if path:
                candidates.append({"file_id": f"initial:{alias}", "name": str(alias), "storage_path": str(path)})
        candidates.extend(_iter_graph_file_records(project, graph))
        for item in candidates:
            if item.get("file_id") == exclude_file_id:
                continue
            if _looks_like_metadata_file(item):
                return item
        return None

    def _sync_project_summary(self, project: dict[str, Any]) -> None:
        index = self._read_index()
        summaries = index.get("projects", [])
        summary = _project_summary(project)
        for idx, item in enumerate(summaries):
            if item["project_id"] == project["project_id"]:
                summaries[idx] = summary
                break
        else:
            summaries.append(summary)
        index["projects"] = summaries
        if not index.get("current_project_id"):
            index["current_project_id"] = project["project_id"]
        self._write_index(index)

    def _unique_project_id(self, project_id: str) -> str:
        existing = {item["project_id"] for item in self._read_index().get("projects", [])}
        return _unique_id(project_id, existing)

    def _unique_graph_id(self, project_id: str, graph_id: str) -> str:
        project_path = self._project_path(project_id)
        if not project_path.exists():
            return graph_id
        existing = {item["graph_id"] for item in self.read_project(project_id).get("graphs", [])}
        return _unique_id(graph_id, existing)

    def _ensure_graph_exists(self, project_id: str, graph_id: str) -> None:
        if not self._graph_path(project_id, graph_id).exists():
            raise FileNotFoundError(f"graph not found: {graph_id}")


def enrich_graph(graph: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(graph)
    try:
        config = GraphConfig.from_dict(enriched)
        state = GraphState(context=config.context, experiment=config.experiment)
        enriched["route_preview"] = {
            node.node_id: route_model(config, node, state).to_dict()
            for node in config.nodes
        }
    except Exception:
        enriched["route_preview"] = {}
    enriched["edges"] = graph_edges(enriched)
    return enriched


def _strip_graph_view(graph: dict[str, Any]) -> dict[str, Any]:
    graph.pop("route_preview", None)
    graph.pop("edges", None)
    return graph


def _normalize_graph_shape(graph: dict[str, Any]) -> None:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        graph["nodes"] = []
        nodes = graph["nodes"]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("id") is not None:
            node["id"] = str(node.get("id"))
        deps = node.get("depends_on")
        if deps is None:
            node["depends_on"] = []
        elif isinstance(deps, str):
            node["depends_on"] = [deps] if deps else []
        elif isinstance(deps, list):
            node["depends_on"] = [str(dep) for dep in deps if str(dep)]
        else:
            try:
                node["depends_on"] = [str(dep) for dep in list(deps) if str(dep)]
            except TypeError:
                node["depends_on"] = [str(deps)] if str(deps) else []
    outputs = graph.get("output_nodes")
    if outputs is None:
        graph["output_nodes"] = []
    elif isinstance(outputs, str):
        graph["output_nodes"] = [outputs] if outputs else []
    elif isinstance(outputs, list):
        graph["output_nodes"] = [str(item) for item in outputs if str(item)]
    else:
        try:
            graph["output_nodes"] = [str(item) for item in list(outputs) if str(item)]
        except TypeError:
            graph["output_nodes"] = [str(outputs)] if str(outputs) else []


def _prune_graphyagent_node_state(graph: dict[str, Any]) -> dict[str, Any]:
    node_ids = {
        str(node.get("id"))
        for node in graph.get("nodes", [])
        if isinstance(node, dict) and node.get("id")
    }
    meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {})
    pruned: dict[str, Any] = {}

    files_meta = meta.setdefault("files", {"unclassified": [], "nodes": {}})
    if not isinstance(files_meta, dict):
        files_meta = {"unclassified": [], "nodes": {}}
        meta["files"] = files_meta
    unclassified = files_meta.setdefault("unclassified", [])
    if not isinstance(unclassified, list):
        unclassified = []
        files_meta["unclassified"] = unclassified
    node_files = files_meta.setdefault("nodes", {})
    if not isinstance(node_files, dict):
        node_files = {}
        files_meta["nodes"] = node_files

    stale_file_nodes: list[str] = []
    moved_file_count = 0
    for node_id in list(node_files):
        if str(node_id) in node_ids:
            continue
        files = node_files.pop(node_id) or []
        stale_file_nodes.append(str(node_id))
        for file_record in files:
            if not isinstance(file_record, dict):
                continue
            _unsync_node_file_input(graph, str(node_id), file_record)
            _upsert_file(unclassified, file_record)
            moved_file_count += 1
    if stale_file_nodes:
        pruned["stale_node_file_folders"] = stale_file_nodes
        pruned["moved_files_to_graph_unclassified"] = moved_file_count

    for key, out_key in [
        ("layout", "stale_layout_nodes"),
        ("node_latest_runs", "stale_latest_run_nodes"),
        ("last_node_outputs", "stale_output_nodes"),
    ]:
        mapping = meta.get(key)
        if not isinstance(mapping, dict):
            continue
        stale = [str(node_id) for node_id in list(mapping) if str(node_id) not in node_ids]
        for node_id in stale:
            mapping.pop(node_id, None)
        if stale:
            pruned[out_key] = stale

    initial_artifacts = graph.get("initial_artifacts")
    if isinstance(initial_artifacts, dict):
        stale_aliases: list[str] = []
        for alias, spec in list(initial_artifacts.items()):
            metadata = spec.get("metadata") if isinstance(spec, dict) else None
            node_id = str((metadata or {}).get("node_id") or "")
            if node_id and node_id not in node_ids:
                initial_artifacts.pop(alias, None)
                stale_aliases.append(str(alias))
        if stale_aliases:
            pruned["stale_initial_artifact_aliases"] = stale_aliases
    return pruned


def graph_edges(graph: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "source": str(edge.get("source_node_id") or ""),
            "target": str(edge.get("target_node_id") or ""),
        }
        for edge in normalized_graph_edges(graph)
        if edge.get("source_node_id") and edge.get("target_node_id")
    ]


def _strip_memory_prefix(prompt: str) -> str:
    return re.sub(r"^【[^】]+】\s*", "", prompt).strip()


def _parse_memory_prompt(prompt: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^【(?P<label>项目|图|节点|文件)记忆：(?P<name>[^】]+)】\s*(?P<body>.*)$", prompt, re.S)
    if not match:
        return {"type": "project", "name": "项目"}, prompt.strip()
    label = match.group("label")
    target_type = {
        "项目": "project",
        "图": "graph",
        "节点": "node",
        "文件": "file",
    }.get(label, "project")
    name = match.group("name").strip()
    return {"type": target_type, "id": name, "name": name}, match.group("body").strip()


def _memory_chat_context(graph: dict[str, Any], target_type: str, target_name: str) -> str:
    nodes = graph.get("nodes", [])
    node = _find_node_id(graph, target_name)
    if node:
        node_data = next((item for item in nodes if item.get("id") == node), {})
    else:
        node_data = {}
    graph_summary = {
        "graph_id": graph.get("graph_id"),
        "graph_name": graph.get("metadata", {}).get("graphyagent", {}).get("name"),
        "target_type": target_type,
        "target_name": target_name,
        "node_count": len(nodes),
        "nodes": [
            {
                "id": item.get("id"),
                "task_type": item.get("task_type"),
                "depends_on": item.get("depends_on") or [],
            }
            for item in nodes
        ],
        "current_node": node_data,
    }
    return "## 当前图上下文\n" + json.dumps(graph_summary, ensure_ascii=False, indent=2)


def _memory_chat_files_prompt(
    tree: dict[str, Any],
    target_type: str,
    target_name: str,
    *,
    workspace_root: Path,
) -> str:
    records: list[dict[str, Any]] = []
    seen_file_ids: set[str] = set()
    for folder in tree.get("folders", []):
        folder_id = folder.get("id")
        if folder_id == "nodes":
            for child in folder.get("children", []):
                if target_type == "node" and child.get("node_id") != target_name:
                    continue
                if target_type not in {"node", "graph", "project"}:
                    continue
                _extend_unique_files(records, seen_file_ids, child.get("files") or [])
        elif folder_id == GRAPH_UNCLASSIFIED and target_type in {"graph", "project"}:
            _extend_unique_files(records, seen_file_ids, folder.get("files") or [])
        elif folder_id == PROJECT_UNCLASSIFIED and target_type in {"graph", "project"}:
            _extend_unique_files(records, seen_file_ids, folder.get("files") or [])
    if not records:
        return ""
    max_files = _positive_int_env("GRAPHYAGENT_CHAT_FILE_LIMIT") or 12
    max_chars = _positive_int_env("GRAPHYAGENT_CHAT_FILE_CONTEXT_CHARS") or 120_000
    contexts = [
        summarize_file_for_prompt(record, max_chars=max_chars, workspace_root=workspace_root)
        for record in records[:max_files]
    ]
    suffix = ""
    if len(records) > max_files:
        suffix = f"\n\n另有 {len(records) - max_files} 个关联文件未放入本次上下文。"
    return "\n\n## 关联文件内容\n" + "\n\n".join(contexts) + suffix


def _extend_unique_files(
    records: list[dict[str, Any]],
    seen_file_ids: set[str],
    files: list[dict[str, Any]],
) -> None:
    for item in files:
        file_id = str(item.get("file_id") or item.get("storage_path") or item.get("path") or "")
        if not file_id or file_id in seen_file_ids:
            continue
        seen_file_ids.add(file_id)
        records.append(item)


def _positive_int_env(name: str) -> int | None:
    import os

    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _default_subgraph_nodes(node_id: str) -> list[str]:
    return [
        f"{node_id} 输入准备",
        f"{node_id} 子任务执行",
        f"{node_id} 结果校验",
        f"{node_id} 输出汇总",
    ]


def _task_graph_name(prompt: str) -> str:
    compact = re.sub(r"\s+", " ", prompt).strip(" ，。:：")
    if not compact:
        return "Decomposed Task"
    if len(compact) <= 32:
        return compact
    return compact[:32].rstrip(" ，。:：") + "..."


def _task_graph_id(name: str, prompt: str) -> str:
    slug = _slug(name)
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    if not slug or len(slug) < 8:
        return f"task-graph-{digest}"
    return f"{slug[:62].rstrip('-.')}-{digest}"


def _task_graph_summary(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") or []
    edge_count = sum(len(node.get("depends_on") or []) for node in nodes)
    parallel_roots = [
        str(node.get("id"))
        for node in nodes
        if not node.get("depends_on")
    ]
    return {
        "graph_id": graph.get("graph_id"),
        "name": graph.get("metadata", {}).get("graphyagent", {}).get("name"),
        "node_count": len(nodes),
        "edge_count": edge_count,
        "output_nodes": list(graph.get("output_nodes") or []),
        "parallel_roots": parallel_roots,
        "task_types": sorted({str(node.get("task_type") or "task") for node in nodes}),
    }


def _apply_llm_chat_edit(
    graph: dict[str, Any],
    target: dict[str, str],
    prompt: str,
) -> dict[str, Any] | None:
    target_type = target.get("type") or "project"
    if target_type not in {"graph", "node"}:
        return None
    profile = "complex" if target_type == "graph" else "simple"
    fallback = ["complex"] if target_type == "node" else []
    try:
        result = chat_completion(
            _llm_edit_prompt(graph, target, prompt),
            profile=profile,
            fallback_profiles=fallback,
            system=(
                "你是 GraphyAgent 的图编辑规划器。你只输出严格 JSON，不输出 Markdown。"
                "你必须基于给定 current_graph，不要编造运行结果。"
            ),
            max_tokens=4200,
            temperature=0.0,
        )
        plan = _extract_json_object(result["text"])
    except (LLMCallError, ValueError, json.JSONDecodeError, TypeError):
        return None

    intent = str(plan.get("intent") or "answer").strip()
    before = _graph_edit_signature(graph)
    message = str(plan.get("message") or "").strip()
    if intent == "answer":
        return {
            "changed": False,
            "message": message or "我已查看当前图，没有需要修改的结构。",
            "plan": plan,
        }

    if target_type == "node":
        if intent == "edit_graph":
            return {
                "changed": False,
                "message": "当前是节点对话，我只会修改该节点的信息；如果要改边或重排整个图，请先点击图名切换到图对话。",
                "plan": plan,
            }
        node_message = _apply_llm_node_update(graph, target, plan)
        if not node_message:
            return None
        return {
            "changed": _graph_edit_signature(graph) != before,
            "message": message or node_message,
            "plan": plan,
        }

    if intent == "edit_node" and plan.get("node_update"):
        node_message = _apply_llm_node_update(graph, target, plan)
        if not node_message:
            return None
        return {
            "changed": _graph_edit_signature(graph) != before,
            "message": message or node_message,
            "plan": plan,
        }

    if intent != "edit_graph":
        return None
    graph_message = _apply_llm_graph_structure(graph, plan, prompt)
    if not graph_message:
        return None
    return {
        "changed": _graph_edit_signature(graph) != before,
        "message": message or graph_message,
        "plan": plan,
    }


def _llm_edit_prompt(graph: dict[str, Any], target: dict[str, str], prompt: str) -> str:
    target_type = target.get("type") or "project"
    schema = {
        "intent": "answer | edit_node | edit_graph",
        "message": "给用户看的中文反馈",
        "node_update": {
            "id": "要修改的节点 ID",
            "new_id": "可选；节点新名称",
            "task_type": "可选；任务类型",
            "description": "可选；节点任务说明",
        },
        "graph": {
            "nodes": [
                {
                    "id": "节点 ID",
                    "task_type": "任务类型",
                    "description": "节点任务说明",
                    "depends_on": ["上游节点 ID"],
                }
            ],
            "output_nodes": ["最终输出节点 ID"],
        },
    }
    rules = [
        "只返回 JSON object，不要 Markdown 代码块。",
        "如果用户只是提问或聊天，intent=answer。",
        "如果 target.type=node，只允许 intent=answer 或 edit_node；不要改边、不要改其他节点、不要返回 edit_graph。",
        "如果 target.type=graph，可以返回 edit_graph；此时必须返回完整 graph.nodes 和 graph.output_nodes。",
        "edit_graph 必须保留所有用户未要求删除的节点；只根据用户指令增删改节点和依赖。",
        "表达“A 在 B/C/D 之前”“A 不要和 B/C/D 并行”时，新的 graph 中 B/C/D 的 depends_on 必须包含 A。",
        "所有 depends_on 都必须引用 graph.nodes 中存在的节点 ID，不能自依赖。",
        "不要声称已经运行节点或生成输出文件。",
    ]
    payload = {
        "target": {
            "type": target_type,
            "name": target.get("name") or target.get("id"),
        },
        "current_graph": _compact_graph_structure(graph),
        "user_instruction": prompt,
        "required_json_schema": schema,
        "rules": rules,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _compact_graph_structure(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "graph_id": graph.get("graph_id"),
        "graph_name": graph.get("metadata", {}).get("graphyagent", {}).get("name"),
        "output_nodes": list(graph.get("output_nodes") or []),
        "nodes": [
            {
                "id": str(node.get("id") or ""),
                "task_type": str(node.get("task_type") or "task"),
                "description": str((node.get("metadata") or {}).get("description") or "")[:800],
                "depends_on": [str(dep) for dep in (node.get("depends_on") or [])],
                "executor_type": str((node.get("executor") or {}).get("type") or "noop"),
            }
            for node in graph.get("nodes", [])
            if node.get("id")
        ],
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(clean[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM edit plan is not an object")
    return parsed


def _apply_llm_graph_structure(graph: dict[str, Any], plan: dict[str, Any], prompt: str) -> str | None:
    proposed = plan.get("graph")
    if not isinstance(proposed, dict):
        return None
    raw_nodes = proposed.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return None
    old_nodes = [node for node in graph.get("nodes", []) if node.get("id")]
    if len(raw_nodes) != len(old_nodes) and not _prompt_allows_node_count_change(prompt):
        return None

    ids: list[str] = []
    normalized_nodes: list[dict[str, Any]] = []
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            return None
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id or node_id in ids:
            return None
        deps = [str(dep).strip() for dep in (raw_node.get("depends_on") or []) if str(dep).strip()]
        if node_id in deps:
            return None
        ids.append(node_id)
        normalized_nodes.append({
            "id": node_id,
            "task_type": str(raw_node.get("task_type") or "task").strip() or "task",
            "description": str(raw_node.get("description") or "").strip(),
            "depends_on": deps,
        })
    id_set = set(ids)
    if any(dep not in id_set for node in normalized_nodes for dep in node["depends_on"]):
        return None
    if _graph_structure_has_cycle(normalized_nodes):
        return None

    old_by_id = {str(node.get("id")): node for node in old_nodes}
    new_nodes: list[dict[str, Any]] = []
    for item in normalized_nodes:
        existing = deepcopy(old_by_id.get(item["id"]))
        if existing:
            node = existing
            node["task_type"] = item["task_type"]
        else:
            node = _workflow_node(item["id"], item["task_type"], item["description"] or "对话新增节点。")
        node["id"] = item["id"]
        node["depends_on"] = item["depends_on"]
        if item["description"]:
            node.setdefault("metadata", {})["description"] = item["description"]
            if str((node.get("executor") or {}).get("type") or "").lower() == "llm":
                executor = dict(node.get("executor") or {})
                executor["prompt"] = _workflow_node(
                    item["id"],
                    item["task_type"],
                    item["description"],
                )["executor"]["prompt"]
                node["executor"] = executor
        new_nodes.append(node)

    output_nodes = [
        str(node_id).strip()
        for node_id in (proposed.get("output_nodes") or [])
        if str(node_id).strip() in id_set
    ]
    if not output_nodes:
        sources = {dep for node in normalized_nodes for dep in node["depends_on"]}
        output_nodes = [node["id"] for node in normalized_nodes if node["id"] not in sources] or [normalized_nodes[-1]["id"]]
    graph["nodes"] = new_nodes
    graph["output_nodes"] = output_nodes
    _unlock_auto_layout(graph)
    return "已根据 LLM 返回的新图结构更新当前图。"


def _apply_llm_node_update(graph: dict[str, Any], target: dict[str, str], plan: dict[str, Any]) -> str | None:
    update = plan.get("node_update")
    if not isinstance(update, dict):
        return None
    target_node_id = _find_node_id(graph, target.get("name") or target.get("id"))
    requested_id = _find_node_id(graph, update.get("id")) if update.get("id") else None
    node_id = target_node_id or requested_id
    if not node_id:
        return None
    if target.get("type") == "node" and target_node_id:
        node_id = target_node_id
    node = next((item for item in graph.get("nodes", []) if item.get("id") == node_id), None)
    if not node:
        return None

    new_id = str(update.get("new_id") or "").strip()
    if new_id and new_id != node_id:
        if not _rename_node(graph, node_id, new_id):
            return None
        node_id = new_id
        node = next((item for item in graph.get("nodes", []) if item.get("id") == node_id), None)
        if not node:
            return None
    task_type = str(update.get("task_type") or "").strip()
    if task_type:
        node["task_type"] = task_type
    description = str(update.get("description") or "").strip()
    if description:
        node.setdefault("metadata", {})["description"] = description
        if str((node.get("executor") or {}).get("type") or "").lower() == "llm":
            executor = dict(node.get("executor") or {})
            executor["prompt"] = _workflow_node(
                node_id,
                str(node.get("task_type") or "task"),
                description,
            )["executor"]["prompt"]
            node["executor"] = executor
    return f"已更新节点 `{node_id}` 的信息。"


def _prompt_allows_node_count_change(prompt: str) -> bool:
    return any(term in prompt for term in ["新增", "添加", "创建", "生成", "删除", "移除", "去掉", "拆分", "拆解", "合并", "重建"])


def _graph_structure_has_cycle(nodes: list[dict[str, Any]]) -> bool:
    by_id = {node["id"]: node for node in nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visited:
            return False
        if node_id in visiting:
            return True
        visiting.add(node_id)
        for dep in by_id[node_id]["depends_on"]:
            if dep in by_id and visit(dep):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node["id"]) for node in nodes)


def _graph_edit_signature(graph: dict[str, Any]) -> str:
    compact = {
        "nodes": [
            {
                "id": str(node.get("id") or ""),
                "task_type": str(node.get("task_type") or ""),
                "depends_on": [str(dep) for dep in (node.get("depends_on") or [])],
                "description": str((node.get("metadata") or {}).get("description") or ""),
                "executor_prompt": str((node.get("executor") or {}).get("prompt") or ""),
            }
            for node in graph.get("nodes", [])
        ],
        "output_nodes": [str(node_id) for node_id in (graph.get("output_nodes") or [])],
    }
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)


def _unlock_auto_layout(graph: dict[str, Any]) -> None:
    meta = graph.setdefault("metadata", {}).setdefault("graphyagent", {})
    meta["layout"] = {}
    meta["layout_locked"] = False


def _workflow_node(node_id: str, task_type: str, description: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "task_type": task_type,
        "executor": {
            "type": "llm",
            "output": "llm_result.md",
            "include_state": True,
            "input_char_limit": 12000,
            "max_tokens": 900,
            "prompt": (
                "你是 GraphyAgent 工作流中的节点智能体。请完成当前节点任务，并输出可供下游节点继续使用的中文结果。\n"
                f"节点名称：{node_id}\n"
                f"任务类型：{task_type}\n"
                f"任务说明：{description}\n"
                "要求：基于输入文件、上游节点结果和图状态进行判断；不要只复述节点名称；"
                "如果信息不足，请明确列出缺口、假设和下一步需要的证据。"
            ),
        },
        "output_roles": {"llm_result.md": "节点结果", "llm_call.json": "llm_call"},
        "metadata": {"description": description},
    }


def _rename_node(graph: dict[str, Any], old_name: str, new_name: str) -> bool:
    old_id = _find_node_id(graph, old_name)
    if not old_id or not new_name:
        return False
    for node in graph.get("nodes", []):
        if node.get("id") == old_id:
            node["id"] = new_name
    for node in graph.get("nodes", []):
        node["depends_on"] = [new_name if dep == old_id else dep for dep in (node.get("depends_on") or [])]
    graph["output_nodes"] = [new_name if node_id == old_id else node_id for node_id in graph.get("output_nodes", [])]
    files = graph.get("metadata", {}).get("graphyagent", {}).get("files", {}).get("nodes", {})
    if old_id in files:
        files[new_name] = files.pop(old_id)
    return True


def _delete_node(graph: dict[str, Any], node_name: str) -> bool:
    node_id = _find_node_id(graph, node_name)
    if not node_id:
        return False
    graph["nodes"] = [node for node in graph.get("nodes", []) if node.get("id") != node_id]
    for node in graph.get("nodes", []):
        node["depends_on"] = [dep for dep in (node.get("depends_on") or []) if dep != node_id]
    graph["output_nodes"] = [node for node in graph.get("output_nodes", []) if node != node_id]
    if not graph.get("output_nodes") and graph.get("nodes"):
        graph["output_nodes"] = [graph["nodes"][-1]["id"]]
    return True


def _split_node(graph: dict[str, Any], node_name: str, child_names: list[str]) -> bool:
    node_id = _find_node_id(graph, node_name)
    if not node_id:
        return False
    nodes = graph.get("nodes", [])
    original_index = next((idx for idx, node in enumerate(nodes) if node.get("id") == node_id), -1)
    if original_index < 0:
        return False
    original = nodes[original_index]
    incoming = list(original.get("depends_on") or [])
    new_nodes = [
        _workflow_node(name, str(original.get("task_type") or "task"), f"{node_id} 的拆分步骤：{name}。")
        for name in child_names
    ]
    for index, node in enumerate(new_nodes):
        node["depends_on"] = incoming if index == 0 else [new_nodes[index - 1]["id"]]
    nodes[original_index:original_index + 1] = new_nodes
    for node in nodes:
        if node in new_nodes:
            continue
        node["depends_on"] = [
            new_nodes[-1]["id"] if dep == node_id else dep
            for dep in (node.get("depends_on") or [])
        ]
    graph["output_nodes"] = [
        new_nodes[-1]["id"] if output == node_id else output
        for output in graph.get("output_nodes", [])
    ]
    files = graph.get("metadata", {}).get("graphyagent", {}).get("files", {}).get("nodes", {})
    if node_id in files and new_nodes:
        first_child_id = new_nodes[0]["id"]
        files[first_child_id] = files.pop(node_id)
        for file_record in files[first_child_id]:
            _unsync_node_file_input(graph, node_id, file_record)
            _sync_node_file_input(graph, first_child_id, file_record)
    return True


def add_edge(graph: dict[str, Any], source: str, target: str) -> bool:
    source_id = _find_node_id(graph, source)
    target_id = _find_node_id(graph, target)
    if not source_id or not target_id or source_id == target_id:
        return False
    for node in graph.get("nodes", []):
        if node.get("id") == target_id:
            deps = [str(dep) for dep in (node.get("depends_on") or [])]
            if source_id in deps:
                return False
            deps.append(source_id)
            node["depends_on"] = deps
            return True
    return False


def remove_edge(graph: dict[str, Any], source: str, target: str) -> bool:
    source_id = _find_node_id(graph, source)
    target_id = _find_node_id(graph, target)
    if not source_id or not target_id:
        return False
    changed = False
    for node in graph.get("nodes", []):
        if node.get("id") == target_id:
            deps = [str(dep) for dep in (node.get("depends_on") or [])]
            new_deps = [dep for dep in deps if dep != source_id]
            changed = len(new_deps) != len(deps)
            node["depends_on"] = new_deps
    return changed


def correct_graph_dependencies(graph: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    corrected = deepcopy(graph)
    corrections: list[dict[str, Any]] = []
    for rule in _DEPENDENCY_RULES:
        source = _find_node_by_terms(corrected, rule["source_terms"]) or _find_node_id(corrected, rule["source_fallback"])
        target = _find_node_by_terms(corrected, rule["target_terms"]) or _find_node_id(corrected, rule["target_fallback"])
        if not source or not target or source == target:
            continue
        if add_edge(corrected, source, target):
            corrections.append({
                "type": "dependency_correction",
                "source": source,
                "target": target,
                "message": f"{source} -> {target}",
                "reason": rule["reason"],
            })
    return corrected, corrections


def diff_graphs(old_graph: dict[str, Any], new_graph: dict[str, Any]) -> dict[str, Any]:
    old_nodes = {node.get("id"): node for node in old_graph.get("nodes", [])}
    new_nodes = {node.get("id"): node for node in new_graph.get("nodes", [])}
    old_edges = {(edge["source"], edge["target"]) for edge in graph_edges(old_graph)}
    new_edges = {(edge["source"], edge["target"]) for edge in graph_edges(new_graph)}
    added_nodes = sorted(set(new_nodes) - set(old_nodes))
    removed_nodes = sorted(set(old_nodes) - set(new_nodes))
    changed_nodes = sorted(
        node_id for node_id in set(old_nodes) & set(new_nodes)
        if _node_diff_view(old_nodes[node_id]) != _node_diff_view(new_nodes[node_id])
    )
    added_edges = [
        {"source": source, "target": target}
        for source, target in sorted(new_edges - old_edges)
    ]
    removed_edges = [
        {"source": source, "target": target}
        for source, target in sorted(old_edges - new_edges)
    ]
    changes = {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
    }
    summary_parts = []
    for key, label in [
        ("added_nodes", "个新增节点"),
        ("removed_nodes", "个删除节点"),
        ("changed_nodes", "个修改节点"),
        ("added_edges", "条新增边"),
        ("removed_edges", "条删除边"),
    ]:
        count = len(changes[key])
        if count:
            summary_parts.append(f"{count}{label}")
    changes["summary"] = "，".join(summary_parts) if summary_parts else "图无变化。"
    return changes


def _node_diff_view(node: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(node.get("metadata") or {})
    for volatile_key in [
        "latest_run",
        "latest_outputs",
        "necessity_audit",
        "run_history",
        "updated_at",
    ]:
        metadata.pop(volatile_key, None)
    return {
        "id": str(node.get("id") or ""),
        "task_type": node.get("task_type"),
        "depends_on": [str(dep) for dep in (node.get("depends_on") or [])],
        "executor": node.get("executor"),
        "inputs": node.get("inputs"),
        "outputs": node.get("outputs"),
        "output_roles": node.get("output_roles"),
        "metadata": metadata,
    }


def _default_graph(default_config_path: str | Path | None) -> dict[str, Any]:
    if default_config_path and Path(default_config_path).exists():
        raw = json.loads(Path(default_config_path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"default graph config must be an object: {default_config_path}")
        return normalize_graph_config_data(raw)
    return _blank_graph("default_graph")


def _blank_graph(graph_id: str) -> dict[str, Any]:
    return {
        "graph_id": graph_id,
        "context": {"purpose": "GraphyAgent managed canvas graph"},
        "nodes": [
            {
                "id": "start",
                "task_type": "planning",
                "executor": {"type": "noop", "write_outputs": {"result.txt": "start"}},
                "metadata": {"description": "Initial node"},
            }
        ],
        "output_nodes": ["start"],
    }


def _project_summary(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": project["project_id"],
        "name": project.get("name", project["project_id"]),
        "created_at": project.get("created_at"),
        "updated_at": project.get("updated_at"),
        "current_graph_id": project.get("current_graph_id"),
        "graph_count": len(project.get("graphs", [])),
    }


def _graph_summary(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not graph:
        return None
    meta = graph.get("metadata", {}).get("graphyagent", {})
    return {
        "graph_id": graph.get("graph_id"),
        "name": meta.get("name") or graph.get("graph_id"),
        "node_count": len(graph.get("nodes", [])),
        "edge_count": len(graph_edges(graph)),
        "updated_at": meta.get("updated_at"),
    }


def _graph_run_record(
    run: dict[str, Any],
    command_record: dict[str, Any] | None,
    scope: dict[str, str] | None,
) -> dict[str, Any]:
    command = None
    if command_record:
        command = {
            "command_id": command_record.get("command_id"),
            "command": command_record.get("command"),
            "origin": command_record.get("origin"),
            "target_type": command_record.get("target_type"),
            "node_id": command_record.get("node_id"),
        }
    return {
        "graph_run_id": run.get("graph_run_id"),
        "runtime_graph_id": run.get("graph_id"),
        "status": run.get("status"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "run_dir": run.get("run_dir"),
        "output_dir": run.get("output_dir"),
        "error": run.get("error"),
        "scope": scope or {"type": "graph"},
        "command": command,
        "recorded_at": utc_now(),
    }


def _node_run_trace_index(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    run_dir = run.get("run_dir")
    if not run_dir:
        return {}
    trace_path = Path(str(run_dir)) / "traces" / "node_runs.jsonl"
    if not trace_path.exists():
        return {}
    traces: dict[str, dict[str, Any]] = {}
    for line in trace_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        node_id = str(item.get("node_id") or "")
        if node_id:
            traces[node_id] = item
    return traces


def _node_output_index_from_run(run: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    final_state = run.get("final_state") or {}
    artifacts = final_state.get("artifacts") or {}
    node_results = final_state.get("node_results") or {}
    output_index: dict[str, list[dict[str, Any]]] = {}
    for node_id, result in node_results.items():
        outputs = []
        for name, artifact_id in sorted((result.get("outputs") or {}).items()):
            artifact = artifacts.get(artifact_id) or {}
            metadata = artifact.get("metadata") or {}
            outputs.append({
                "name": name,
                "artifact_id": artifact_id,
                "path": artifact.get("uri"),
                "type": artifact.get("type") or "output",
                "size": metadata.get("size"),
                "sha256": metadata.get("sha256"),
                "original_name": metadata.get("original_name"),
            })
        output_index[str(node_id)] = outputs
    return output_index


def _node_run_record(
    node_id: str,
    result: dict[str, Any],
    graph_run: dict[str, Any],
    outputs: list[dict[str, Any]],
    trace: dict[str, Any] | None,
) -> dict[str, Any]:
    trace = trace or {}
    call = trace.get("call") or {}
    routing = call.get("routing") or {}
    return {
        "node_id": node_id,
        "graph_run_id": graph_run.get("graph_run_id"),
        "node_run_id": result.get("node_run_id") or trace.get("node_run_id"),
        "status": result.get("status") or trace.get("status"),
        "started_at": trace.get("started_at"),
        "ended_at": trace.get("ended_at"),
        "duration_ms": trace.get("duration_ms"),
        "run_dir": (result.get("summary") or {}).get("run_dir"),
        "outputs": outputs,
        "inputs": _node_trace_inputs(trace),
        "node_memory_packet": (trace.get("input_snapshot") or {}).get("node_memory_packet") or {},
        "online_reflection": (trace.get("output_snapshot") or {}).get("online_reflection") or {},
        "routing": {
            "provider": call.get("chosen_provider") or routing.get("provider_id"),
            "model": call.get("chosen_model") or routing.get("model_id"),
            "model_ref": routing.get("model_ref"),
            "reason": call.get("routing_reason") or routing.get("routing_reason"),
        },
        "error": result.get("error") or trace.get("error"),
        "recorded_at": utc_now(),
    }


def _node_trace_inputs(trace: dict[str, Any]) -> list[dict[str, Any]]:
    inputs = ((trace.get("input_snapshot") or {}).get("inputs") or {})
    items = []
    for name, artifact in sorted(inputs.items()):
        metadata = artifact.get("metadata") or {}
        items.append({
            "name": name,
            "artifact_id": artifact.get("artifact_id"),
            "path": artifact.get("uri"),
            "type": artifact.get("type"),
            "size": metadata.get("size"),
            "sha256": metadata.get("sha256"),
            "original_name": metadata.get("original_name"),
        })
    return items


def _graph_run_memory_text(run_record: dict[str, Any], outputs: dict[str, list[dict[str, Any]]]) -> str:
    output_count = sum(len(items) for items in outputs.values())
    scope = run_record.get("scope") or {}
    scope_label = (
        f"节点 `{scope.get('node_id')}`"
        if scope.get("type") == "node"
        else "整图"
    )
    return (
        "图运行记录已同步。\n"
        f"- 范围：{scope_label}\n"
        f"- GraphRun：{run_record.get('graph_run_id')}\n"
        f"- 状态：{run_record.get('status')}\n"
        f"- 输出文件数：{output_count}\n"
        f"- 运行目录：{run_record.get('run_dir')}"
    )


def _node_run_memory_text(record: dict[str, Any]) -> str:
    output_names = ", ".join(item["name"] for item in record.get("outputs", [])[:8]) or "无"
    routing = record.get("routing") or {}
    model = routing.get("model_ref") or ":".join(
        part for part in [routing.get("provider"), routing.get("model")] if part
    ) or "未路由"
    return (
        "节点运行记录已同步。\n"
        f"- NodeRun：{record.get('node_run_id')}\n"
        f"- 状态：{record.get('status')}\n"
        f"- 模型：{model}\n"
        f"- 输出：{output_names}\n"
        f"- 运行目录：{record.get('run_dir')}\n"
        f"- 错误：{record.get('error') or '无'}"
    )


def _graph_file_index(project: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    records = [
        _file_record_summary(file_record, PROJECT_UNCLASSIFIED, graph_id=None, node_id=None)
        for file_record in project.get("files", {}).get(PROJECT_UNCLASSIFIED, [])
    ]
    graph_id = str(graph.get("graph_id") or "")
    files_meta = graph.get("metadata", {}).get("graphyagent", {}).get("files", {})
    records.extend(
        _file_record_summary(file_record, GRAPH_UNCLASSIFIED, graph_id=graph_id, node_id=None)
        for file_record in files_meta.get("unclassified", [])
    )
    for node_id, files in sorted((files_meta.get("nodes") or {}).items()):
        records.extend(
            _file_record_summary(file_record, NODE_FILES, graph_id=graph_id, node_id=node_id)
            for file_record in files
        )
    return records


def _node_file_records(graph: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    graph_id = str(graph.get("graph_id") or "")
    files = (
        graph.get("metadata", {})
        .get("graphyagent", {})
        .get("files", {})
        .get("nodes", {})
        .get(node_id, [])
    )
    return [
        _file_record_summary(file_record, NODE_FILES, graph_id=graph_id, node_id=node_id)
        for file_record in files
    ]


def _file_record_summary(
    file_record: dict[str, Any],
    scope: str,
    *,
    graph_id: str | None,
    node_id: str | None,
) -> dict[str, Any]:
    analysis = file_record.get("analysis") or {}
    return {
        "file_id": file_record.get("file_id"),
        "name": file_record.get("name"),
        "scope": scope,
        "graph_id": graph_id,
        "node_id": node_id,
        "storage_path": file_record.get("storage_path"),
        "source_path": file_record.get("source_path"),
        "size": file_record.get("size"),
        "sha256": file_record.get("sha256"),
        "artifact_id": file_record.get("artifact_id"),
        "artifact_uri": file_record.get("artifact_uri"),
        "artifact_type": file_record.get("artifact_type"),
        "is_dataset": _is_auditable_dataset_file(file_record),
        "analysis_summary": analysis.get("summary"),
        "artifact": analysis.get("artifact"),
        "audit": _audit_summary_from_file(file_record),
    }


def _audit_summary_from_file(file_record: dict[str, Any]) -> dict[str, Any] | None:
    audit = (file_record.get("analysis") or {}).get("audit") or {}
    if not audit:
        return None
    llm = audit.get("llm_summary") or {}
    return {
        "status": audit.get("status"),
        "verdict": audit.get("verdict"),
        "row_count": audit.get("row_count"),
        "tagged_record_count": audit.get("tagged_record_count"),
        "evidence_count": audit.get("evidence_count"),
        "synthetic_evidence_families": audit.get("synthetic_evidence_families") or [],
        "recommended_actions": audit.get("recommended_actions") or [],
        "top_tags": audit.get("top_tags") or [],
        "paths": audit.get("paths") or {},
        "llm_summary": {
            "status": llm.get("status"),
            "profile": llm.get("profile"),
            "model": llm.get("model"),
            "path": llm.get("path"),
        } if llm else None,
        "reused": audit.get("reused", False),
    }


def _file_index_audit_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    dataset_files = [item for item in records if item.get("is_dataset")]
    audits = [item.get("audit") or {} for item in dataset_files if item.get("audit")]
    verdicts: dict[str, int] = {}
    for audit in audits:
        key = str(audit.get("verdict") or audit.get("status") or "unknown")
        verdicts[key] = verdicts.get(key, 0) + 1
    return {
        "dataset_file_count": len(dataset_files),
        "audited_count": sum(1 for audit in audits if audit.get("status") == "completed"),
        "running_count": sum(1 for audit in audits if audit.get("status") == "running"),
        "failed_count": sum(1 for audit in audits if audit.get("status") == "failed"),
        "verdicts": verdicts,
    }


def _node_files_audit_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return _file_index_audit_summary(records)


def _find_node_by_terms(graph: dict[str, Any], terms: list[str]) -> str | None:
    for node in graph.get("nodes", []):
        text = _node_search_text(node)
        if all(term in text for term in terms):
            return str(node.get("id"))
    return None


def _find_node_id(graph: dict[str, Any], query: str | None) -> str | None:
    if not query:
        return None
    query_norm = str(query).strip()
    for node in graph.get("nodes", []):
        if str(node.get("id")) == query_norm:
            return str(node.get("id"))
    for node in graph.get("nodes", []):
        node_text = _node_search_text(node)
        if query_norm in node_text or str(node.get("id") or "") in query_norm:
            return str(node.get("id"))
    query_key = _node_match_key(query_norm)
    if len(query_key) >= 2:
        direct_matches = []
        for node in graph.get("nodes", []):
            node_key = _node_match_key(_node_identity_text(node))
            if query_key and (query_key in node_key or node_key in query_key):
                direct_matches.append(str(node.get("id")))
        if len(direct_matches) == 1:
            return direct_matches[0]
        best_id = None
        best_score = 0.0
        tied = False
        query_chars = set(query_key)
        for node in graph.get("nodes", []):
            node_key = _node_match_key(_node_identity_text(node))
            if not node_key:
                continue
            shared = len(query_chars & set(node_key))
            score = shared / max(len(query_chars), 1)
            if shared >= 2 and score > best_score:
                best_id = str(node.get("id"))
                best_score = score
                tied = False
            elif shared >= 2 and score == best_score:
                tied = True
        if best_id and best_score >= 0.67 and not tied:
            return best_id
        description_matches = []
        for node in graph.get("nodes", []):
            node_key = _node_match_key(_node_search_text(node))
            if query_key and query_key in node_key:
                description_matches.append(str(node.get("id")))
        if len(description_matches) == 1:
            return description_matches[0]
    return None


def _node_identity_text(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") or {}
    fields = [
        node.get("id"),
        metadata.get("name"),
        metadata.get("title"),
    ]
    return " ".join(str(field or "") for field in fields)


def _node_search_text(node: dict[str, Any]) -> str:
    metadata = node.get("metadata") or {}
    fields = [
        node.get("id"),
        node.get("task_type"),
        metadata.get("name"),
        metadata.get("title"),
        metadata.get("description"),
    ]
    return " ".join(str(field or "") for field in fields)


def _node_match_key(value: str | None) -> str:
    text = re.sub(r"[\s`\"'“”‘’（）()【】\[\]{}<>《》:：,，。；;、/\\|\-]+", "", str(value or ""))
    for term in [
        "节点",
        "任务",
        "步骤",
        "阶段",
        "分析",
        "研判",
        "评估",
        "分类",
        "处理",
        "处置",
        "当前",
        "其他",
        "请",
        "把",
        "将",
        "让",
        "使",
        "前面",
        "后面",
        "之前",
        "之后",
    ]:
        text = text.replace(term, "")
    text = re.sub(r"[一二两三四五六七八九十\d]+个?", "", text)
    return text


def _analysis_report(file_name: str, size: int, source_path: str | None) -> dict[str, Any]:
    ext = Path(file_name).suffix.lower() or "unknown"
    role = "source" if ext in {".pdf", ".md", ".txt", ".json", ".jsonl", ".csv"} else "artifact"
    role_label = "来源文件" if role == "source" else "产物文件"
    ext_label = ext if ext != "unknown" else "未知"
    return {
        "summary": f"{file_name}（{size} 字节），建议角色：{role_label}。",
        "extension": ext_label,
        "suggested_role": role,
        "source_path": source_path,
    }


def _artifact_reference_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    metadata = artifact.get("metadata") or {}
    return {
        "artifact_id": artifact.get("artifact_id"),
        "uri": artifact.get("uri") or artifact.get("path"),
        "type": artifact.get("type"),
        "name": artifact.get("name"),
        "size": artifact.get("size") or metadata.get("size"),
        "sha256": artifact.get("sha256") or artifact.get("artifact_id"),
    }


def _sync_node_file_input(graph: dict[str, Any], node_id: str, file_record: dict[str, Any]) -> None:
    node = next((item for item in graph.get("nodes", []) if item.get("id") == node_id), None)
    if not node:
        return
    alias = _node_file_alias(file_record)
    file_name = str(file_record.get("name") or alias)
    artifact_type = _artifact_type_for_file(file_record)
    artifact_spec = {
        "path": file_record.get("storage_path"),
        "type": artifact_type,
        "metadata": {
            "graphyagent_file_id": file_record.get("file_id"),
            "node_id": node_id,
            "name": file_name,
            "sha256": file_record.get("sha256"),
            "source_path": file_record.get("source_path"),
        },
    }
    node.setdefault("inputs", {})[file_name] = alias
    initial_artifacts = graph.setdefault("initial_artifacts", {})
    initial_artifacts[alias] = artifact_spec
    canonical_alias = _canonical_artifact_alias_for_file(file_record, artifact_type)
    if canonical_alias:
        initial_artifacts[canonical_alias] = deepcopy(artifact_spec)
        node.setdefault("inputs", {})[canonical_alias] = canonical_alias
    _repair_file_input_references(graph, file_name, alias, canonical_alias)
    metadata = node.setdefault("metadata", {})
    evidence = metadata.setdefault("evidence_pointers", [])
    pointer = {
        "type": "node_file",
        "file_id": file_record.get("file_id"),
        "name": file_name,
        "artifact_alias": alias,
        "path": file_record.get("storage_path"),
    }
    if not any(item.get("file_id") == pointer["file_id"] for item in evidence if isinstance(item, dict)):
        evidence.append(pointer)


def _unsync_node_file_input(graph: dict[str, Any], node_id: str, file_record: dict[str, Any]) -> None:
    alias = _node_file_alias(file_record)
    canonical_alias = _canonical_artifact_alias_for_file(file_record, _artifact_type_for_file(file_record))
    initial_artifacts = graph.get("initial_artifacts", {})
    initial_artifacts.pop(alias, None)
    if canonical_alias:
        spec = initial_artifacts.get(canonical_alias)
        spec_meta = spec.get("metadata") if isinstance(spec, dict) else {}
        if (
            isinstance(spec_meta, dict)
            and spec_meta.get("graphyagent_file_id") == file_record.get("file_id")
        ):
            initial_artifacts.pop(canonical_alias, None)
    for node in graph.get("nodes", []):
        if node.get("id") != node_id:
            continue
        inputs = node.get("inputs") or {}
        node["inputs"] = {
            key: value
            for key, value in inputs.items()
            if (
                value != alias
                and key != file_record.get("name")
                and not (canonical_alias and (value == canonical_alias or key == canonical_alias))
            )
        }
        metadata = node.get("metadata") or {}
        metadata["evidence_pointers"] = [
            item for item in metadata.get("evidence_pointers", [])
            if not (isinstance(item, dict) and item.get("file_id") == file_record.get("file_id"))
        ]


def _node_file_alias(file_record: dict[str, Any]) -> str:
    file_id = str(file_record.get("file_id") or uuid.uuid4().hex[:16])
    return "node_file_" + re.sub(r"[^A-Za-z0-9_]+", "_", file_id).strip("_")


def _repair_file_input_references(
    graph: dict[str, Any],
    file_name: str,
    alias: str,
    canonical_alias: str | None,
) -> None:
    preferred_alias = canonical_alias or alias
    if not preferred_alias:
        return
    output_names_by_node = {
        str(node.get("id")): set((node.get("output_roles") or {}).keys())
        for node in graph.get("nodes", [])
    }
    candidate_names = {file_name, alias}
    if canonical_alias:
        candidate_names.add(canonical_alias)
    for node in graph.get("nodes", []):
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for input_name, raw_ref in list(inputs.items()):
            ref = str(raw_ref or "")
            if ref in candidate_names:
                inputs[input_name] = preferred_alias
                continue
            if ":" not in ref:
                continue
            source_node_id, output_name = ref.split(":", 1)
            source_node_id = source_node_id.strip()
            output_name = output_name.strip()
            if output_name not in candidate_names:
                continue
            if output_name in output_names_by_node.get(source_node_id, set()):
                continue
            inputs[input_name] = preferred_alias


def _artifact_type_for_file(file_record: dict[str, Any]) -> str:
    suffix = Path(str(file_record.get("name") or "")).suffix.lower()
    if suffix in {".csv", ".json", ".jsonl", ".parquet"} and not _looks_like_metadata_file(file_record):
        return "dataset"
    if _looks_like_metadata_file(file_record):
        return "metadata"
    return "source"


def _canonical_artifact_alias_for_file(file_record: dict[str, Any], artifact_type: str) -> str | None:
    if artifact_type == "dataset" and _is_auditable_dataset_file(file_record):
        return "dataset"
    if artifact_type == "metadata" and _looks_like_metadata_file(file_record):
        return "metadata"
    return None


def _evaluate_node_necessity(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    nodes = graph.get("nodes", [])
    node = next((item for item in nodes if item.get("id") == node_id), {})
    downstream = [
        str(item.get("id"))
        for item in nodes
        if node_id in [str(dep) for dep in (item.get("depends_on") or [])]
    ]
    files = graph.get("metadata", {}).get("graphyagent", {}).get("files", {}).get("nodes", {}).get(node_id, [])
    executor = node.get("executor") or {}
    output_nodes = set(graph.get("output_nodes") or [])
    reasons: list[str] = []
    risks: list[str] = []
    if node_id in output_nodes:
        reasons.append("该节点是图输出节点，删除会直接改变最终交付物。")
    if downstream:
        reasons.append(f"该节点被 {len(downstream)} 个下游节点依赖：{', '.join(downstream[:6])}。")
    if node.get("inputs"):
        reasons.append("该节点声明了输入契约，承担数据/证据传递职责。")
    if node.get("output_roles") or executor.get("write_outputs"):
        reasons.append("该节点声明了输出角色，可能被图输出或后续节点消费。")
    if files:
        reasons.append(f"该节点绑定了 {len(files)} 个文件，删除会丢失节点文件归属和自动审计上下文。")
    if executor.get("type") in {"audit", "llm", "python", "shell", "subgraph", "http", "sqlite", "db_query"}:
        reasons.append(f"该节点执行器为 {executor.get('type')}，包含实际运行逻辑。")
    if not reasons:
        risks.append("没有下游依赖、输出角色、输入文件或实际执行器，可能是冗余节点。")
    elif not downstream and node_id not in output_nodes:
        risks.append("节点没有下游消费关系，建议确认其输出是否应连接到后续节点或图输出。")
    decision = "required" if (node_id in output_nodes or downstream) else "review"
    if not reasons:
        decision = "optional"
    confidence = 0.9 if decision == "required" else 0.65 if decision == "review" else 0.8
    return {
        "created_at": utc_now(),
        "decision": decision,
        "confidence": confidence,
        "reasons": reasons,
        "risks_if_removed": risks or ["删除该节点会改变当前图结构；实际影响取决于用户目标。"],
        "removal_test": {
            "downstream_nodes": downstream,
            "is_output_node": node_id in output_nodes,
            "bound_file_count": len(files),
            "has_executor_logic": executor.get("type") not in {None, "", "noop"} or bool(executor.get("write_outputs")),
        },
    }


def _refresh_node_necessity_audits(graph: dict[str, Any]) -> dict[str, Any]:
    """Refresh necessity audit metadata for every node in a graph.

    This is intentionally local and deterministic. The UI should not ask users
    to trigger this manually; any graph shape change updates the node audit
    state that is then synced back through the workspace snapshot.
    """
    nodes = graph.get("nodes") or []
    decisions: dict[str, int] = {}
    review_nodes: list[str] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        audit = _evaluate_node_necessity(graph, node_id)
        node.setdefault("metadata", {})["necessity_audit"] = audit
        decision = str(audit.get("decision") or "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1
        if decision != "required":
            review_nodes.append(node_id)
    summary = {
        "status": "completed",
        "updated_at": utc_now(),
        "node_count": len(nodes),
        "decisions": decisions,
        "review_nodes": review_nodes,
    }
    graph.setdefault("metadata", {}).setdefault("graphyagent", {})["auto_node_necessity_audit"] = summary
    return summary


def _necessity_audit_memory_text(audit: dict[str, Any]) -> str:
    return (
        "节点必要性审计完成。\n"
        f"- 结论：{audit.get('decision')}，confidence={audit.get('confidence')}\n"
        f"- 理由：{'; '.join(audit.get('reasons') or ['无强必要性证据'])}\n"
        f"- 删除风险：{'; '.join(audit.get('risks_if_removed') or [])}"
    )


def _is_auditable_dataset_file(file_record: dict[str, Any]) -> bool:
    path = str(file_record.get("storage_path") or file_record.get("name") or "")
    suffix = Path(path).suffix.lower()
    if suffix not in {".csv", ".json", ".jsonl"}:
        return False
    return not _looks_like_metadata_file(file_record)


def _looks_like_metadata_file(file_record: dict[str, Any]) -> bool:
    name = f"{file_record.get('name') or ''} {file_record.get('storage_path') or ''}".lower()
    if Path(name.split()[0] if name.split() else "").suffix.lower() not in {".json", ".jsonl", ""}:
        return False
    terms = (
        "metadata",
        "meta",
        "schema",
        "datasheet",
        "datacard",
        "data_card",
        "task_spec",
        "provenance",
        "字段",
        "元数据",
        "任务说明",
    )
    return any(term in name for term in terms)


def _iter_graph_file_records(project: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    records = list(project.get("files", {}).get(PROJECT_UNCLASSIFIED, []))
    graph_files = graph.get("metadata", {}).get("graphyagent", {}).get("files", {})
    records.extend(graph_files.get("unclassified", []))
    for files in graph_files.get("nodes", {}).values():
        records.extend(files)
    return records


def _completed_audit_for_file(
    project: dict[str, Any],
    graph: dict[str, Any],
    file_record: dict[str, Any],
) -> dict[str, Any] | None:
    current_sha = file_record.get("sha256")
    current_id = file_record.get("file_id")
    current_audit = (file_record.get("analysis") or {}).get("audit") or {}
    if current_audit.get("status") == "completed" and _audit_paths_exist(current_audit):
        return current_audit
    for other in _iter_graph_file_records(project, graph):
        if other is file_record:
            continue
        if other.get("file_id") != current_id and other.get("sha256") != current_sha:
            continue
        audit = (other.get("analysis") or {}).get("audit") or {}
        if audit.get("status") == "completed" and _audit_paths_exist(audit):
            return audit
    return None


def _audit_paths_exist(audit_meta: dict[str, Any]) -> bool:
    paths = audit_meta.get("paths") or {}
    report = paths.get("audit_report_md") or paths.get("audit_report_json")
    return bool(report and Path(str(report)).exists())


def _audit_record_from_report(report: dict[str, Any], paths: dict[str, str]) -> dict[str, Any]:
    metrics = report.get("dataset_metrics") or {}
    top_tags = [
        {
            "tag": tag,
            "record_count": item.get("record_count", 0),
            "evidence_count": item.get("evidence_count", 0),
            "max_severity": item.get("max_severity"),
            "max_confidence": item.get("max_confidence"),
        }
        for tag, item in sorted(
            (report.get("tag_summary") or {}).items(),
            key=lambda pair: (
                SEVERITY_RANK_LOCAL.get(str(pair[1].get("max_severity") or "low"), 0),
                pair[1].get("record_count", 0),
                pair[1].get("evidence_count", 0),
            ),
            reverse=True,
        )[:8]
    ]
    return {
        "status": "completed",
        "completed_at": utc_now(),
        "verdict": report.get("verdict"),
        "row_count": metrics.get("row_count", 0),
        "tagged_record_count": metrics.get("tagged_record_count", 0),
        "evidence_count": metrics.get("evidence_count", 0),
        "synthetic_evidence_families": metrics.get("synthetic_evidence_families") or [],
        "recommended_actions": (report.get("gate") or {}).get("recommended_actions") or [],
        "top_tags": top_tags,
        "paths": paths,
    }


SEVERITY_RANK_LOCAL = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _audit_summary_text(file_name: str, audit_meta: dict[str, Any]) -> str:
    tags = ", ".join(item["tag"] for item in audit_meta.get("top_tags", [])[:4]) or "无主要标签"
    llm = audit_meta.get("llm_summary") or {}
    llm_label = "LLM总结完成" if llm.get("status") == "completed" else "LLM总结失败"
    return (
        f"{file_name} 自动审计：{audit_meta.get('verdict')}，"
        f"{audit_meta.get('tagged_record_count', 0)}/{audit_meta.get('row_count', 0)} 条记录被标记，"
        f"标签：{tags}，{llm_label}。"
    )


def _node_audit_memory_text(file_record: dict[str, Any], audit_meta: dict[str, Any]) -> str:
    tags = ", ".join(
        f"{item['tag']}({item.get('record_count', 0)})"
        for item in audit_meta.get("top_tags", [])[:6]
    ) or "无主要标签"
    paths = audit_meta.get("paths") or {}
    llm = audit_meta.get("llm_summary") or {}
    return (
        "自动数据审计完成。\n"
        f"- 文件：`{file_record.get('name')}`\n"
        f"- Verdict：{audit_meta.get('verdict')}\n"
        f"- 标记记录：{audit_meta.get('tagged_record_count', 0)}/{audit_meta.get('row_count', 0)}\n"
        f"- 证据数：{audit_meta.get('evidence_count', 0)}\n"
        f"- 主要标签：{tags}\n"
        f"- 建议动作：{', '.join(audit_meta.get('recommended_actions') or []) or '无'}\n"
        f"- 审计报告：{paths.get('audit_report_md') or paths.get('audit_report_json') or audit_meta.get('output_dir')}\n"
        f"- LLM 总结：{llm.get('path')}（{llm.get('status')}，profile={llm.get('profile')}）"
    )


def _node_audit_reuse_memory_text(file_record: dict[str, Any], audit_meta: dict[str, Any]) -> str:
    paths = audit_meta.get("paths") or {}
    return (
        "自动数据审计结果复用。\n"
        f"- 文件：`{file_record.get('name')}`\n"
        f"- Verdict：{audit_meta.get('verdict')}\n"
        f"- 标记记录：{audit_meta.get('tagged_record_count', 0)}/{audit_meta.get('row_count', 0)}\n"
        f"- 审计报告：{paths.get('audit_report_md') or paths.get('audit_report_json') or audit_meta.get('output_dir')}"
    )


def _upsert_file(files: list[dict[str, Any]], file_record: dict[str, Any]) -> None:
    for idx, item in enumerate(files):
        if item.get("file_id") == file_record["file_id"]:
            files[idx] = file_record
            return
    files.append(file_record)


def _pop_from_list(files: list[dict[str, Any]], file_id: str) -> dict[str, Any] | None:
    for idx, item in enumerate(files):
        if item.get("file_id") == file_id:
            return files.pop(idx)
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-. ")
    slug = slug[:80].rstrip(". ")
    if not slug or not re.search(r"[A-Za-z0-9]", slug):
        return ""
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{idx}" for idx in range(1, 10)),
        *(f"LPT{idx}" for idx in range(1, 10)),
    }
    if slug.upper() in reserved:
        return ""
    return slug


def _safe_filename(value: str) -> str:
    name = Path(str(value)).name
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", name).strip() or "file"


def _node_asset_name(node_id: str) -> str:
    slug = _slug(node_id)
    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:10]
    return slug or f"node-{digest}"


def _write_if_missing(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _unique_id(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    for idx in range(2, 1000):
        candidate = f"{base}-{idx}"
        if candidate not in existing:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _remove_inside(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if not str(target_resolved).lower().startswith(str(root_resolved).lower()):
        raise ValueError(f"refusing to remove outside root: {target_resolved}")
    if target_resolved.exists():
        shutil.rmtree(target_resolved)
