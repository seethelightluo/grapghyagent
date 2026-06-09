"""Graph and node agent runtime facade for GraphyAgent.

This module is the backend agent boundary. Web, CLI workers, and future
background schedulers submit command records; the queue owns persistence, while
this runtime owns what a graph/node agent can do with those commands.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.types import GraphConfig, utc_now
from ..data_manager.project_store import PROJECT_UNCLASSIFIED, ProjectStore
from ..front_bridge.service import run_graph
from .module_registry import list_module_commands, list_modules, resolve_module_command
from .tool_catalog import list_agent_tools
from .tool_registry import execute_tool as execute_registered_tool
from .tool_registry import get_tool_schemas


AGENT_TOOL_SPECS: list[dict[str, Any]] = list_agent_tools()


class GraphyAgentAgentRuntime:
    """Execute graph/node agent commands against a ProjectStore."""

    def __init__(self, workspace_root: str | Path, project_store: ProjectStore):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.project_store = project_store

    def list_tools(self, target_type: str | None = None) -> list[dict[str, Any]]:
        if not target_type:
            return deepcopy(AGENT_TOOL_SPECS)
        return [
            deepcopy(tool)
            for tool in AGENT_TOOL_SPECS
            if target_type in tool.get("target_types", [])
        ]

    def list_module_commands(self, target_type: str | None = None) -> list[dict[str, Any]]:
        return list_module_commands(target_type=target_type, queue_enabled=True)

    def target_context(
        self,
        project_id: str | None,
        graph_id: str | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        project = self.project_store.read_project(str(project_id)) if project_id else None
        graph = (
            self.project_store.read_graph(str(project_id), str(graph_id))
            if project_id and graph_id
            else None
        )
        node = None
        if graph and node_id:
            node = next(
                (item for item in graph.get("nodes", []) if item.get("id") == node_id),
                None,
            )
        target_type = "node" if node_id else "graph" if graph_id else "project"
        return {
            "project": _project_context(project),
            "graph": _graph_context(graph),
            "node": _node_context(graph, node) if graph and node else None,
            "modules": list_modules(),
            "module_commands": self.list_module_commands(target_type),
            "module_skill_summaries": _module_skill_summaries(),
            "tools": self.list_tools(target_type),
            "common_tools": get_tool_schemas(target_type),
        }

    def execute_command(self, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("module"):
            return self.execute_module_command(record)
        return self._execute_flat_command(record)

    def execute_module_command(self, record: dict[str, Any]) -> dict[str, Any]:
        spec = resolve_module_command(record.get("module"), str(record.get("command") or ""))
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if not spec.queue_enabled:
            raise ValueError(f"module command is not executable through the queue: {spec.qualified_name}")
        if spec.legacy_command:
            legacy_record = dict(record)
            legacy_record["command"] = spec.legacy_command
            legacy_record["module_command"] = spec.to_dict()
            return self._execute_flat_command(legacy_record)
        return self._execute_direct_module_command(spec.module, spec.command, record, payload)

    def _execute_flat_command(self, record: dict[str, Any]) -> dict[str, Any]:
        command = str(record.get("command") or "")
        payload = record.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        if command == "create_project":
            return self._create_project(record, payload)
        if command == "select_project":
            return self._select_project(record, payload)
        if command == "delete_project":
            return self._delete_project(record, payload)
        if command == "create_graph":
            return self._create_graph(record, payload)
        if command == "select_graph":
            return self._select_graph(record, payload)
        if command == "delete_graph":
            return self._delete_graph(record, payload)
        if command == "save_graph":
            return self._save_graph(record, payload)
        if command == "update_node_task":
            return self._update_node_task(record, payload)
        if command == "run_graph":
            return self._run_graph(record, payload)
        if command == "run_node":
            return self._run_node(record, payload)
        if command == "chat_graph":
            return self._chat_graph(record, payload)
        if command == "write_memory":
            return self._write_memory(record, payload)
        if command == "read_memory":
            return self._read_memory(record, payload)
        if command == "audit_node_necessity":
            return self._audit_node_necessity(record)
        if command == "decompose_node":
            return self._decompose_node(record, payload)
        if command == "import_file":
            return self._import_file(record, payload)
        if command == "move_file":
            return self._move_file(record, payload)
        if command == "delete_file":
            return self._delete_file(record, payload)
        if command == "audit_dataset":
            return self._audit_dataset(record, payload)
        if command == "list_subagent_types":
            return self._list_subagent_types(record, payload)
        raise ValueError(f"unknown agent command: {command}")

    def _execute_direct_module_command(
        self,
        module: str,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if module == "core":
            return self._execute_core_command(command, payload)
        if module == "graph_runner":
            return self._execute_graph_runner_command(command, record, payload)
        if module == "data_manager":
            return self._execute_data_manager_command(command, record, payload)
        if module == "graph_saver":
            return self._execute_graph_saver_command(command, record, payload)
        if module == "knowledge_graph":
            return self._execute_knowledge_graph_command(command, record, payload)
        if module == "node_memory":
            return self._execute_node_memory_command(command, record, payload)
        if module == "execution_lineage":
            return self._execute_execution_lineage_command(command, record, payload)
        if module == "reflection":
            return self._execute_reflection_command(command, record, payload)
        if module == "graph_optimizer":
            return self._execute_graph_optimizer_command(command, record, payload)
        if module == "evaluation":
            return self._execute_evaluation_command(command, record, payload)
        if module == "playbooks":
            return self._execute_playbooks_command(command, record, payload)
        if module == "model_routing":
            return self._execute_model_routing_command(command, payload)
        if module == "agent_runtime":
            return self._execute_agent_runtime_command(command, record, payload)
        if module == "node_audit":
            return self._execute_node_audit_command(command, record, payload)
        if module == "task_decompose":
            return self._execute_task_decompose_command(command, record, payload)
        if module == "memory":
            return self._execute_memory_command(command, record, payload)
        if module == "multi_agent":
            return self._execute_multi_agent_command(command, record, payload)
        if module == "research":
            return self._execute_research_command(command, record, payload)
        raise ValueError(f"module command has no runtime handler: {module}.{command}")

    def _execute_core_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "load_graph_config":
            from ..core.config import load_graph_config

            config_path = str(payload.get("config_path") or payload.get("path") or "")
            if not config_path:
                raise ValueError("load_graph_config requires payload.config_path")
            return {"graph": load_graph_config(config_path).to_dict()}
        if command == "inspect_graph_config":
            from ..front_bridge.service import inspect_graph_config

            config_path = str(payload.get("config_path") or payload.get("path") or "")
            if not config_path:
                raise ValueError("inspect_graph_config requires payload.config_path")
            return {"graph": inspect_graph_config(config_path)}
        if command == "graph_schema":
            from ..core.schema import GRAPH_CONFIG_SCHEMA

            return {"schema": GRAPH_CONFIG_SCHEMA}
        raise ValueError(f"unknown core command: {command}")

    def _execute_graph_runner_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if command == "list_runs":
            from ..front_bridge.service import list_graph_runs

            return {"runs": list_graph_runs(self.workspace_root)}
        if command == "show_run":
            from ..front_bridge.service import read_graph_run, read_node_runs

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("show_run requires payload.graph_run_id")
            result = {"run": read_graph_run(self.workspace_root, graph_run_id)}
            if payload.get("node_runs"):
                result["node_runs"] = read_node_runs(self.workspace_root, graph_run_id)
            return result
        if command == "timeline":
            from ..graph_runner.history import graph_run_timeline

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("timeline requires payload.graph_run_id")
            return graph_run_timeline(self.workspace_root, graph_run_id)
        if command == "show_run_manifest":
            from ..graph_runner.history import graph_run_manifest

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("show_run_manifest requires payload.graph_run_id")
            return graph_run_manifest(self.workspace_root, graph_run_id)
        if command == "list_node_runs":
            from ..front_bridge.service import read_node_runs

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("list_node_runs requires payload.graph_run_id")
            return {"node_runs": read_node_runs(self.workspace_root, graph_run_id)}
        if command == "show_node_run":
            from ..graph_runner.history import read_node_run

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("show_node_run requires payload.graph_run_id")
            return {
                "node_run": read_node_run(
                    self.workspace_root,
                    graph_run_id,
                    node_run_id=payload.get("node_run_id"),
                    node_id=payload.get("node_id"),
                )
            }
        if command == "list_run_outputs":
            from ..graph_runner.history import graph_run_outputs

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("list_run_outputs requires payload.graph_run_id")
            return graph_run_outputs(self.workspace_root, graph_run_id)
        if command == "list_run_errors":
            from ..graph_runner.history import graph_run_errors

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("list_run_errors requires payload.graph_run_id")
            return graph_run_errors(self.workspace_root, graph_run_id)
        if command == "classify_node_failure":
            from ..graph_runner.main import classify_node_failure

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            if graph is None and (record.get("project_id") or payload.get("project_id")) and (record.get("graph_id") or payload.get("graph_id")):
                graph = self.project_store.read_graph(
                    _required_project_id(record, payload),
                    _required_graph_id(record, payload),
                )
            return {
                "failure_analysis": classify_node_failure(
                    self.workspace_root,
                    graph_run_id or None,
                    node_run_id=payload.get("node_run_id"),
                    node_id=payload.get("node_id") or record.get("node_id"),
                    error=payload.get("error"),
                    graph=graph,
                )
            }
        if command == "pause_for_replan":
            from ..graph_runner.main import pause_for_replan

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("pause_for_replan requires payload.graph_run_id")
            result = pause_for_replan(
                self.workspace_root,
                graph_run_id,
                node_run_id=payload.get("node_run_id"),
                node_id=payload.get("node_id") or record.get("node_id"),
                reason=str(payload.get("reason") or ""),
                failure_analysis=payload.get("failure_analysis") if isinstance(payload.get("failure_analysis"), dict) else None,
            )
            return {"pause": result}
        if command == "mark_edges_blocked":
            from ..graph_runner.main import mark_edges_blocked

            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            project_id = record.get("project_id") or payload.get("project_id")
            graph_id = record.get("graph_id") or payload.get("graph_id")
            if graph is None:
                if not project_id or not graph_id:
                    raise ValueError("mark_edges_blocked requires payload.graph or project_id/graph_id")
                graph = self.project_store.read_graph(str(project_id), str(graph_id))
            failed_node_id = str(payload.get("failed_node_id") or payload.get("node_id") or record.get("node_id") or "")
            if not failed_node_id:
                raise ValueError("mark_edges_blocked requires payload.failed_node_id")
            result = mark_edges_blocked(
                graph,
                failed_node_id,
                replacement_node_id=payload.get("replacement_node_id"),
                downstream_node_ids=payload.get("downstream_node_ids") if isinstance(payload.get("downstream_node_ids"), list) else None,
                status=str(payload.get("status") or "blocked_for_replan"),
                reason=str(payload.get("reason") or ""),
                rewrite_dependencies=bool(payload.get("rewrite_dependencies")),
            )
            if payload.get("save") or payload.get("apply"):
                if not project_id or not graph_id:
                    raise ValueError("saving marked graph requires project_id and graph_id")
                saved = self.project_store.save_graph(str(project_id), str(graph_id), result["graph"])
                result["save_result"] = saved
                result["agent_context"] = self.target_context(str(project_id), str(graph_id))
                result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "export_trace_dataset":
            from ..data_manager.artifacts import ArtifactStore
            from ..graph_runner.history import export_trace_dataset

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("export_trace_dataset requires payload.graph_run_id")
            dataset = export_trace_dataset(
                self.workspace_root,
                graph_run_id,
                output_dir=payload.get("output_dir"),
                max_chars_per_file=int(payload.get("max_chars_per_file") or 4000),
            )
            store = ArtifactStore(self.workspace_root)
            artifacts: dict[str, Any] = {}
            paths = dataset.get("paths") or {}
            if paths.get("jsonl"):
                artifacts["jsonl"] = store.register_file(
                    paths["jsonl"],
                    artifact_type="trace_dataset",
                    metadata={
                        "graph_run_id": graph_run_id,
                        "record_count": dataset.get("record_count"),
                    },
                    name=Path(str(paths["jsonl"])).name,
                ).to_dict()
            if paths.get("manifest"):
                artifacts["manifest"] = store.register_file(
                    paths["manifest"],
                    artifact_type="trace_dataset_manifest",
                    metadata={
                        "graph_run_id": graph_run_id,
                        "record_count": dataset.get("record_count"),
                    },
                    name=Path(str(paths["manifest"])).name,
                ).to_dict()
            project_id = record.get("project_id") or payload.get("project_id")
            graph_id = record.get("graph_id") or payload.get("graph_id")
            if project_id and graph_id:
                self.project_store.append_memory_event(
                    str(project_id),
                    str(graph_id),
                    {"type": "graph", "name": str(graph_id)},
                    "system",
                    (
                        "GraphRun 轨迹数据集已导出。\n"
                        f"- GraphRun：{graph_run_id}\n"
                        f"- 记录数：{dataset.get('record_count')}\n"
                        f"- JSONL：{paths.get('jsonl')}\n"
                        f"- Manifest：{paths.get('manifest')}"
                    ),
                )
            return {
                "dataset": dataset,
                "artifacts": artifacts,
                "agent_context": self.target_context(project_id, graph_id) if project_id else None,
                "snapshot": self.project_store.snapshot() if project_id else None,
            }
        if command == "list_graph_outputs":
            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("list_graph_outputs requires payload.graph_run_id")
            return {"outputs": _list_graph_run_files(self.workspace_root, graph_run_id, "graphoutput")}
        if command == "list_checkpoints":
            from ..graph_saver import list_graph_run_checkpoints

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("list_checkpoints requires payload.graph_run_id")
            return list_graph_run_checkpoints(self.workspace_root, graph_run_id)
        if command == "read_checkpoint":
            from ..graph_saver import read_graph_run_checkpoint

            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            checkpoint_id = str(payload.get("checkpoint_id") or payload.get("checkpoint") or "")
            if not graph_run_id:
                raise ValueError("read_checkpoint requires payload.graph_run_id")
            if not checkpoint_id:
                raise ValueError("read_checkpoint requires payload.checkpoint_id")
            return read_graph_run_checkpoint(self.workspace_root, graph_run_id, checkpoint_id)
        if command == "resume_from_checkpoint":
            return self._resume_from_checkpoint(record, payload)
        raise ValueError(f"unknown graph_runner command: {command}")

    def _resume_from_checkpoint(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        from ..graph_runner.executor import GraphExecutor
        from ..graph_saver import read_graph_run_checkpoint

        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
        checkpoint_id = str(payload.get("checkpoint_id") or payload.get("checkpoint") or "")
        if not graph_run_id:
            raise ValueError("resume_from_checkpoint requires payload.graph_run_id")
        if not checkpoint_id:
            raise ValueError("resume_from_checkpoint requires payload.checkpoint_id")
        reuse_policy = str(payload.get("reuse_policy") or "strict_fingerprint")
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
        if graph is None:
            graph = self.project_store.read_graph(project_id, graph_id)
        checkpoint_result = read_graph_run_checkpoint(self.workspace_root, graph_run_id, checkpoint_id)
        checkpoint = checkpoint_result.get("checkpoint") or {}
        checkpoint_state = checkpoint.get("state")
        if not isinstance(checkpoint_state, dict):
            raise ValueError("checkpoint is missing state")
        graph_node_ids = {str(node.get("id")) for node in graph.get("nodes", [])}
        completed_before = sorted(
            node_id
            for node_id, result in (checkpoint_state.get("node_results") or {}).items()
            if node_id in graph_node_ids and (result or {}).get("status") == "success"
        )
        resume_source = {
            "module": "graph_runner",
            "command": "resume_from_checkpoint",
            "source_graph_run_id": graph_run_id,
            "checkpoint_id": checkpoint_result.get("summary", {}).get("checkpoint_id") or checkpoint_id,
            "checkpoint_node_id": checkpoint.get("node_id"),
            "completed_node_ids": completed_before,
            "checkpoint": checkpoint,
            "reuse_policy": reuse_policy,
            "created_at": utc_now(),
        }
        try:
            run = GraphExecutor(self.workspace_root).run_graph(
                GraphConfig.from_dict(graph),
                initial_state=checkpoint_state,
                skip_completed=True,
                resume_source=resume_source,
                reuse_policy=reuse_policy,
            ).to_dict()
        except Exception as exc:  # noqa: BLE001
            recovery = self._recover_graph_runner_failure(
                record,
                payload,
                graph,
                exc,
                scope={
                    "type": "resume",
                    "source_graph_run_id": graph_run_id,
                    "checkpoint_id": str(resume_source["checkpoint_id"]),
                },
            )
            return {
                "run": {
                    "status": "failed",
                    "graph_id": graph_id,
                    "source_graph_run_id": graph_run_id,
                    "checkpoint_id": resume_source["checkpoint_id"],
                    "error": str(exc),
                },
                "checkpoint": checkpoint_result.get("summary"),
                "resume": {
                    "completed_before_count": len(completed_before),
                    "resumed_node_run_count": 0,
                    "source": resume_source,
                },
                "recovery": recovery,
                "agent_context": self.target_context(project_id, graph_id, recovery.get("node_id")),
                "snapshot": self.project_store.snapshot(),
            }
        self.project_store.record_graph_run(
            project_id,
            graph_id,
            run,
            command_record=record,
            scope={
                "type": "resume",
                "source_graph_run_id": graph_run_id,
                "checkpoint_id": str(resume_source["checkpoint_id"]),
            },
        )
        self.project_store.append_memory_event(
            project_id,
            graph_id,
            {"type": "graph", "name": graph_id},
            "system",
            (
                "已从 checkpoint 续跑 workflow。\n"
                f"- 源 GraphRun：{graph_run_id}\n"
                f"- Checkpoint：{resume_source['checkpoint_id']}\n"
                f"- 复用成功节点数：{len(completed_before)}\n"
                f"- 新执行 NodeRun 数：{len(run.get('node_runs') or [])}\n"
                f"- 新 GraphRun：{run.get('graph_run_id')}"
            ),
        )
        return {
            "run": run,
            "checkpoint": checkpoint_result.get("summary"),
            "resume": {
                "completed_before_count": len(completed_before),
                "resumed_node_run_count": len(run.get("node_runs") or []),
                "source": resume_source,
            },
            "agent_context": self.target_context(project_id, graph_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _execute_data_manager_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..data_manager.artifacts import ArtifactStore

        if command == "snapshot":
            return {
                "snapshot": self.project_store.snapshot(),
                "agent_context": self.target_context(record.get("project_id"), record.get("graph_id"), record.get("node_id")),
            }
        if command == "register_artifact":
            path = str(payload.get("path") or "")
            if not path:
                raise ValueError("register_artifact requires payload.path")
            artifact = ArtifactStore(self.workspace_root).register_file(
                path,
                artifact_type=str(payload.get("type") or payload.get("artifact_type") or "other"),
                metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
                name=payload.get("name"),
            )
            return {"artifact": artifact.to_dict()}
        if command == "list_artifacts":
            return {
                "artifacts": ArtifactStore(self.workspace_root).list_artifacts(
                    limit=int(payload.get("limit") or 200),
                    artifact_type=payload.get("type") or payload.get("artifact_type"),
                )
            }
        if command == "describe_artifact":
            artifact_id = str(payload.get("artifact_id") or "")
            if not artifact_id:
                raise ValueError("describe_artifact requires payload.artifact_id")
            return {"artifact": ArtifactStore(self.workspace_root).describe_artifact(artifact_id)}
        if command == "link_artifact_to_file_tree":
            project_id = _required_project_id(record, payload)
            artifact_id = str(payload.get("artifact_id") or "")
            if not artifact_id:
                raise ValueError("link_artifact_to_file_tree requires payload.artifact_id")
            result = self.project_store.link_artifact_to_file_tree(
                project_id,
                artifact_id,
                str(payload.get("target_scope") or payload.get("scope") or record.get("target_type") or PROJECT_UNCLASSIFIED),
                graph_id=payload.get("graph_id") or record.get("graph_id"),
                node_id=payload.get("node_id") or record.get("node_id"),
                name=payload.get("name"),
            )
            result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "sync_artifact_index":
            project_id = _required_project_id(record, payload)
            return {
                **self.project_store.sync_artifact_index(
                    project_id,
                    graph_id=payload.get("graph_id") or record.get("graph_id"),
                ),
                "snapshot": self.project_store.snapshot(),
            }
        if command == "list_managed_files":
            return {
                "virtual_tree": self.project_store.virtual_tree(),
                "snapshot": self.project_store.snapshot(),
            }
        if command == "graph_folder_info":
            project_id = _required_project_id(record, payload)
            graph_id = _required_graph_id(record, payload)
            return {
                **self.project_store.graph_folder_info(project_id, graph_id),
                "snapshot": self.project_store.snapshot(),
            }
        raise ValueError(f"unknown data_manager command: {command}")

    def _execute_graph_saver_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..graph_saver import (
            export_workflow,
            fork_workflow_from_checkpoint,
            import_workflow,
            list_workflow_versions,
            merge_workflow,
            restore_workflow_version,
            save_workflow_version,
        )

        project_id = _required_project_id(record, payload)
        if command == "import_workflow":
            path = str(payload.get("path") or "")
            if not path:
                raise ValueError("import_workflow requires payload.path")
            result = import_workflow(
                self.project_store,
                project_id,
                path,
                name=payload.get("name"),
            )
            result["snapshot"] = self.project_store.snapshot()
            return result
        graph_id = _required_graph_id(record, payload)
        if command == "save_workflow":
            result = save_workflow_version(
                self.project_store,
                project_id,
                graph_id,
                graph=payload.get("graph") if isinstance(payload.get("graph"), dict) else None,
                note=payload.get("note"),
                source=str(payload.get("source") or record.get("origin") or "agent"),
            )
            result["agent_context"] = self.target_context(project_id, graph_id)
            result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "list_versions":
            return list_workflow_versions(self.project_store, project_id, graph_id)
        if command == "restore_version":
            version_id = str(payload.get("version_id") or payload.get("version") or "")
            if not version_id:
                raise ValueError("restore_version requires payload.version_id")
            result = restore_workflow_version(self.project_store, project_id, graph_id, version_id)
            result["agent_context"] = self.target_context(project_id, graph_id)
            result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "export_workflow":
            return export_workflow(
                self.project_store,
                project_id,
                graph_id,
                output_path=payload.get("output_path"),
                include_versions=bool(payload.get("include_versions")),
            )
        if command == "merge_workflow":
            attach_to = payload.get("attach_to")
            if attach_to is not None and not isinstance(attach_to, list):
                raise ValueError("merge_workflow payload.attach_to must be a list")
            result = merge_workflow(
                self.project_store,
                project_id,
                graph_id,
                source_graph=payload.get("source_graph") if isinstance(payload.get("source_graph"), dict) else None,
                source_graph_id=payload.get("source_graph_id"),
                path=payload.get("path"),
                prefix=payload.get("prefix"),
                attach_to=[str(item) for item in attach_to] if isinstance(attach_to, list) else None,
                output_policy=str(payload.get("output_policy") or "append"),
                note=payload.get("note"),
            )
            result["agent_context"] = self.target_context(project_id, graph_id)
            result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "fork_from_checkpoint":
            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            checkpoint_id = str(payload.get("checkpoint_id") or payload.get("checkpoint") or "")
            if not graph_run_id:
                raise ValueError("fork_from_checkpoint requires payload.graph_run_id")
            if not checkpoint_id:
                raise ValueError("fork_from_checkpoint requires payload.checkpoint_id")
            result = fork_workflow_from_checkpoint(
                self.project_store,
                project_id,
                graph_id,
                graph_run_id=graph_run_id,
                checkpoint_id=checkpoint_id,
                name=payload.get("name"),
                note=payload.get("note"),
            )
            result["snapshot"] = self.project_store.snapshot()
            return result
        raise ValueError(f"unknown graph_saver command: {command}")

    def _execute_knowledge_graph_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..knowledge_graph import (
            build_for_project,
            build_view_for_node,
            decay_noisy_items,
            refresh_from_run,
            update_weights_from_feedback,
        )

        if command == "build_for_project":
            project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            if graph is None and project_id != "runtime":
                graph_id = payload.get("graph_id") or record.get("graph_id")
                if graph_id:
                    graph = self.project_store.read_graph(project_id, str(graph_id))
            return {"knowledge_graph": build_for_project(project_id, workspace=self.workspace_root, graph=graph)}
        if command == "refresh_from_run":
            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            if not graph_run_id:
                raise ValueError("refresh_from_run requires payload.graph_run_id")
            return {
                "knowledge_graph": refresh_from_run(
                    graph_run_id,
                    workspace=self.workspace_root,
                    project_id=payload.get("project_id") or record.get("project_id"),
                )
            }
        if command == "build_view_for_node":
            project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
            graph_id = str(payload.get("graph_id") or record.get("graph_id") or "")
            node_id = str(payload.get("node_id") or record.get("node_id") or "")
            if not graph_id:
                graph_id = _current_graph_id(self.project_store) or "graph"
            if not node_id:
                raise ValueError("build_view_for_node requires payload.node_id or record.node_id")
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            return {
                "knowledge_view": build_view_for_node(
                    project_id,
                    graph_id,
                    node_id,
                    workspace=self.workspace_root,
                    graph=graph,
                    query=str(payload.get("query") or ""),
                    limit=int(payload.get("limit") or 12),
                )
            }
        if command == "update_weights_from_feedback":
            node_run_id = str(payload.get("node_run_id") or "")
            if not node_run_id:
                raise ValueError("update_weights_from_feedback requires payload.node_run_id")
            return {
                "feedback_update": update_weights_from_feedback(
                    node_run_id,
                    workspace=self.workspace_root,
                    graph_run_id=payload.get("graph_run_id") or payload.get("run_id"),
                    project_id=payload.get("project_id") or record.get("project_id"),
                )
            }
        if command == "decay_noisy_items":
            project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
            return {
                "decay": decay_noisy_items(
                    project_id,
                    workspace=self.workspace_root,
                    decay=float(payload.get("decay") or 0.05),
                )
            }
        raise ValueError(f"unknown knowledge_graph command: {command}")

    def _execute_node_memory_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..node_memory import (
            prepare_node_context,
            record_context_usage,
            summarize_context_for_model,
            update_gap_state,
        )

        if command == "prepare_node_context":
            project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
            graph_id = str(payload.get("graph_id") or record.get("graph_id") or _current_graph_id(self.project_store) or "graph")
            node_id = str(payload.get("node_id") or record.get("node_id") or "")
            if not node_id:
                raise ValueError("prepare_node_context requires payload.node_id or record.node_id")
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            if graph is None and project_id != "runtime" and graph_id != "graph":
                graph = self.project_store.read_graph(project_id, graph_id)
            packet = prepare_node_context(
                workspace=self.workspace_root,
                project_id=project_id,
                graph_id=graph_id,
                node_id=node_id,
                graph=graph,
                node=payload.get("node") if isinstance(payload.get("node"), dict) else None,
                state=payload.get("state") if isinstance(payload.get("state"), dict) else None,
                graph_run_id=payload.get("graph_run_id"),
                node_run_id=payload.get("node_run_id"),
                input_snapshot=payload.get("input_snapshot") if isinstance(payload.get("input_snapshot"), dict) else None,
                lineage_context=payload.get("lineage_context") if isinstance(payload.get("lineage_context"), dict) else None,
            )
            return {"packet": packet, "model_context": summarize_context_for_model(packet)}
        if command == "summarize_context_for_model":
            packet = payload.get("packet")
            if not isinstance(packet, dict):
                raise ValueError("summarize_context_for_model requires payload.packet")
            return {"model_context": summarize_context_for_model(packet)}
        if command == "record_context_usage":
            project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
            usage = payload.get("usage")
            if not isinstance(usage, dict):
                raise ValueError("record_context_usage requires payload.usage")
            return {"usage": record_context_usage(project_id, usage, workspace=self.workspace_root)}
        if command == "update_gap_state":
            project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
            graph_id = str(payload.get("graph_id") or record.get("graph_id") or "graph")
            node_id = str(payload.get("node_id") or record.get("node_id") or "")
            gaps = payload.get("gaps")
            if not node_id:
                raise ValueError("update_gap_state requires payload.node_id or record.node_id")
            if not isinstance(gaps, list):
                raise ValueError("update_gap_state requires payload.gaps list")
            return {"gap_state": update_gap_state(project_id, graph_id, node_id, [str(item) for item in gaps], workspace=self.workspace_root)}
        raise ValueError(f"unknown node_memory command: {command}")

    def _execute_execution_lineage_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..execution_lineage import (
            list_dirty_nodes,
            plan_replay_from_checkpoint,
            record_node_lineage,
            verify_node_inputs,
        )
        from ..graph_saver import read_graph_run_checkpoint

        project_id = str(payload.get("project_id") or record.get("project_id") or "runtime")
        graph_id = str(payload.get("graph_id") or record.get("graph_id") or _current_graph_id(self.project_store) or "graph")
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
        if graph is None and project_id != "runtime" and graph_id != "graph":
            graph = self.project_store.read_graph(project_id, graph_id)
        checkpoint = payload.get("checkpoint") if isinstance(payload.get("checkpoint"), dict) else None
        source_graph_run_id = str(payload.get("source_graph_run_id") or payload.get("graph_run_id") or payload.get("run_id") or "")
        checkpoint_id = str(payload.get("checkpoint_id") or "")
        if checkpoint is None and source_graph_run_id and checkpoint_id:
            checkpoint = read_graph_run_checkpoint(self.workspace_root, source_graph_run_id, checkpoint_id).get("checkpoint")

        if command == "verify_node_inputs":
            node_id = str(payload.get("node_id") or record.get("node_id") or "")
            if not node_id:
                raise ValueError("verify_node_inputs requires payload.node_id or record.node_id")
            if graph is None:
                raise ValueError("verify_node_inputs requires graph context")
            return {
                "lineage_preflight": verify_node_inputs(
                    workspace=self.workspace_root,
                    graph=graph,
                    node_id=node_id,
                    state=payload.get("state") if isinstance(payload.get("state"), dict) else None,
                    graph_run_id=payload.get("graph_run_id") or payload.get("run_id"),
                    node_run_id=payload.get("node_run_id"),
                    input_snapshot=payload.get("input_snapshot") if isinstance(payload.get("input_snapshot"), dict) else None,
                    route_decision=payload.get("route_decision") if isinstance(payload.get("route_decision"), dict) else None,
                    context_packet_hash=payload.get("context_packet_hash"),
                )
            }
        if command == "record_node_lineage":
            graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
            node_run = payload.get("node_run")
            if not graph_run_id:
                raise ValueError("record_node_lineage requires payload.graph_run_id")
            if not isinstance(node_run, dict):
                raise ValueError("record_node_lineage requires payload.node_run object")
            return {
                "lineage_record": record_node_lineage(
                    workspace=self.workspace_root,
                    graph_run_id=graph_run_id,
                    node_run=node_run,
                    preflight_verdict=payload.get("preflight_verdict") if isinstance(payload.get("preflight_verdict"), dict) else None,
                    postflight_verdict=payload.get("postflight_verdict") if isinstance(payload.get("postflight_verdict"), dict) else None,
                    checkpoint_id=payload.get("checkpoint_id"),
                    context_packet_hash=payload.get("context_packet_hash"),
                )
            }
        if command == "plan_replay_from_checkpoint":
            if graph is None:
                raise ValueError("plan_replay_from_checkpoint requires graph context")
            if not isinstance(checkpoint, dict):
                raise ValueError("plan_replay_from_checkpoint requires checkpoint")
            return {
                "replay_plan": plan_replay_from_checkpoint(
                    workspace=self.workspace_root,
                    graph=graph,
                    checkpoint=checkpoint,
                    current_state=payload.get("current_state") if isinstance(payload.get("current_state"), dict) else None,
                    source_graph_run_id=source_graph_run_id or None,
                    reuse_policy=str(payload.get("reuse_policy") or "strict_fingerprint"),
                )
            }
        if command == "list_dirty_nodes":
            return {
                "dirty_nodes": list_dirty_nodes(
                    workspace=self.workspace_root,
                    graph=graph,
                    checkpoint=checkpoint,
                    current_state=payload.get("current_state") if isinstance(payload.get("current_state"), dict) else None,
                    graph_run_id=source_graph_run_id or None,
                    reuse_policy=str(payload.get("reuse_policy") or "strict_fingerprint"),
                )
            }
        raise ValueError(f"unknown execution_lineage command: {command}")

    def _execute_reflection_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..reflection import apply_feedback_updates, run_online_reflection

        node_run_id = str(payload.get("node_run_id") or "")
        if not node_run_id:
            raise ValueError(f"{command} requires payload.node_run_id")
        if command == "run_online_reflection":
            return {
                "reflection": run_online_reflection(
                    node_run_id,
                    workspace=self.workspace_root,
                    graph_run_id=payload.get("graph_run_id") or payload.get("run_id"),
                )
            }
        if command == "apply_feedback_updates":
            return {
                "feedback_update": apply_feedback_updates(
                    node_run_id,
                    workspace=self.workspace_root,
                    graph_run_id=payload.get("graph_run_id") or payload.get("run_id"),
                    project_id=payload.get("project_id") or record.get("project_id"),
                )
            }
        raise ValueError(f"unknown reflection command: {command}")

    def _execute_graph_optimizer_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..graph_optimizer import (
            analyze_graph_runs,
            compute_edge_utilities,
            materialize_new_graph_version,
            mine_reusable_subgraphs,
            suggest_structure_changes,
        )

        if command == "analyze_graph_runs":
            graph_id = str(payload.get("graph_id") or record.get("graph_id") or "")
            if not graph_id:
                raise ValueError("analyze_graph_runs requires payload.graph_id or record.graph_id")
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            if graph is None and record.get("project_id"):
                try:
                    graph = self.project_store.read_graph(str(record["project_id"]), graph_id)
                except FileNotFoundError:
                    graph = None
            graph_run_ids = payload.get("graph_run_ids")
            if graph_run_ids is not None and not isinstance(graph_run_ids, list):
                raise ValueError("payload.graph_run_ids must be a list")
            return {
                "analysis": analyze_graph_runs(
                    graph_id,
                    workspace=self.workspace_root,
                    graph=graph,
                    graph_run_ids=[str(item) for item in graph_run_ids] if graph_run_ids else None,
                    version_range=payload.get("version_range"),
                )
            }
        if command == "compute_edge_utilities":
            graph = payload.get("graph")
            if not isinstance(graph, dict):
                raise ValueError("compute_edge_utilities requires payload.graph")
            return {"edge_utilities": compute_edge_utilities(graph, workspace=self.workspace_root, graph_id=payload.get("graph_id") or record.get("graph_id"))}
        if command == "mine_reusable_subgraphs":
            graph = payload.get("graph")
            if not isinstance(graph, dict):
                raise ValueError("mine_reusable_subgraphs requires payload.graph")
            return {"subgraph_candidates": mine_reusable_subgraphs(graph, workspace=self.workspace_root, graph_id=payload.get("graph_id") or record.get("graph_id"))}
        if command == "suggest_structure_changes":
            edge_utilities = payload.get("edge_utilities")
            if not isinstance(edge_utilities, list):
                raise ValueError("suggest_structure_changes requires payload.edge_utilities list")
            subgraphs = payload.get("subgraph_candidates")
            if subgraphs is not None and not isinstance(subgraphs, list):
                raise ValueError("payload.subgraph_candidates must be a list")
            return {"suggestions": suggest_structure_changes(edge_utilities, subgraphs)}
        if command == "materialize_new_graph_version":
            graph = payload.get("graph")
            suggestions = payload.get("suggestions")
            if not isinstance(graph, dict):
                raise ValueError("materialize_new_graph_version requires payload.graph")
            if not isinstance(suggestions, list):
                raise ValueError("materialize_new_graph_version requires payload.suggestions")
            return {
                "version": materialize_new_graph_version(
                    graph,
                    suggestions,
                    workspace=self.workspace_root,
                    project_id=payload.get("project_id") or record.get("project_id"),
                    graph_id=payload.get("graph_id") or record.get("graph_id"),
                    persist=bool(payload.get("persist")),
                )
            }
        raise ValueError(f"unknown graph_optimizer command: {command}")

    def _execute_evaluation_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..evaluation import compare_graph_versions, graph_metrics, rank_graph_versions
        from ..evaluation.reporting import render_evaluation_report

        if command == "compare_graph_versions":
            base_graph = payload.get("base_graph")
            candidate_graph = payload.get("candidate_graph")
            if not isinstance(base_graph, dict) or not isinstance(candidate_graph, dict):
                raise ValueError("compare_graph_versions requires base_graph and candidate_graph")
            return {"comparison": compare_graph_versions(base_graph, candidate_graph)}
        if command == "graph_metrics":
            graph = payload.get("graph")
            if not isinstance(graph, dict):
                raise ValueError("graph_metrics requires payload.graph")
            return {"metrics": graph_metrics(graph)}
        if command == "render_evaluation_report":
            comparison = payload.get("comparison")
            if not isinstance(comparison, dict):
                raise ValueError("render_evaluation_report requires payload.comparison")
            return {"markdown": render_evaluation_report(comparison)}
        if command == "rank_graph_versions":
            entries = payload.get("entries")
            if not isinstance(entries, list):
                raise ValueError("rank_graph_versions requires payload.entries list")
            return {"leaderboard": rank_graph_versions(entries)}
        raise ValueError(f"unknown evaluation command: {command}")

    def _execute_playbooks_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..playbooks import match_playbooks, promote_reusable_subgraphs, serialize_subgraph

        if command == "serialize_subgraph":
            graph = payload.get("graph")
            if not isinstance(graph, dict):
                raise ValueError("serialize_subgraph requires payload.graph")
            node_ids = payload.get("node_ids")
            if not isinstance(node_ids, list):
                raise ValueError("serialize_subgraph requires payload.node_ids list")
            return {
                "playbook": serialize_subgraph(
                    graph,
                    [str(item) for item in node_ids],
                    name=payload.get("name"),
                    workspace=self.workspace_root,
                    project_id=payload.get("project_id") or record.get("project_id"),
                    write=bool(payload.get("write")),
                )
            }
        if command == "promote_reusable_subgraphs":
            graph = payload.get("graph")
            if not isinstance(graph, dict):
                raise ValueError("promote_reusable_subgraphs requires payload.graph")
            candidates = payload.get("subgraph_candidates")
            if not isinstance(candidates, list):
                raise ValueError("promote_reusable_subgraphs requires payload.subgraph_candidates list")
            return {
                "promotion": promote_reusable_subgraphs(
                    graph,
                    candidates,
                    workspace=self.workspace_root,
                    project_id=payload.get("project_id") or record.get("project_id"),
                    min_support=int(payload.get("min_support") or 2),
                    write=bool(payload.get("write", True)),
                )
            }
        if command == "match_playbooks":
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            return {
                "matches": match_playbooks(
                    graph,
                    task=str(payload.get("task") or payload.get("prompt") or ""),
                    workspace=self.workspace_root,
                    project_id=payload.get("project_id") or record.get("project_id"),
                    limit=int(payload.get("limit") or 5),
                )
            }
        raise ValueError(f"unknown playbooks command: {command}")

    def _execute_model_routing_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "load_environment":
            from ..model_routing.settings import load_env_file

            return {"env_path": str(load_env_file())}
        if command == "read_settings":
            from ..model_routing.settings import read_settings

            return {"settings": read_settings()}
        if command == "update_settings":
            from ..model_routing.settings import update_settings

            return {"settings": update_settings(payload)}
        if command == "chat_completion":
            from ..model_routing.llm_client import chat_completion
            from .context_budget import resolve_max_tokens

            prompt = str(payload.get("prompt") or "")
            if not prompt:
                raise ValueError("chat_completion requires payload.prompt")
            fallback_profiles = payload.get("fallback_profiles")
            if fallback_profiles is not None and not isinstance(fallback_profiles, list):
                raise ValueError("payload.fallback_profiles must be a list")
            profile = str(payload.get("profile") or "complex")
            return {
                "completion": chat_completion(
                    prompt,
                    profile=profile,
                    system=payload.get("system"),
                    fallback_profiles=fallback_profiles,
                    max_tokens=resolve_max_tokens(payload.get("max_tokens"), profile=profile, prompt=prompt),
                    temperature=float(payload.get("temperature") or 0.2),
                    timeout_seconds=(
                        float(payload["timeout_seconds"])
                        if payload.get("timeout_seconds") is not None
                        else None
                    ),
                )
            }
        if command == "route_node":
            graph = payload.get("graph")
            node_id = str(payload.get("node_id") or "")
            if not isinstance(graph, dict):
                raise ValueError("route_node requires payload.graph")
            if not node_id:
                raise ValueError("route_node requires payload.node_id")
            config = GraphConfig.from_dict(graph)
            by_id = {node.node_id: node for node in config.nodes}
            if node_id not in by_id:
                raise FileNotFoundError(f"node not found: {node_id}")
            from ..core.types import GraphState
            from ..model_routing.routing import route_model

            decision = route_model(
                config,
                by_id[node_id],
                GraphState(context=config.context, experiment=config.experiment),
            )
            return {"route": decision.to_dict()}
        raise ValueError(f"unknown model_routing command: {command}")

    def _execute_agent_runtime_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if command == "list_tools":
            target = payload.get("target") or payload.get("target_type") or record.get("target_type")
            return {"tools": self.list_tools(str(target) if target else None)}
        if command == "list_common_tools":
            target = payload.get("target") or payload.get("target_type") or record.get("target_type")
            return {"tools": get_tool_schemas(str(target) if target else None)}
        if command == "execute_tool":
            tool_name = str(payload.get("tool") or payload.get("name") or "")
            if not tool_name:
                raise ValueError("execute_tool requires payload.tool")
            arguments = payload.get("arguments")
            if arguments is None:
                arguments = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"tool", "name", "use_cache", "allow_outside_workspace"}
                }
            if not isinstance(arguments, dict):
                raise ValueError("payload.arguments must be an object")
            return {
                "tool_result": execute_registered_tool(
                    tool_name,
                    arguments,
                    workspace_root=str(self.workspace_root),
                    allow_outside_workspace=bool(payload.get("allow_outside_workspace", True)),
                    use_cache=bool(payload.get("use_cache", True)),
                )
            }
        if command == "list_modules":
            return {"modules": list_modules()}
        if command == "list_module_commands":
            module = payload.get("module")
            target = payload.get("target") or payload.get("target_type")
            return {
                "commands": list_module_commands(
                    str(module) if module else None,
                    str(target) if target else None,
                    queue_enabled=True,
                )
            }
        if command == "list_module_skills":
            from .skills import list_module_skills

            module = payload.get("module")
            return {"skills": list_module_skills(str(module) if module else None)}
        if command == "recommend_next_modules":
            from .skills import recommend_next_modules

            module = str(payload.get("module") or "")
            if not module:
                raise ValueError("recommend_next_modules requires payload.module")
            return {
                "recommendation": recommend_next_modules(
                    module,
                    event=str(payload.get("event") or ""),
                    error=str(payload.get("error") or ""),
                )
            }
        if command == "target_context":
            return {
                "agent_context": self.target_context(
                    payload.get("project_id") or record.get("project_id"),
                    payload.get("graph_id") or record.get("graph_id"),
                    payload.get("node_id") or record.get("node_id"),
                )
            }
        if command == "recover_graph_failure":
            return self._recover_graph_failure_command(record, payload)
        raise ValueError(f"unknown agent_runtime command: {command}")

    def _execute_task_decompose_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if command == "decompose_task_to_graph":
            project_id = _required_project_id(record, payload)
            prompt = str(payload.get("prompt") or "")
            if not prompt:
                raise ValueError("decompose_task_to_graph requires payload.prompt")
            graph_id = payload.get("graph_id") or record.get("graph_id")
            create_new_graph = payload.get("create_new_graph")
            if create_new_graph is None:
                create_new_graph = not bool(graph_id)
            result = self.project_store.decompose_task_to_graph(
                project_id,
                prompt,
                graph_id=str(graph_id) if graph_id else None,
                name=payload.get("name"),
                create_new_graph=bool(create_new_graph),
            )
            resolved_graph_id = result.get("graph", {}).get("graph_id") or graph_id
            result["agent_context"] = self.target_context(project_id, resolved_graph_id)
            result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "replan_subgraph":
            from ..task_decompose.main import replan_subgraph

            project_id = _required_project_id(record, payload)
            graph_id = _required_graph_id(record, payload)
            failed_node_id = str(payload.get("failed_node_id") or payload.get("node_id") or record.get("node_id") or "")
            if not failed_node_id:
                raise ValueError("replan_subgraph requires payload.failed_node_id")
            result = replan_subgraph(
                self.workspace_root,
                project_id,
                graph_id,
                failed_node_id,
                failure_analysis=payload.get("failure_analysis") if isinstance(payload.get("failure_analysis"), dict) else None,
                graph=payload.get("graph") if isinstance(payload.get("graph"), dict) else None,
                replacement_strategy=str(payload.get("replacement_strategy") or "repair_then_retry"),
                recovery_node_names=payload.get("recovery_node_names") if isinstance(payload.get("recovery_node_names"), list) else None,
                rewrite_downstream_dependencies=bool(payload.get("rewrite_downstream_dependencies", True)),
                save=bool(payload.get("save")),
                apply=bool(payload.get("apply")) if "apply" in payload else None,
            )
            result["agent_context"] = self.target_context(project_id, graph_id, result.get("patch", {}).get("replacement_node_id"))
            result["snapshot"] = self.project_store.snapshot()
            return result
        if command == "build_decompose_prompt":
            from ..task_decompose.recovery import build_decompose_prompt

            graph_id = payload.get("graph_id") or record.get("graph_id")
            graph = (
                self.project_store.read_graph(_required_project_id(record, payload), str(graph_id))
                if graph_id and (record.get("project_id") or payload.get("project_id"))
                else {}
            )
            task = _recovery_task_text(graph, payload, record)
            return {
                "prompt": build_decompose_prompt(
                    task=task,
                    error=str(payload.get("error") or ""),
                    failed_node_id=str(payload.get("failed_node_id") or record.get("node_id") or "") or None,
                    inputs=payload.get("inputs") if isinstance(payload.get("inputs"), dict) else None,
                    output_spec=payload.get("output_spec") if isinstance(payload.get("output_spec"), dict) else None,
                )
            }
        if command == "decompose_task":
            from ..task_decompose.recovery import build_decompose_prompt

            project_id = _required_project_id(record, payload)
            graph_id = payload.get("graph_id") or record.get("graph_id")
            graph = self.project_store.read_graph(project_id, str(graph_id)) if graph_id else {}
            task = _recovery_task_text(graph, payload, record)
            prompt = build_decompose_prompt(
                task=task,
                error=str(payload.get("error") or ""),
                failed_node_id=str(payload.get("failed_node_id") or record.get("node_id") or "") or None,
                inputs=payload.get("inputs") if isinstance(payload.get("inputs"), dict) else None,
                output_spec=payload.get("output_spec") if isinstance(payload.get("output_spec"), dict) else None,
            )
            create_new_graph = payload.get("create_new_graph")
            if create_new_graph is None:
                create_new_graph = not bool(graph_id)
            result = self.project_store.decompose_task_to_graph(
                project_id,
                prompt,
                graph_id=str(graph_id) if graph_id else None,
                name=payload.get("name"),
                create_new_graph=bool(create_new_graph),
            )
            resolved_graph_id = result.get("graph", {}).get("graph_id") or graph_id
            result["recovery_prompt"] = prompt
            result["agent_context"] = self.target_context(project_id, resolved_graph_id)
            result["snapshot"] = self.project_store.snapshot()
            return result
        raise ValueError(f"unknown task_decompose command: {command}")

    def _execute_memory_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..memory.context import find_relevant_memories, get_memory_context

        project_id = record.get("project_id") or payload.get("project_id")
        graph_id = record.get("graph_id") or payload.get("graph_id")
        graph = (
            self.project_store.read_graph(str(project_id), str(graph_id))
            if project_id and graph_id
            else None
        )
        node_id = str(payload.get("node_id") or record.get("node_id") or "") or None
        query = str(payload.get("query") or payload.get("prompt") or node_id or graph_id or project_id or "")
        if command == "find_relevant_memories":
            return {
                "memories": find_relevant_memories(
                    query,
                    workspace_root=self.workspace_root,
                    graph=graph,
                    node_id=node_id,
                    max_results=int(payload.get("max_results") or 6),
                )
            }
        if command == "get_memory_context":
            return {
                "memory_context": get_memory_context(
                    workspace_root=self.workspace_root,
                    graph=graph,
                    node_id=node_id,
                    query=query,
                    max_results=int(payload.get("max_results") or 6),
                    max_chars=int(payload.get("max_chars") or 20000),
                )
            }
        raise ValueError(f"unknown memory command: {command}")

    def _execute_multi_agent_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..multi_agent.tools import _agent_tool, plan_parallel_node_agents

        project_id = record.get("project_id") or payload.get("project_id")
        graph_id = record.get("graph_id") or payload.get("graph_id")
        if command == "create_agent_task":
            params = dict(payload)
            params.setdefault("project_id", project_id)
            params.setdefault("graph_id", graph_id)
            params.setdefault("node_id", record.get("node_id"))
            return {
                "agent_task": _agent_tool(
                    params,
                    {
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_id": record.get("node_id"),
                    },
                )
            }
        if command == "plan_parallel_node_agents":
            graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
            if graph is None:
                project_id = _required_project_id(record, payload)
                graph_id = _required_graph_id(record, payload)
                graph = self.project_store.read_graph(project_id, graph_id)
            return {
                "parallel_agent_plan": plan_parallel_node_agents(
                    graph,
                    project_id=str(project_id) if project_id else None,
                    graph_id=str(graph_id) if graph_id else graph.get("graph_id"),
                    target_layer=payload.get("target_layer"),
                )
            }
        raise ValueError(f"unknown multi_agent command: {command}")

    def _execute_research_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from urllib.parse import quote

        from ..data_manager.artifacts import ArtifactStore
        from ..research.synthesizer import (
            brief_from_outputs,
            render_citations,
            render_report_files,
            render_without_llm,
        )

        brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else None
        if brief is None:
            brief = brief_from_outputs(
                topic=str(payload.get("topic") or "GraphyAgent Report"),
                outputs=payload.get("outputs") or payload.get("results") or {},
            )
        if command == "render_citations":
            return {"citations": render_citations(brief)}
        if command == "render_without_llm":
            return {"markdown": render_without_llm(brief)}
        if command == "render_report":
            graph_id = record.get("graph_id") or payload.get("graph_id") or "graph"
            output_dir = _workspace_output_dir(
                self.workspace_root,
                payload.get("output_dir") or Path("reports") / _safe_path_name(str(graph_id)),
            )
            result = render_report_files(
                brief,
                output_dir=output_dir,
                basename=str(payload.get("basename") or payload.get("topic") or "report"),
                include_html=bool(payload.get("include_html", True)),
            )
            store = ArtifactStore(self.workspace_root)
            artifacts = {
                key: store.register_file(
                    path,
                    artifact_type="report" if key in {"markdown", "html"} else "citations",
                    metadata={"renderer": "research.synthesizer", "preview": key == "html"},
                    name=Path(path).name,
                ).to_dict()
                for key, path in (result.get("paths") or {}).items()
            }
            preview_path = str(result.get("preview_path") or "")
            return {
                "report": {key: value for key, value in result.items() if key not in {"markdown"}},
                "artifacts": artifacts,
                "preview_url": f"/api/files/open?path={quote(preview_path)}" if preview_path else None,
            }
        raise ValueError(f"unknown research command: {command}")

    def _execute_node_audit_command(
        self,
        command: str,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if command == "validate_node_contract":
            from ..node_audit.main import validate_contract

            project_id = _required_project_id(record, payload)
            graph_id = _required_graph_id(record, payload)
            node_id = str(payload.get("node_id") or record.get("node_id") or "")
            if not node_id:
                raise ValueError("validate_node_contract requires payload.node_id or record.node_id")
            update_graph = payload.get("update_graph")
            if update_graph is None:
                update_graph = True
            result = validate_contract(
                self.workspace_root,
                project_id,
                graph_id,
                node_id,
                graph=payload.get("graph") if isinstance(payload.get("graph"), dict) else None,
                update_graph=bool(update_graph),
            )
            result["agent_context"] = self.target_context(project_id, graph_id, result.get("node_id"))
            if "snapshot" not in result:
                result["snapshot"] = self.project_store.snapshot()
            return result
        raise ValueError(f"unknown node_audit command: {command}")

    def _create_project(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project = self.project_store.create_project(str(payload.get("name") or "New Project"))
        return {
            "project": project,
            "agent_context": self.target_context(project["project_id"]),
            "snapshot": self.project_store.snapshot(),
        }

    def _select_project(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        project = self.project_store.select_project(project_id)
        return {
            "project": project,
            "agent_context": self.target_context(project_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _delete_project(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        result = self.project_store.delete_project(project_id)
        return {"result": result, "snapshot": self.project_store.snapshot()}

    def _create_graph(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph = self.project_store.create_graph(
            project_id,
            str(payload.get("name") or "New Graph"),
            payload.get("graph") if isinstance(payload.get("graph"), dict) else None,
        )
        return {
            "graph": graph,
            "agent_context": self.target_context(project_id, graph["graph_id"]),
            "snapshot": self.project_store.snapshot(),
        }

    def _select_graph(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        graph = self.project_store.select_graph(project_id, graph_id)
        return {
            "graph": graph,
            "agent_context": self.target_context(project_id, graph_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _delete_graph(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        result = self.project_store.delete_graph(project_id, graph_id)
        return {
            "result": result,
            "agent_context": self.target_context(project_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _save_graph(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        graph = payload.get("graph")
        if not isinstance(graph, dict):
            raise ValueError("save_graph requires payload.graph")
        result = self.project_store.save_graph(project_id, graph_id, graph)
        result["agent_context"] = self.target_context(project_id, graph_id)
        result["snapshot"] = self.project_store.snapshot()
        return result

    def _update_node_task(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        node_id = str(payload.get("node_id") or record.get("node_id") or "")
        result = self.project_store.update_node_task(
            project_id,
            graph_id,
            node_id,
            name=payload.get("name"),
            description=payload.get("description"),
        )
        result["agent_context"] = self.target_context(project_id, graph_id, result.get("node_id"))
        result["snapshot"] = self.project_store.snapshot()
        return result

    def _run_graph(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
        if graph is None:
            graph = self.project_store.read_graph(project_id, graph_id)
        try:
            run = run_graph(GraphConfig.from_dict(graph), self.workspace_root)
        except Exception as exc:  # noqa: BLE001
            if payload.get("disable_recovery"):
                return {
                    "run": {"status": "failed", "graph_id": graph_id, "error": str(exc)},
                    "agent_context": self.target_context(project_id, graph_id),
                    "snapshot": self.project_store.snapshot(),
                }
            recovery = self._recover_graph_runner_failure(record, payload, graph, exc, scope={"type": "graph"})
            return {
                "run": {"status": "failed", "graph_id": graph_id, "error": str(exc)},
                "recovery": recovery,
                "agent_context": self.target_context(project_id, graph_id, recovery.get("node_id")),
                "snapshot": self.project_store.snapshot(),
            }
        self.project_store.record_graph_run(project_id, graph_id, run, command_record=record)
        return {
            "run": run,
            "agent_context": self.target_context(project_id, graph_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _run_node(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
        if graph is None:
            graph = self.project_store.read_graph(project_id, graph_id)
        node_id = str(record.get("node_id") or payload.get("node_id") or "")
        node_graph = graph_for_node(graph, node_id)
        try:
            run = run_graph(GraphConfig.from_dict(node_graph), self.workspace_root)
        except Exception as exc:  # noqa: BLE001
            if payload.get("disable_recovery"):
                return {
                    "run": {"status": "failed", "graph_id": graph_id, "node_id": node_id, "error": str(exc)},
                    "agent_context": self.target_context(project_id, graph_id, node_id),
                    "snapshot": self.project_store.snapshot(),
                }
            recovery = self._recover_graph_runner_failure(
                record,
                payload,
                graph,
                exc,
                scope={"type": "node", "node_id": node_id},
            )
            return {
                "run": {"status": "failed", "graph_id": graph_id, "node_id": node_id, "error": str(exc)},
                "recovery": recovery,
                "agent_context": self.target_context(project_id, graph_id, recovery.get("node_id") or node_id),
                "snapshot": self.project_store.snapshot(),
            }
        self.project_store.record_graph_run(
            project_id,
            graph_id,
            run,
            command_record=record,
            scope={"type": "node", "node_id": node_id},
        )
        return {
            "run": run,
            "agent_context": self.target_context(project_id, graph_id, node_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _recover_graph_failure_command(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        from ..graph_runner.main import classify_node_failure, pause_for_replan
        from ..task_decompose.main import replan_subgraph
        from .skills import recommend_next_modules

        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        graph_run_id = str(payload.get("graph_run_id") or payload.get("run_id") or "")
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else None
        if graph is None:
            graph = self.project_store.read_graph(project_id, graph_id)

        failure_analysis = payload.get("failure_analysis") if isinstance(payload.get("failure_analysis"), dict) else None
        if failure_analysis is None:
            failure_analysis = classify_node_failure(
                self.workspace_root,
                graph_run_id or None,
                node_run_id=payload.get("node_run_id"),
                node_id=payload.get("node_id") or record.get("node_id"),
                error=payload.get("error"),
                graph=graph,
            )
        failed_node_id = str(
            payload.get("failed_node_id")
            or payload.get("node_id")
            or record.get("node_id")
            or failure_analysis.get("node_id")
            or _parse_failed_node_id(str(failure_analysis.get("error") or payload.get("error") or ""))
            or ""
        )
        failure_scope = str(failure_analysis.get("failure_scope") or "node_local")
        force_replan = bool(payload.get("force_replan"))
        apply_replan = bool(payload.get("apply") or payload.get("save"))
        result: dict[str, Any] = {
            "schema": "graphyagent.recover_graph_failure.v1",
            "project_id": project_id,
            "graph_id": graph_id,
            "graph_run_id": graph_run_id or None,
            "node_id": failed_node_id or None,
            "failure_analysis": failure_analysis,
            "actions": [],
        }

        if failure_scope not in {"graph_level", "plan_level"} and not force_replan:
            plan = recommend_next_modules("graph_runner", event="node_failure", error=str(failure_analysis.get("error") or ""))
            result.update({
                "status": "node_local_recovery_recommended",
                "skill_plan": plan,
                "next_modules": [
                    module for module in (plan.get("next_modules") or [])
                    if module in {"model_routing", "task_decompose", "node_audit"}
                ],
                "next_action": failure_analysis.get("next_action") or "retry or decompose the failed node locally",
            })
            self.project_store.append_memory_event(
                project_id,
                graph_id,
                {"type": "node" if failed_node_id else "graph", "name": failed_node_id or graph_id},
                "system",
                (
                    "节点失败已分类为局部恢复问题。\n"
                    f"- 节点：{failed_node_id or '未知'}\n"
                    f"- 分类：{failure_scope}\n"
                    f"- 推荐模块：{', '.join(result.get('next_modules') or []) or '无'}"
                ),
            )
            result["agent_context"] = self.target_context(project_id, graph_id, failed_node_id or None)
            result["snapshot"] = self.project_store.snapshot()
            return result

        pause = None
        if graph_run_id:
            pause = pause_for_replan(
                self.workspace_root,
                graph_run_id,
                node_run_id=payload.get("node_run_id"),
                node_id=failed_node_id or None,
                reason=str(payload.get("reason") or failure_analysis.get("error") or "graph-level recovery requested"),
                failure_analysis=failure_analysis,
            )
            result["actions"].append({
                "module": "graph_runner",
                "command": "pause_for_replan",
                "status": pause.get("status"),
                "result": pause,
            })

        if not failed_node_id:
            result.update({
                "status": "paused_needs_failed_node",
                "pause": pause,
                "next_action": "provide failed_node_id before creating a replacement subgraph",
                "agent_context": self.target_context(project_id, graph_id),
                "snapshot": self.project_store.snapshot(),
            })
            return result

        replan = replan_subgraph(
            self.workspace_root,
            project_id,
            graph_id,
            failed_node_id,
            failure_analysis=failure_analysis,
            graph=graph,
            replacement_strategy=str(payload.get("replacement_strategy") or "repair_then_retry"),
            recovery_node_names=payload.get("recovery_node_names") if isinstance(payload.get("recovery_node_names"), list) else None,
            rewrite_downstream_dependencies=bool(payload.get("rewrite_downstream_dependencies", True)),
            save=apply_replan,
        )
        result["actions"].append({
            "module": "task_decompose",
            "command": "replan_subgraph",
            "status": replan.get("status"),
            "patch": replan.get("patch"),
        })
        if apply_replan:
            try:
                from ..graph_saver import save_workflow_version

                version = save_workflow_version(
                    self.project_store,
                    project_id,
                    graph_id,
                    note=f"graph-level recovery for failed node {failed_node_id}",
                    source="recovery",
                )
                result["actions"].append({
                    "module": "graph_saver",
                    "command": "save_workflow",
                    "status": "success",
                    "version": version.get("version"),
                })
            except Exception as exc:  # noqa: BLE001
                result["actions"].append({
                    "module": "graph_saver",
                    "command": "save_workflow",
                    "status": "failed",
                    "error": str(exc),
                })
        else:
            self.project_store.append_memory_event(
                project_id,
                graph_id,
                {"type": "graph", "name": graph_id},
                "system",
                (
                    "图级失败已生成候选恢复分支，尚未写回 workflow。\n"
                    f"- 失败节点：{failed_node_id}\n"
                    f"- 替代节点：{(replan.get('patch') or {}).get('replacement_node_id')}"
                ),
            )

        result.update({
            "status": "replanned" if apply_replan else "candidate_replan_ready",
            "pause": pause,
            "replan": replan,
            "next_action": "review candidate_graph and rerun from a checkpoint" if not apply_replan else "rerun graph from the latest checkpoint or current graph",
            "agent_context": self.target_context(
                project_id,
                graph_id,
                (replan.get("patch") or {}).get("replacement_node_id") or failed_node_id,
            ),
            "snapshot": self.project_store.snapshot(),
        })
        return result

    def _recover_graph_runner_failure(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        graph: dict[str, Any],
        error: Exception,
        *,
        scope: dict[str, str],
    ) -> dict[str, Any]:
        from ..graph_runner.main import classify_node_failure
        from ..graph_saver import save_workflow_version
        from .skills import recommend_next_modules

        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        error_text = str(error)
        failed_node_id = (
            scope.get("node_id")
            or getattr(error, "node_id", None)
            or str(record.get("node_id") or payload.get("node_id") or "")
            or _parse_failed_node_id(error_text)
        )
        plan = recommend_next_modules("graph_runner", event="run_failed", error=error_text)
        recovery: dict[str, Any] = {
            "status": "planned",
            "node_id": failed_node_id or None,
            "skill_plan": plan,
            "actions": [],
        }
        try:
            failure_analysis = classify_node_failure(
                self.workspace_root,
                getattr(error, "graph_run_id", None),
                node_id=failed_node_id or None,
                error=error_text,
                graph=graph,
            )
        except Exception as exc:  # noqa: BLE001
            failure_analysis = {
                "schema": "graphyagent.failure_analysis.v1",
                "status": "classification_failed",
                "node_id": failed_node_id or None,
                "failure_scope": "node_local",
                "error": error_text,
                "classification_error": str(exc),
                "created_at": utc_now(),
            }
        recovery["failure_analysis"] = failure_analysis
        if failure_analysis.get("failure_scope") in {"graph_level", "plan_level"} or payload.get("force_graph_replan"):
            graph_recovery = self._recover_graph_failure_command(
                record,
                {
                    **payload,
                    "graph": graph,
                    "graph_run_id": getattr(error, "graph_run_id", None),
                    "failed_node_id": failed_node_id,
                    "error": error_text,
                    "failure_analysis": failure_analysis,
                    "apply": bool(payload.get("apply_graph_recovery")),
                    "force_replan": True,
                },
            )
            recovery["actions"].append({
                "module": "agent_runtime",
                "command": "recover_graph_failure",
                "status": graph_recovery.get("status"),
                "result": graph_recovery,
            })
            recovery["status"] = str(graph_recovery.get("status") or "paused_for_replan")
            return recovery
        self.project_store.append_memory_event(
            project_id,
            graph_id,
            {"type": "node" if failed_node_id else "graph", "name": failed_node_id or graph_id},
            "system",
            (
                "graph_runner 执行失败，已进入技能辅助恢复策略。\n"
                f"- 错误：{error_text}\n"
                f"- 推荐下一模块：{', '.join(plan.get('next_modules') or []) or '无'}"
            ),
        )

        if failed_node_id and "model_routing" in plan.get("next_modules", []):
            route_action = self._retry_failed_node_with_complex_model(
                record,
                payload,
                graph,
                failed_node_id,
                error_text,
                scope=scope,
            )
            recovery["actions"].append(route_action)
            if route_action.get("status") == "success":
                recovery["status"] = "retry_success"
                return recovery

        if failed_node_id and "task_decompose" in plan.get("next_modules", []):
            try:
                decompose = self.project_store.decompose_node(project_id, graph_id, failed_node_id)
                recovery["actions"].append({
                    "module": "task_decompose",
                    "command": "decompose_node",
                    "status": "success",
                    "result": decompose,
                })
                save_workflow_version(
                    self.project_store,
                    project_id,
                    graph_id,
                    note=f"graph_runner failed and task_decompose recovered node {failed_node_id}: {error_text}",
                    source="recovery",
                )
                recovery["status"] = "decomposed"
            except Exception as exc:  # noqa: BLE001
                recovery["actions"].append({
                    "module": "task_decompose",
                    "command": "decompose_node",
                    "status": "failed",
                    "error": str(exc),
                })
                recovery["status"] = "failed"
        return recovery

    def _retry_failed_node_with_complex_model(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        graph: dict[str, Any],
        node_id: str,
        error_text: str,
        *,
        scope: dict[str, str],
    ) -> dict[str, Any]:
        from ..core.types import GraphState
        from ..graph_saver import save_workflow_version
        from ..model_routing.routing import route_model

        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        recovery_graph = deepcopy(graph)
        target = next((node for node in recovery_graph.get("nodes", []) if str(node.get("id")) == node_id), None)
        if not target:
            return {
                "module": "model_routing",
                "command": "route_node",
                "status": "skipped",
                "reason": f"node not found: {node_id}",
            }
        target.setdefault("routing", {})["complexity"] = "complex"
        target.setdefault("metadata", {}).setdefault("recovery", []).append({
            "source": "graph_runner_failure",
            "error": error_text,
            "strategy": "complex_model_retry",
            "created_at": utc_now(),
        })
        executor = target.setdefault("executor", {})
        if str(executor.get("type") or "").lower() == "llm":
            executor["profile"] = "complex"
            executor["fallback_complex"] = False
        config = GraphConfig.from_dict(recovery_graph)
        node_spec = next(node for node in config.nodes if node.node_id == node_id)
        route = route_model(config, node_spec, GraphState(context=config.context, experiment=config.experiment))
        save_workflow_version(
            self.project_store,
            project_id,
            graph_id,
            graph=recovery_graph,
            note=f"complex model retry for failed node {node_id}: {error_text}",
            source="recovery",
        )
        try:
            retry_graph = graph_for_node(recovery_graph, node_id) if scope.get("type") == "node" else recovery_graph
            run = run_graph(GraphConfig.from_dict(retry_graph), self.workspace_root)
            self.project_store.record_graph_run(
                project_id,
                graph_id,
                run,
                command_record={**record, "recovery": "complex_model_retry"},
                scope=scope,
            )
            return {
                "module": "model_routing",
                "command": "route_node",
                "status": "success",
                "route": route.to_dict(),
                "retry_run": run,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "module": "model_routing",
                "command": "route_node",
                "status": "failed",
                "route": route.to_dict(),
                "error": str(exc),
            }

    def _chat_graph(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        from .tool_loop import run_chat_graph_tool_loop

        project_id = _required_project_id(record, payload)
        graph_id = _optional_graph_id(record, payload, self.project_store)
        prompt = str(payload.get("prompt") or "")
        return run_chat_graph_tool_loop(
            self,
            record,
            payload,
            project_id=project_id,
            graph_id=graph_id,
            prompt=prompt,
        )

    def _write_memory(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _optional_graph_id(record, payload, self.project_store)
        target = _memory_target(record, payload, project_id, graph_id)
        _require_graph_for_non_project(target, graph_id)
        self.project_store.append_memory_event(
            project_id,
            graph_id or "",
            target,
            str(payload.get("role") or "user"),
            str(payload.get("text") or payload.get("content") or ""),
        )
        return {
            "target": target,
            "agent_context": self.target_context(project_id, graph_id, record.get("node_id")),
            "snapshot": self.project_store.snapshot(),
        }

    def _read_memory(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _optional_graph_id(record, payload, self.project_store)
        target = _memory_target(record, payload, project_id, graph_id)
        _require_graph_for_non_project(target, graph_id)
        memory = self.project_store.read_memory(project_id, graph_id or "", target)
        return {
            "target": target,
            "memory": memory,
            "agent_context": self.target_context(project_id, graph_id, record.get("node_id")),
        }

    def _audit_node_necessity(self, record: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record)
        graph_id = _required_graph_id(record)
        node_id = str(record.get("node_id") or "")
        result = self.project_store.audit_node_necessity(project_id, graph_id, node_id)
        result["agent_context"] = self.target_context(project_id, graph_id, node_id)
        return result

    def _decompose_node(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = _required_graph_id(record, payload)
        node_id = str(record.get("node_id") or "")
        child_names = payload.get("child_names") if isinstance(payload.get("child_names"), list) else None
        result = self.project_store.decompose_node(project_id, graph_id, node_id, child_names)
        result["agent_context"] = self.target_context(project_id, graph_id)
        return result

    def _import_file(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = payload.get("graph_id") or record.get("graph_id") or _current_graph_id(self.project_store)
        node_id = payload.get("node_id") or record.get("node_id")
        scope = str(payload.get("scope") or PROJECT_UNCLASSIFIED)
        file_record = self.project_store.import_file(
            project_id=project_id,
            scope=scope,
            graph_id=graph_id,
            node_id=node_id,
            path=payload.get("path"),
            name=payload.get("name"),
            content_base64=payload.get("contentBase64") or payload.get("content_base64"),
        )
        return {
            "file": file_record,
            "agent_context": self.target_context(project_id, graph_id, node_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _move_file(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        graph_id = payload.get("graph_id") or record.get("graph_id") or _current_graph_id(self.project_store)
        node_id = payload.get("node_id") or record.get("node_id")
        result = self.project_store.move_file(
            project_id=project_id,
            file_id=str(payload.get("file_id") or ""),
            target_scope=str(payload.get("target_scope") or payload.get("scope") or PROJECT_UNCLASSIFIED),
            graph_id=graph_id,
            node_id=node_id,
        )
        return {
            "result": result,
            "agent_context": self.target_context(project_id, graph_id, node_id),
            "snapshot": self.project_store.snapshot(),
        }

    def _delete_file(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_project_id(record, payload)
        result = self.project_store.delete_file(
            project_id=project_id,
            file_id=str(payload.get("file_id") or ""),
        )
        graph_id = record.get("graph_id") or _current_graph_id(self.project_store)
        return {
            "result": result,
            "agent_context": self.target_context(project_id, graph_id, record.get("node_id")),
            "snapshot": self.project_store.snapshot(),
        }

    def _audit_dataset(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        from ..data_audit import audit_dataset, write_audit_outputs

        dataset = payload.get("dataset") or payload.get("path")
        if not dataset:
            raise ValueError("audit_dataset requires payload.dataset")
        report = audit_dataset(dataset, metadata_path=payload.get("metadata"))
        result: dict[str, Any] = {"report": report}
        if payload.get("output_dir"):
            result["paths"] = write_audit_outputs(report, payload["output_dir"])
        return result

    def _list_subagent_types(self, record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        from .subagents import load_agent_definitions

        definitions = load_agent_definitions(self.workspace_root)
        agents = [
            {
                "name": item.name,
                "description": item.description,
                "model": item.model,
                "tools": item.tools,
                "source": item.source,
            }
            for item in definitions.values()
        ]
        agents.sort(key=lambda item: item["name"])
        return {
            "subagents": agents,
            "agent_context": self.target_context(
                record.get("project_id"),
                record.get("graph_id"),
                record.get("node_id"),
            ),
        }


def graph_for_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    by_id = {str(node.get("id")): node for node in graph.get("nodes", [])}
    if node_id not in by_id:
        raise FileNotFoundError(f"node not found: {node_id}")
    keep: set[str] = set()

    def visit(current_id: str) -> None:
        if current_id in keep:
            return
        keep.add(current_id)
        for dep in by_id[current_id].get("depends_on") or []:
            if str(dep) in by_id:
                visit(str(dep))

    visit(node_id)
    node_graph = deepcopy(graph)
    node_graph["graph_id"] = f"{graph.get('graph_id')}_{node_id}"
    node_graph["nodes"] = [node for node in node_graph.get("nodes", []) if str(node.get("id")) in keep]
    node_graph["output_nodes"] = [node_id]
    node_graph.setdefault("metadata", {}).setdefault("graphyagent", {})["command_scope"] = {
        "type": "node",
        "node_id": node_id,
    }
    return node_graph


def _recovery_task_text(
    graph: dict[str, Any],
    payload: dict[str, Any],
    record: dict[str, Any],
) -> str:
    explicit = str(payload.get("task") or payload.get("prompt") or "").strip()
    if explicit:
        return explicit
    node_id = str(payload.get("failed_node_id") or payload.get("node_id") or record.get("node_id") or "")
    if node_id:
        node = next((item for item in graph.get("nodes", []) if str(item.get("id")) == node_id), None)
        if node:
            metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
            description = metadata.get("description") or (node.get("executor") or {}).get("prompt") or ""
            return (
                f"节点：{node.get('id')}\n"
                f"任务类型：{node.get('task_type')}\n"
                f"任务说明：{description}\n"
                f"输入：{json.dumps(node.get('inputs') or {}, ensure_ascii=False)}\n"
                f"输出：{json.dumps(node.get('output_roles') or {}, ensure_ascii=False)}"
            )
    if graph:
        return json.dumps(_chat_router_context({"graph": _graph_context(graph), "project": {}, "node": None}), ensure_ascii=False, indent=2)
    raise ValueError("task_decompose recovery requires payload.task or payload.prompt")


def _safe_path_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value))
    return cleaned.strip("._") or "graph"


def _workspace_output_dir(workspace_root: Path, output_dir: Any) -> Path:
    candidate = Path(str(output_dir)).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(workspace_root)
        return candidate
    except ValueError:
        return workspace_root / "reports" / candidate.name


def _chat_router_context(context: dict[str, Any]) -> dict[str, Any]:
    graph = context.get("graph") or {}
    node = context.get("node") or {}
    project = context.get("project") or {}
    return {
        "project": {
            "project_id": project.get("project_id"),
            "name": project.get("name"),
        },
        "graph": {
            "graph_id": graph.get("graph_id"),
            "name": graph.get("name"),
            "node_count": graph.get("node_count"),
            "output_nodes": graph.get("output_nodes"),
        },
        "node": {
            "node_id": node.get("node_id"),
            "task_type": node.get("task_type"),
            "task_description": node.get("task_description"),
        } if node else None,
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        import re

        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response did not contain a JSON object")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("response JSON must be an object")
    return data


def _project_context(project: dict[str, Any] | None) -> dict[str, Any] | None:
    if not project:
        return None
    return {
        "project_id": project.get("project_id"),
        "name": project.get("name"),
        "current_graph_id": project.get("current_graph_id"),
        "graph_count": len(project.get("graphs", [])),
        "project_file_count": len(project.get("files", {}).get(PROJECT_UNCLASSIFIED, [])),
    }


def _graph_context(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not graph:
        return None
    meta = graph.get("metadata", {}).get("graphyagent", {})
    files = meta.get("files") or {}
    node_files = files.get("nodes") or {}
    return {
        "graph_id": graph.get("graph_id"),
        "name": meta.get("name") or graph.get("graph_id"),
        "node_count": len(graph.get("nodes", [])),
        "output_nodes": graph.get("output_nodes") or [],
        "latest_run": meta.get("latest_run"),
        "graph_file_count": len(files.get("unclassified", [])),
        "node_file_count": sum(len(items) for items in node_files.values()),
        "last_node_outputs": meta.get("last_node_outputs", {}),
    }


def _node_context(graph: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    node_id = str(node.get("id") or "")
    meta = node.get("metadata") or {}
    files = (
        graph.get("metadata", {})
        .get("graphyagent", {})
        .get("files", {})
        .get("nodes", {})
        .get(node_id, [])
    )
    return {
        "node_id": node_id,
        "task_type": node.get("task_type"),
        "task_description": meta.get("description"),
        "depends_on": node.get("depends_on") or [],
        "inputs": node.get("inputs") or {},
        "output_roles": node.get("output_roles") or {},
        "file_count": len(files),
        "files": [
            {
                "file_id": item.get("file_id"),
                "name": item.get("name"),
                "audit": (item.get("analysis") or {}).get("audit"),
            }
            for item in files
        ],
        "latest_run": meta.get("latest_run"),
        "latest_outputs": meta.get("latest_outputs", []),
    }


def _required_project_id(record: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    project_id = str(payload.get("project_id") or record.get("project_id") or "")
    if not project_id:
        raise ValueError("project_id is required")
    return project_id


def _required_graph_id(record: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    graph_id = str(payload.get("graph_id") or record.get("graph_id") or "")
    if not graph_id:
        raise ValueError("graph_id is required")
    return graph_id


def _optional_graph_id(
    record: dict[str, Any],
    payload: dict[str, Any],
    project_store: ProjectStore,
) -> str | None:
    return payload.get("graph_id") or record.get("graph_id") or _current_graph_id(project_store)


def _current_graph_id(project_store: ProjectStore) -> str | None:
    project = project_store.get_current_project()
    return project.get("current_graph_id") if project else None


def _memory_target(
    record: dict[str, Any],
    payload: dict[str, Any],
    project_id: str,
    graph_id: str | None,
) -> dict[str, str]:
    explicit = payload.get("target")
    if isinstance(explicit, dict) and explicit.get("type"):
        return {str(key): str(value) for key, value in explicit.items() if value is not None}
    if record.get("node_id") or payload.get("node_id"):
        node_id = str(payload.get("node_id") or record.get("node_id"))
        return {"type": "node", "id": node_id, "name": node_id}
    if graph_id:
        return {"type": "graph", "id": str(graph_id), "name": str(graph_id)}
    return {"type": "project", "id": project_id, "name": project_id}


def _require_graph_for_non_project(target: dict[str, str], graph_id: str | None) -> None:
    if target.get("type") != "project" and not graph_id:
        raise ValueError("graph_id is required for graph/node/file memory")


def _list_graph_run_files(workspace_root: Path, graph_run_id: str, folder: str) -> list[dict[str, Any]]:
    root = workspace_root / "graphs" / graph_run_id / folder
    if not root.exists():
        return []
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        stat = path.stat()
        files.append({
            "name": path.name,
            "relative_path": path.relative_to(root).as_posix(),
            "path": str(path),
            "size": stat.st_size,
            "updated_at": stat.st_mtime,
        })
    return files


def _parse_failed_node_id(error_text: str) -> str:
    marker = "node "
    if marker not in error_text:
        return ""
    tail = error_text.split(marker, 1)[1]
    node_id = tail.split(" failed", 1)[0].strip()
    return node_id if node_id and " " not in node_id else ""


def _module_skill_summaries() -> list[dict[str, Any]]:
    from .skills import list_module_skills

    return [
        {
            "module": item["module"],
            "summary": item["summary"],
            "recommended_next_modules": item["recommended_next_modules"],
            "path": item["path"],
        }
        for item in list_module_skills()
    ]


def format_agent_tools_markdown(target_type: str | None = None) -> str:
    tools = [
        item
        for item in AGENT_TOOL_SPECS
        if not target_type or target_type in item.get("target_types", [])
    ]
    lines = ["# GraphyAgent Agent Tools", ""]
    for tool in tools:
        targets = ", ".join(tool.get("target_types", []))
        payload = json.dumps(tool.get("payload") or {}, ensure_ascii=False)
        lines.append(f"- `{tool['name']}` [{targets}] - {tool['description']}")
        lines.append(f"  payload: `{payload}`")
    return "\n".join(lines)
