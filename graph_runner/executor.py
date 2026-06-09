"""Graph executor for the GraphyAgent runtime."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import uuid
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..core.types import GraphConfig, GraphRun, GraphState, NodeResult, NodeRun, NodeSpec, utc_now
from ..core.lineage_schema import CheckpointManifest
from ..data_manager.artifacts import ArtifactStore
from ..agent_runtime.common_tools import read_file_content
from ..agent_runtime.context_budget import default_input_char_limit, resolve_max_tokens
from ..execution_lineage import plan_replay_from_checkpoint, record_node_lineage, verify_node_inputs
from ..model_routing.llm_client import LLMCallError, chat_completion
from ..model_routing.routing import classify_node_complexity, route_model
from ..model_routing.settings import load_env_file
from ..knowledge_graph import refresh_from_run
from ..node_memory import prepare_node_context, summarize_context_for_model
from ..node_audit.contract import (
    format_contract_failure,
    validate_node_contract,
    validate_node_outputs,
)
from ..reflection import apply_feedback_updates, run_online_reflection
from ..task.store import check_gate_conditions


class GraphExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        node_id: str | None = None,
        run_dir: str | Path | None = None,
        graph_run_id: str | None = None,
    ):
        super().__init__(message)
        self.node_id = node_id
        self.run_dir = str(run_dir) if run_dir else None
        self.graph_run_id = graph_run_id


class GraphExecutor:
    def __init__(self, workspace_root: str | Path = ".graphyagent"):
        load_env_file()
        self.store = ArtifactStore(workspace_root)
        self._state_lock = threading.Lock()
        self._trace_lock = threading.Lock()

    def run_graph(
        self,
        config: GraphConfig,
        *,
        initial_state: GraphState | dict[str, Any] | None = None,
        skip_completed: bool = False,
        resume_source: dict[str, Any] | None = None,
        reuse_policy: str = "strict_fingerprint",
    ) -> GraphRun:
        graph_run_id = f"{config.graph_id}-{uuid.uuid4().hex[:12]}"
        graph_run_dir = self.store.graph_run_dir(graph_run_id)
        (graph_run_dir / "traces").mkdir(parents=True, exist_ok=True)
        (graph_run_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        config_snapshot = _sanitize_graph_config_snapshot(config.to_dict())
        config_text = json.dumps(config_snapshot, indent=2, ensure_ascii=False, sort_keys=True)
        config_sha256 = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
        config_path = graph_run_dir / "graph_config.json"
        config_path.write_text(config_text, encoding="utf-8")

        if initial_state is None:
            state = GraphState(
                context=dict(config.context),
                experiment=dict(config.experiment),
            )
            self._register_initial_artifacts(config, state)
        elif isinstance(initial_state, GraphState):
            state = GraphState.from_dict(initial_state.to_dict())
            self._register_missing_initial_artifacts(config, state, refresh_existing=True)
        else:
            state = GraphState.from_dict(initial_state)
            self._register_missing_initial_artifacts(config, state, refresh_existing=True)
        initial_state_snapshot = state.to_dict()
        replay_plan: dict[str, Any] | None = None
        if skip_completed and resume_source:
            checkpoint = resume_source.get("checkpoint") if isinstance(resume_source.get("checkpoint"), dict) else None
            source_run_id = resume_source.get("source_graph_run_id")
            if checkpoint and source_run_id:
                replay_plan = plan_replay_from_checkpoint(
                    workspace=self.store.workspace_root,
                    graph=config,
                    checkpoint=checkpoint,
                    current_state=state,
                    source_graph_run_id=str(source_run_id),
                    reuse_policy=reuse_policy,
                )
                initial_state_snapshot["lineage_replay_plan"] = replay_plan
        if resume_source:
            initial_state_snapshot["resume_source"] = dict(resume_source)
            (graph_run_dir / "resume_source.json").write_text(
                json.dumps(resume_source, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        graph_run = GraphRun(
            graph_run_id=graph_run_id,
            graph_id=config.graph_id,
            graph_config=config_snapshot,
            experiment=dict(config.experiment),
            config_sha256=config_sha256,
            graph_config_path=str(config_path),
            initial_state=initial_state_snapshot,
            run_dir=str(graph_run_dir),
        )

        try:
            completed_node_ids = (
                set(replay_plan.get("reusable_node_ids") or [])
                if replay_plan is not None
                else self._completed_node_ids(state) if skip_completed else set()
            )
            dirty_node_ids = set((replay_plan or {}).get("dirty_node_ids") or [])
            for layer in self._topological_layers(config):
                reused_layer = [
                    node for node in layer
                    if node.node_id in completed_node_ids
                ]
                for node in reused_layer:
                    node_run = self._reuse_node_from_state(
                        config,
                        node,
                        graph_run,
                        graph_run_dir,
                        state,
                        replay_plan,
                    )
                    graph_run.node_runs.append(node_run.node_run_id)
                    checkpoint = self._write_checkpoint(
                        graph_run_dir,
                        state,
                        node,
                        graph_run,
                        dirty_node_ids=dirty_node_ids,
                    )
                    record_node_lineage(
                        workspace=self.store.workspace_root,
                        graph_run_id=graph_run.graph_run_id,
                        node_run=node_run,
                        checkpoint_id=checkpoint["checkpoint_id"],
                    )
                runnable_layer = [
                    node for node in layer
                    if node.node_id not in completed_node_ids
                ]
                if not runnable_layer:
                    continue
                if len(runnable_layer) == 1:
                    layer_runs = [
                        (runnable_layer[0], self._run_node(config, runnable_layer[0], graph_run, graph_run_dir, state))
                    ]
                else:
                    layer_runs = self._run_parallel_layer(config, runnable_layer, graph_run, graph_run_dir, state)
                for node, node_run in layer_runs:
                    graph_run.node_runs.append(node_run.node_run_id)
                    checkpoint = self._write_checkpoint(
                        graph_run_dir,
                        state,
                        node,
                        graph_run,
                        dirty_node_ids=dirty_node_ids,
                    )
                    record_node_lineage(
                        workspace=self.store.workspace_root,
                        graph_run_id=graph_run.graph_run_id,
                        node_run=node_run,
                        checkpoint_id=checkpoint["checkpoint_id"],
                    )
            output_dir = self.store.link_graph_outputs(
                graph_run_dir, state, config.output_nodes
            )
            graph_run.output_dir = str(output_dir)
            graph_run.status = "success"
        except Exception as exc:
            graph_run.status = "failed"
            graph_run.error = str(exc)
            if isinstance(exc, GraphExecutionError):
                exc.graph_run_id = graph_run.graph_run_id
                if not exc.run_dir:
                    exc.run_dir = str(graph_run_dir)
            if not isinstance(exc, GraphExecutionError):
                graph_run.error = traceback.format_exc()
            raise
        finally:
            graph_run.ended_at = utc_now()
            graph_run.final_state = state.to_dict()
            self._append_jsonl(graph_run_dir / "traces" / "graph_runs.jsonl", graph_run.to_dict())
            (graph_run_dir / "graph_run.json").write_text(
                json.dumps(graph_run.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                refresh_from_run(
                    graph_run.graph_run_id,
                    workspace=self.store.workspace_root,
                    project_id=_project_id_for_config(config),
                )
            except Exception:
                pass

        return graph_run

    def _register_initial_artifacts(self, config: GraphConfig, state: GraphState) -> None:
        for alias, spec in config.initial_artifacts.items():
            self._register_initial_artifact(alias, spec, state)

    def _register_missing_initial_artifacts(
        self,
        config: GraphConfig,
        state: GraphState,
        *,
        refresh_existing: bool = False,
    ) -> None:
        for alias, spec in config.initial_artifacts.items():
            alias_key = str(alias)
            artifact_id = state.artifact_aliases.get(alias_key)
            if artifact_id and artifact_id in state.artifacts and not refresh_existing:
                continue
            self._register_initial_artifact(alias, spec, state)

    def _register_initial_artifact(self, alias: str, spec: Any, state: GraphState) -> None:
        if isinstance(spec, str):
            path = spec
            artifact_type = "other"
            metadata: dict[str, Any] = {}
        elif isinstance(spec, dict):
            path = spec.get("path")
            artifact_type = str(spec.get("type", "other"))
            metadata = dict(spec.get("metadata") or {})
        else:
            raise ValueError(f"initial artifact {alias}: expected path string or object")
        if not path:
            raise ValueError(f"initial artifact {alias}: missing path")
        artifact = self.store.register_file(
            path,
            artifact_type=artifact_type,
            metadata=metadata,
            name=alias,
        )
        state.artifacts[artifact.artifact_id] = artifact
        state.artifact_aliases[str(alias)] = artifact.artifact_id

    def _completed_node_ids(self, state: GraphState) -> set[str]:
        return {
            node_id
            for node_id, result in state.node_results.items()
            if result.status == "success"
        }

    def _topological_nodes(self, config: GraphConfig) -> list[NodeSpec]:
        return [node for layer in self._topological_layers(config) for node in layer]

    def _topological_layers(self, config: GraphConfig) -> list[list[NodeSpec]]:
        by_id = {node.node_id: node for node in config.nodes}
        if len(by_id) != len(config.nodes):
            raise ValueError("graph contains duplicate node ids")
        missing = {
            dep
            for node in config.nodes
            for dep in node.depends_on
            if dep not in by_id
        }
        if missing:
            raise ValueError(f"graph dependencies reference missing nodes: {sorted(missing)}")

        children: dict[str, list[str]] = {node.node_id: [] for node in config.nodes}
        indegree: dict[str, int] = {node.node_id: 0 for node in config.nodes}
        order = {node.node_id: index for index, node in enumerate(config.nodes)}
        for node in config.nodes:
            for dep in node.depends_on:
                children[dep].append(node.node_id)
                indegree[node.node_id] += 1

        layers: list[list[NodeSpec]] = []
        ready = [node.node_id for node in config.nodes if indegree[node.node_id] == 0]
        visited = 0
        while ready:
            ready.sort(key=lambda node_id: order[node_id])
            layer_ids = ready
            layers.append([by_id[node_id] for node_id in layer_ids])
            visited += len(layer_ids)
            next_ready: list[str] = []
            for node_id in layer_ids:
                for child_id in children[node_id]:
                    indegree[child_id] -= 1
                    if indegree[child_id] == 0:
                        next_ready.append(child_id)
            ready = next_ready
        if visited != len(config.nodes):
            cycle_nodes = sorted(node_id for node_id, value in indegree.items() if value > 0)
            raise ValueError(f"cycle detected in graph dependencies: {cycle_nodes}")
        return layers

    def _run_parallel_layer(
        self,
        config: GraphConfig,
        layer: list[NodeSpec],
        graph_run: GraphRun,
        graph_run_dir: Path,
        state: GraphState,
    ) -> list[tuple[NodeSpec, NodeRun]]:
        max_workers = self._max_parallel_nodes(config, len(layer))
        results: dict[str, NodeRun] = {}
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="graphyagent-node") as pool:
            future_to_node = {
                pool.submit(self._run_node, config, node, graph_run, graph_run_dir, state): node
                for node in layer
            }
            for future in as_completed(future_to_node):
                node = future_to_node[future]
                results[node.node_id] = future.result()
        return [(node, results[node.node_id]) for node in layer]

    def _max_parallel_nodes(self, config: GraphConfig, layer_size: int) -> int:
        graphyagent_meta = config.metadata.get("graphyagent") if isinstance(config.metadata, dict) else {}
        raw = None
        if isinstance(graphyagent_meta, dict):
            raw = graphyagent_meta.get("max_parallel_nodes")
        if raw is None:
            raw = config.metadata.get("max_parallel_nodes") if isinstance(config.metadata, dict) else None
        try:
            configured = int(raw) if raw is not None else layer_size
        except (TypeError, ValueError):
            configured = layer_size
        return max(1, min(layer_size, configured))

    def _reuse_node_from_state(
        self,
        config: GraphConfig,
        node: NodeSpec,
        graph_run: GraphRun,
        graph_run_dir: Path,
        state: GraphState,
        replay_plan: dict[str, Any] | None,
    ) -> NodeRun:
        node_run_id = f"{node.node_id}-reused-{uuid.uuid4().hex[:8]}"
        run_dir = graph_run_dir / "nodes" / node.node_id / "runs" / node_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with self._state_lock:
            result = state.node_results.get(node.node_id)
            if not result or result.status != "success":
                raise ValueError(f"cannot reuse node without successful checkpoint result: {node.node_id}")
            input_bindings = self._resolve_inputs(node, state)
            input_snapshot = self.store.materialize_inputs(run_dir, input_bindings, state)
            route_decision = route_model(config, node, state)
            lineage_preflight = verify_node_inputs(
                workspace=self.store.workspace_root,
                graph=config,
                node_id=node.node_id,
                state=state,
                graph_run_id=graph_run.graph_run_id,
                node_run_id=node_run_id,
                input_snapshot=input_snapshot,
                route_decision=route_decision.to_dict(),
            )
            if lineage_preflight.get("verdict") == "blocked":
                raise ValueError(f"lineage reuse blocked `{node.node_id}`: {lineage_preflight.get('reason')}")
            node_memory_packet = prepare_node_context(
                workspace=self.store.workspace_root,
                project_id=_project_id_for_config(config),
                graph_id=config.graph_id,
                node_id=node.node_id,
                graph=config.to_dict(),
                node=node,
                state=state,
                graph_run_id=graph_run.graph_run_id,
                node_run_id=node_run_id,
                run_dir=run_dir,
                input_snapshot=input_snapshot,
                lineage_context=lineage_preflight,
            )
            state.context.setdefault("node_memory_packets", {})[node.node_id] = node_memory_packet
            artifacts = {
                output_name: state.artifacts[artifact_id].to_dict()
                for output_name, artifact_id in result.outputs.items()
                if artifact_id in state.artifacts
            }
            node_run = NodeRun(
                node_run_id=node_run_id,
                node_id=node.node_id,
                graph_run_id=graph_run.graph_run_id,
                status="success",
                input_snapshot={
                    "inputs": input_snapshot,
                    "depends_on": {
                        dep: state.node_results[dep].to_dict()
                        for dep in node.depends_on
                        if dep in state.node_results
                    },
                    "experiment": state.experiment,
                    "context_keys": sorted(state.context.keys()),
                    "lineage_preflight": lineage_preflight,
                    "node_memory_packet": node_memory_packet,
                    "replay_plan": {
                        "source_graph_run_id": (replay_plan or {}).get("source_graph_run_id"),
                        "reuse_policy": (replay_plan or {}).get("reuse_policy"),
                    },
                },
                output_snapshot={
                    "artifacts": artifacts,
                    "result": {
                        "type": "reused",
                        "source_node_run_id": result.node_run_id,
                        "source_status": result.status,
                    },
                    "lineage_postflight": {
                        "schema": "graphyagent.lineage_postflight.v1",
                        "node_run_id": node_run_id,
                        "node_id": node.node_id,
                        "created_at": utc_now(),
                        "verdict": "valid",
                        "reason": "checkpoint result reused",
                        "output_count": len(artifacts),
                    },
                    "online_reflection": {
                        "schema": "graphyagent.online_reflection.v1",
                        "node_run_id": node_run_id,
                        "graph_run_id": graph_run.graph_run_id,
                        "node_id": node.node_id,
                        "created_at": utc_now(),
                        "status": "reused",
                        "reused_from_node_run_id": result.node_run_id,
                        "structure_mutation_allowed": False,
                    },
                },
                call={
                    "executor": node.executor,
                    "execution_mode": "reused",
                    "routing": route_decision.to_dict(),
                    "chosen_provider": route_decision.provider_id,
                    "chosen_model": route_decision.model_id,
                    "routing_reason": route_decision.routing_reason,
                },
            )
        node_run.ended_at = utc_now()
        node_run.duration_ms = int((time.monotonic() - started) * 1000)
        self._append_jsonl(graph_run_dir / "traces" / "node_runs.jsonl", node_run.to_dict())
        return node_run

    def _run_node(
        self,
        config: GraphConfig,
        node: NodeSpec,
        graph_run: GraphRun,
        graph_run_dir: Path,
        state: GraphState,
    ) -> NodeRun:
        node_run_id = f"{node.node_id}-{uuid.uuid4().hex[:12]}"
        run_dir = graph_run_dir / "nodes" / node.node_id / "runs" / node_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)

        node_run = NodeRun(
            node_run_id=node_run_id,
            node_id=node.node_id,
            graph_run_id=graph_run.graph_run_id,
            input_snapshot={},
            call={"executor": node.executor},
        )

        started = time.monotonic()
        try:
            with self._state_lock:
                contract = validate_node_contract(
                    config,
                    node.node_id,
                    state=state,
                    phase="pre_run",
                )
                if contract.get("runtime_blocking"):
                    raise ValueError(format_contract_failure(contract))
                gate_ok, gate_reason = check_gate_conditions(
                    node.node_id,
                    graph=config,
                    state=state,
                )
                if not gate_ok:
                    raise ValueError(f"node gate blocked `{node.node_id}`: {gate_reason}")
                input_bindings = self._resolve_inputs(node, state)
                input_snapshot = self.store.materialize_inputs(run_dir, input_bindings, state)
                route_decision = route_model(config, node, state)
                lineage_preflight = verify_node_inputs(
                    workspace=self.store.workspace_root,
                    graph=config,
                    node_id=node.node_id,
                    state=state,
                    graph_run_id=graph_run.graph_run_id,
                    node_run_id=node_run_id,
                    input_snapshot=input_snapshot,
                    route_decision=route_decision.to_dict(),
                )
                if lineage_preflight.get("verdict") == "blocked":
                    raise ValueError(f"lineage preflight blocked `{node.node_id}`: {lineage_preflight.get('reason')}")
                node_memory_packet = prepare_node_context(
                    workspace=self.store.workspace_root,
                    project_id=_project_id_for_config(config),
                    graph_id=config.graph_id,
                    node_id=node.node_id,
                    graph=config.to_dict(),
                    node=node,
                    state=state,
                    graph_run_id=graph_run.graph_run_id,
                    node_run_id=node_run_id,
                    run_dir=run_dir,
                    input_snapshot=input_snapshot,
                    lineage_context=lineage_preflight,
                )
                execution_state = GraphState.from_dict(state.to_dict())
                execution_state.context.setdefault("node_memory_packets", {})[node.node_id] = node_memory_packet
                node_run.input_snapshot = {
                    "inputs": input_snapshot,
                    "depends_on": {
                        dep: state.node_results[dep].to_dict()
                        for dep in node.depends_on
                        if dep in state.node_results
                    },
                    "experiment": state.experiment,
                    "context_keys": sorted(state.context.keys()),
                    "contract": contract,
                    "gate_check": {"can_execute": gate_ok, "reason": gate_reason},
                    "lineage_preflight": lineage_preflight,
                    "node_memory_packet": node_memory_packet,
                }
                node_run.call = {
                    "executor": node.executor,
                    "execution_mode": "executed",
                    "routing": route_decision.to_dict(),
                    "chosen_provider": route_decision.provider_id,
                    "chosen_model": route_decision.model_id,
                    "routing_reason": route_decision.routing_reason,
                }
            result = self._execute_node(
                config,
                node,
                run_dir,
                execution_state,
                graph_run,
                route_decision.to_dict(),
            )
            with self._state_lock:
                artifacts = self.store.register_outputs(run_dir, node.output_roles)
                output_contract = validate_node_outputs(node, set(artifacts))
                if not output_contract.get("runtime_blocking"):
                    for artifact in artifacts.values():
                        state.artifacts[artifact.artifact_id] = artifact
                    output_ids = {
                        rel: artifact.artifact_id
                        for rel, artifact in artifacts.items()
                    }
                    state.node_results[node.node_id] = NodeResult(
                        status="success",
                        outputs=output_ids,
                        summary={
                            "output_count": len(output_ids),
                            "run_dir": str(run_dir),
                            "gate_status": "open",
                        },
                        node_run_id=node_run.node_run_id,
                    )
            if output_contract.get("runtime_blocking"):
                raise ValueError(format_contract_failure(output_contract))
            node_run.status = "success"
            lineage_postflight = {
                "schema": "graphyagent.lineage_postflight.v1",
                "node_run_id": node_run.node_run_id,
                "node_id": node.node_id,
                "created_at": utc_now(),
                "verdict": "valid",
                "reason": "outputs verified",
                "output_count": len(artifacts),
            }
            node_run.output_snapshot = {
                "artifacts": {
                    rel: artifact.to_dict()
                    for rel, artifact in artifacts.items()
                },
                "result": result,
                "contract": output_contract,
                "lineage_postflight": lineage_postflight,
            }
            node_run.output_snapshot["online_reflection"] = run_online_reflection(
                node_run.node_run_id,
                workspace=self.store.workspace_root,
                graph_run_id=graph_run.graph_run_id,
                node_id=node.node_id,
                input_snapshot=node_run.input_snapshot,
                output_snapshot=node_run.output_snapshot,
                status=node_run.status,
                run_dir=run_dir,
            )
        except Exception as exc:
            node_run.status = "failed"
            node_run.error = str(exc)
            node_run.output_snapshot = {
                **(node_run.output_snapshot or {}),
                "lineage_postflight": {
                    "schema": "graphyagent.lineage_postflight.v1",
                    "node_run_id": node_run.node_run_id,
                    "node_id": node.node_id,
                    "created_at": utc_now(),
                    "verdict": "blocked",
                    "reason": str(exc),
                    "output_count": len(((node_run.output_snapshot or {}).get("artifacts") or {})),
                },
                "online_reflection": run_online_reflection(
                    node_run.node_run_id,
                    workspace=self.store.workspace_root,
                    graph_run_id=graph_run.graph_run_id,
                    node_id=node.node_id,
                    input_snapshot=node_run.input_snapshot,
                    output_snapshot=node_run.output_snapshot,
                    status="failed",
                    error=str(exc),
                    run_dir=run_dir,
                ),
            }
            with self._state_lock:
                state.node_results[node.node_id] = NodeResult(
                    status="failed",
                    error=str(exc),
                    summary={"run_dir": str(run_dir)},
                    node_run_id=node_run.node_run_id,
                )
            raise GraphExecutionError(
                f"node {node.node_id} failed: {exc}",
                node_id=node.node_id,
                run_dir=run_dir,
            ) from exc
        finally:
            node_run.ended_at = utc_now()
            node_run.duration_ms = int((time.monotonic() - started) * 1000)
            self._append_jsonl(graph_run_dir / "traces" / "node_runs.jsonl", node_run.to_dict())
            try:
                apply_feedback_updates(
                    node_run.node_run_id,
                    workspace=self.store.workspace_root,
                    graph_run_id=graph_run.graph_run_id,
                    project_id=_project_id_for_config(config),
                )
            except Exception:
                pass

        return node_run

    def _resolve_inputs(self, node: NodeSpec, state: GraphState) -> dict[str, str]:
        bindings: dict[str, str] = {}
        for friendly_name, reference in node.inputs.items():
            try:
                artifact_id = self._resolve_input_reference(reference, state)
            except ValueError:
                if _is_optional_node_input(node, str(friendly_name), reference):
                    continue
                raise
            bindings[str(friendly_name)] = artifact_id
        return bindings

    def _resolve_input_reference(self, reference: Any, state: GraphState) -> str:
        if isinstance(reference, dict):
            if "artifact" in reference:
                return self._resolve_input_reference(reference["artifact"], state)
            if "alias" in reference:
                return self._resolve_input_reference(reference["alias"], state)
            if "from" in reference:
                return self._resolve_input_reference(reference["from"], state)
            if "path" in reference:
                artifact = self.store.register_file(
                    reference["path"],
                    artifact_type=str(reference.get("type", "other")),
                    metadata=dict(reference.get("metadata") or {}),
                    name=reference.get("name"),
                )
                state.artifacts[artifact.artifact_id] = artifact
                return artifact.artifact_id
            raise ValueError(f"unsupported input reference object: {reference}")

        ref = str(reference)
        if ref.startswith("artifact:"):
            ref = ref.split(":", 1)[1]
        elif ref.startswith("alias:"):
            ref = ref.split(":", 1)[1]

        if ref in state.artifacts:
            return ref
        if ref in state.artifact_aliases:
            return state.artifact_aliases[ref]
        if ":" in ref:
            node_id, output_name = ref.split(":", 1)
            node_result = state.node_results.get(node_id)
            if not node_result:
                raise ValueError(f"input reference {ref}: node has not run")
            if output_name not in node_result.outputs:
                raise ValueError(f"input reference {ref}: output not found")
            return node_result.outputs[output_name]
        raise ValueError(f"cannot resolve input reference: {reference}")

    def _execute_node(
        self,
        config: GraphConfig,
        node: NodeSpec,
        run_dir: Path,
        state: GraphState,
        graph_run: GraphRun,
        route_decision: dict[str, Any],
    ) -> dict[str, Any]:
        executor = node.executor
        executor_type = str(executor.get("type", "shell")).lower()
        env = os.environ.copy()
        env.update({
            "GRAPHYAGENT_GRAPH_ID": config.graph_id,
            "GRAPHYAGENT_GRAPH_RUN_ID": graph_run.graph_run_id,
            "GRAPHYAGENT_NODE_ID": node.node_id,
            "GRAPHYAGENT_RUN_DIR": str(run_dir),
            "GRAPHYAGENT_INPUTS": str(run_dir / "inputs"),
            "GRAPHYAGENT_OUTPUTS": str(run_dir / "outputs"),
            "GRAPHYAGENT_STATE": json.dumps(state.to_dict(), ensure_ascii=False),
            "GRAPHYAGENT_PROVIDER": str(route_decision.get("provider_id") or ""),
            "GRAPHYAGENT_MODEL": str(route_decision.get("model_id") or ""),
            "GRAPHYAGENT_MODEL_REF": str(route_decision.get("model_ref") or ""),
            "GRAPHYAGENT_ROUTING_REASON": str(route_decision.get("routing_reason") or ""),
            "GRAPHYAGENT_ROUTING": json.dumps(route_decision, ensure_ascii=False),
        })
        package_root = Path(__file__).resolve().parents[1]
        env["PYTHONPATH"] = (
            str(package_root)
            + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        )

        if executor_type == "noop":
            for rel, content in (executor.get("write_outputs") or {}).items():
                output_path = run_dir / "outputs" / str(rel)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(content, (dict, list)):
                    output_path.write_text(
                        json.dumps(content, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                else:
                    output_path.write_text(str(content), encoding="utf-8")
            return {"type": "noop"}

        if executor_type == "audit":
            return self._execute_audit_node(node, run_dir)

        if executor_type == "llm":
            return self._execute_llm_node(config, node, run_dir, state, route_decision)

        if executor_type == "subgraph":
            return self._execute_subgraph_node(config, node, run_dir, state)

        if executor_type == "http":
            return self._execute_http_node(node, run_dir)

        if executor_type in {"sqlite", "db_query"}:
            return self._execute_sqlite_node(node, run_dir)

        if executor_type == "python":
            if "code" in executor:
                command: list[str] | str = [sys.executable, "-c", str(executor["code"])]
                shell = False
            elif "script" in executor:
                command = [sys.executable, str(executor["script"])]
                shell = False
            else:
                raise ValueError("python executor requires code or script")
        elif executor_type == "shell":
            command = executor.get("command")
            if not command:
                raise ValueError("shell executor requires command")
            shell = isinstance(command, str)
        else:
            raise ValueError(f"unsupported executor type: {executor_type}")

        stdout_path = run_dir / "logs" / "stdout.txt"
        stderr_path = run_dir / "logs" / "stderr.txt"
        with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(
                command,
                shell=shell,
                cwd=str(run_dir),
                env=env,
                stdout=stdout,
                stderr=stderr,
                text=True,
                timeout=executor.get("timeout_seconds"),
            )
        if completed.returncode != 0:
            stderr_preview = stderr_path.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(
                f"command exited with {completed.returncode}: {stderr_preview}"
            )
        return {
            "type": executor_type,
            "command": command,
            "exit_code": completed.returncode,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }

    def _execute_http_node(self, node: NodeSpec, run_dir: Path) -> dict[str, Any]:
        executor = node.executor
        url = str(executor.get("url") or "").strip()
        if not url:
            raise ValueError("http executor requires url")
        params = executor.get("params") if isinstance(executor.get("params"), dict) else None
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params, doseq=True)}"
        method = str(executor.get("method") or ("POST" if ("json" in executor or "body" in executor) else "GET")).upper()
        headers = {
            str(key): str(value)
            for key, value in (executor.get("headers") or {}).items()
            if value is not None
        }
        body: bytes | None = None
        if "json" in executor:
            body = json.dumps(executor["json"], ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif "body" in executor:
            raw_body = executor["body"]
            if isinstance(raw_body, (dict, list)):
                body = json.dumps(raw_body, ensure_ascii=False).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            else:
                body = str(raw_body).encode("utf-8")
        request = Request(url, data=body, headers=headers, method=method)
        timeout = float(executor.get("timeout_seconds") or 30)
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-authored local workflow URL.
            response_body = response.read()
            status = int(response.status)
            response_headers = dict(response.headers.items())
        text = response_body.decode(str(executor.get("encoding") or "utf-8"), errors="replace")
        parsed_json: Any = None
        try:
            parsed_json = json.loads(text)
        except json.JSONDecodeError:
            parsed_json = None
        output_name = str(executor.get("output") or "http_response.json")
        output_path = run_dir / "outputs" / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "graphyagent.http_response.v1",
            "node_id": node.node_id,
            "method": method,
            "url": url,
            "status_code": status,
            "headers": response_headers,
            "body": parsed_json if parsed_json is not None else text,
            "body_text": text,
        }
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "type": "http",
            "method": method,
            "url": url,
            "status_code": status,
            "output": output_name,
        }

    def _execute_sqlite_node(self, node: NodeSpec, run_dir: Path) -> dict[str, Any]:
        executor = node.executor
        query = str(executor.get("query") or "").strip()
        if not query:
            raise ValueError("sqlite executor requires query")
        read_only = bool(executor.get("read_only", True))
        if read_only and not _looks_like_readonly_sql(query):
            raise ValueError("sqlite executor read_only mode only allows SELECT, WITH, or PRAGMA queries")
        database_path = self._sqlite_database_path(executor, run_dir)
        parameters = executor.get("parameters") or executor.get("params") or []
        if not isinstance(parameters, (list, tuple, dict)):
            raise ValueError("sqlite executor parameters must be a list or object")
        if read_only:
            uri = f"file:{database_path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            cursor = connection.execute(query, parameters)
            rows = [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()
        output_name = str(executor.get("output") or "query_result.json")
        output_path = run_dir / "outputs" / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "graphyagent.sqlite_result.v1",
            "node_id": node.node_id,
            "database": str(database_path),
            "query": query,
            "row_count": len(rows),
            "rows": rows,
        }
        output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "type": "sqlite",
            "database": str(database_path),
            "row_count": len(rows),
            "output": output_name,
        }

    def _sqlite_database_path(self, executor: dict[str, Any], run_dir: Path) -> Path:
        configured = executor.get("database") or executor.get("database_path")
        if configured:
            return Path(str(configured)).expanduser().resolve()
        input_name = str(executor.get("database_input") or "database.sqlite")
        path = run_dir / "inputs" / input_name
        if not path.exists():
            raise FileNotFoundError(f"sqlite database input not found: {input_name}")
        return path

    def _execute_audit_node(self, node: NodeSpec, run_dir: Path) -> dict[str, Any]:
        from ..data_audit import audit_dataset, write_audit_outputs

        executor = node.executor
        inputs_dir = run_dir / "inputs"
        dataset_name = str(executor.get("dataset_input") or "dataset")
        metadata_name = str(executor.get("metadata_input") or "metadata")
        dataset_path = inputs_dir / dataset_name
        metadata_path = inputs_dir / metadata_name
        if not dataset_path.exists():
            configured = executor.get("dataset_path")
            dataset_path = Path(configured).expanduser().resolve() if configured else dataset_path
        if not dataset_path.exists():
            raise ValueError(f"audit dataset input not found: {dataset_name}")
        dataset_path = _path_with_inferred_suffix(dataset_path, run_dir)
        if metadata_path.exists():
            metadata_path = _path_with_inferred_suffix(metadata_path, run_dir)
        report = audit_dataset(
            dataset_path,
            metadata_path=metadata_path if metadata_path.exists() else executor.get("metadata_path"),
        )
        paths = write_audit_outputs(report, run_dir / "outputs")
        return {
            "type": "audit",
            "dataset": str(dataset_path),
            "verdict": report.get("verdict"),
            "evidence_count": report.get("dataset_metrics", {}).get("evidence_count"),
            "tag_summary": report.get("tag_summary", {}),
            "paths": paths,
        }

    def _execute_llm_node(
        self,
        config: GraphConfig,
        node: NodeSpec,
        run_dir: Path,
        state: GraphState,
        route_decision: dict[str, Any],
    ) -> dict[str, Any]:
        executor = node.executor
        output_name = str(executor.get("output") or "llm_result.md")
        profile = _llm_profile_for_node(node, state, route_decision)
        fallback_profiles = []
        if profile == "simple" and executor.get("fallback_complex", True):
            fallback_profiles.append("complex")
        prompt = self._build_llm_prompt(config, node, run_dir, state)
        route_parameters = route_decision.get("parameters") if isinstance(route_decision.get("parameters"), dict) else {}
        requested_max_tokens = executor.get("max_tokens") or route_parameters.get("max_tokens")
        if _is_generated_workflow_llm_node(node) and _small_token_value(requested_max_tokens):
            requested_max_tokens = None
        max_tokens = resolve_max_tokens(
            requested_max_tokens,
            profile=profile,
            model=str(route_decision.get("model_id") or route_decision.get("model_ref") or ""),
            prompt=prompt,
        )
        try:
            result = chat_completion(
                prompt,
                profile=profile,
                system=executor.get("system"),
                fallback_profiles=fallback_profiles,
                max_tokens=max_tokens,
                temperature=float(
                    executor.get("temperature")
                    if "temperature" in executor
                    else route_parameters.get("temperature", 0.2)
                ),
                timeout_seconds=executor.get("timeout_seconds"),
            )
        except LLMCallError:
            raise
        output_path = run_dir / "outputs" / output_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result["text"], encoding="utf-8")
        call_path = run_dir / "outputs" / "llm_call.json"
        call_path.write_text(
            json.dumps(
                {
                    "profile": result["profile"],
                    "api_format": result["api_format"],
                    "model": result["model"],
                    "base_url": result["base_url"],
                    "routing": route_decision,
                    "max_tokens": max_tokens,
                    "output": output_name,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {
            "type": "llm",
            "profile": result["profile"],
            "api_format": result["api_format"],
            "model": result["model"],
            "routing_reason": route_decision.get("routing_reason"),
            "output": output_name,
        }

    def _execute_subgraph_node(
        self,
        config: GraphConfig,
        node: NodeSpec,
        run_dir: Path,
        state: GraphState,
    ) -> dict[str, Any]:
        executor = node.executor
        graph_data = self._load_subgraph_data(executor)
        nested_graph_id = str(graph_data.get("graph_id") or graph_data.get("id") or node.node_id)
        graph_data["graph_id"] = f"{node.node_id}_{nested_graph_id}"
        graph_data["context"] = {
            **dict(state.context),
            **dict(graph_data.get("context") or {}),
            "parent_graph_id": config.graph_id,
            "parent_node_id": node.node_id,
        }
        graph_data["experiment"] = {
            **dict(state.experiment),
            **dict(graph_data.get("experiment") or {}),
        }
        graph_data["initial_artifacts"] = {
            **dict(graph_data.get("initial_artifacts") or {}),
            **self._subgraph_input_artifacts(run_dir, executor),
        }
        nested_workspace = run_dir / "subgraph_workspace"
        nested_run = GraphExecutor(nested_workspace).run_graph(GraphConfig.from_dict(graph_data))
        copied_outputs = self._copy_subgraph_outputs(nested_run, run_dir)
        summary_path = run_dir / "logs" / "subgraph_run.json"
        summary_path.write_text(
            json.dumps(nested_run.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {
            "type": "subgraph",
            "graph_run_id": nested_run.graph_run_id,
            "graph_id": nested_run.graph_id,
            "status": nested_run.status,
            "output_dir": nested_run.output_dir,
            "copied_outputs": copied_outputs,
            "summary": str(summary_path),
        }

    def _load_subgraph_data(self, executor: dict[str, Any]) -> dict[str, Any]:
        if isinstance(executor.get("graph"), dict):
            return deepcopy(executor["graph"])
        if executor.get("graph_path"):
            from ..core.config import load_graph_config

            return load_graph_config(str(executor["graph_path"])).to_dict()
        raise ValueError("subgraph executor requires graph or graph_path")

    def _subgraph_input_artifacts(self, run_dir: Path, executor: dict[str, Any]) -> dict[str, Any]:
        inputs_dir = run_dir / "inputs"
        input_map = executor.get("input_map") if isinstance(executor.get("input_map"), dict) else None
        artifacts: dict[str, Any] = {}
        if input_map:
            for alias, input_name in input_map.items():
                path = inputs_dir / str(input_name)
                if not path.exists():
                    raise FileNotFoundError(f"subgraph input not found: {input_name}")
                artifacts[str(alias)] = {"path": str(path), "type": "subgraph_input"}
            return artifacts
        for path in sorted(inputs_dir.iterdir() if inputs_dir.exists() else []):
            if path.is_file() or path.is_symlink():
                artifacts[path.name] = {"path": str(path), "type": "subgraph_input"}
        return artifacts

    def _copy_subgraph_outputs(self, nested_run: GraphRun, run_dir: Path) -> list[dict[str, Any]]:
        copied = []
        output_dir = run_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        nested_output_dir = Path(str(nested_run.output_dir or ""))
        if not nested_output_dir.exists():
            return copied
        for source in sorted(path for path in nested_output_dir.rglob("*") if path.is_file()):
            rel = source.relative_to(nested_output_dir).as_posix()
            target = output_dir / rel
            if target.exists():
                target = output_dir / str(nested_run.graph_id) / rel
                rel = target.relative_to(output_dir).as_posix()
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append({"relative_path": rel, "source": str(source), "path": str(target)})
        return copied

    def _build_llm_prompt(
        self,
        config: GraphConfig,
        node: NodeSpec,
        run_dir: Path,
        state: GraphState,
    ) -> str:
        executor = node.executor
        parts = [
            str(executor.get("prompt") or node.metadata.get("description") or node.node_id),
        ]
        input_dir = run_dir / "inputs"
        profile = str(executor.get("profile") or node.routing.get("complexity") or "")
        max_chars = int(executor.get("input_char_limit") or default_input_char_limit(profile))
        for path in sorted(input_dir.iterdir() if input_dir.exists() else []):
            if not path.is_file():
                continue
            try:
                content = read_file_content(path, max_chars=max_chars)
            except Exception as exc:  # noqa: BLE001
                content = f"读取输入文件失败：{exc}"
            parts.append(f"\n## 输入文件：{path.name}\n{content[:max_chars]}")
        for dep in node.depends_on:
            dep_result = state.node_results.get(dep)
            if not dep_result:
                continue
            for output_name, artifact_id in dep_result.outputs.items():
                artifact = state.artifacts.get(artifact_id)
                if not artifact:
                    continue
                output_path = Path(artifact.uri)
                if not output_path.is_file():
                    continue
                try:
                    content = read_file_content(output_path, max_chars=max_chars)
                except Exception as exc:  # noqa: BLE001
                    content = f"读取上游输出失败：{exc}"
                parts.append(
                    f"\n## 上游节点输出：{dep}/{output_name}\n{content[:max_chars]}"
                )
        if executor.get("include_state"):
            state_text = json.dumps(state.to_dict(), ensure_ascii=False)
            parts.append(f"\n## 图状态摘要\n{state_text[:max_chars]}")
        packet = (state.context.get("node_memory_packets") or {}).get(node.node_id)
        if isinstance(packet, dict):
            parts.append("\n" + summarize_context_for_model(packet))
        if executor.get("include_legacy_memory_context"):
            from ..memory.context import get_memory_context

            memory_query = "\n".join([
                node.node_id,
                str(node.task_type or ""),
                str(node.metadata.get("description") or ""),
                " ".join(node.depends_on),
                " ".join(config.output_nodes),
            ])
            memory_context = get_memory_context(
                workspace_root=self.store.workspace_root,
                graph=config.to_dict(),
                node_id=node.node_id,
                query=memory_query,
                max_results=int(executor.get("memory_context_limit") or 6),
                max_chars=int(executor.get("memory_context_chars") or 20000),
            )
            if memory_context:
                parts.append("\n" + memory_context)
        return "\n".join(parts)

    def _write_checkpoint(
        self,
        graph_run_dir: Path,
        state: GraphState,
        node: NodeSpec,
        graph_run: GraphRun,
        *,
        dirty_node_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        checkpoint_id = f"{len(state.checkpoints) + 1:04d}"
        checkpoint_path = graph_run_dir / "checkpoints" / f"{checkpoint_id}_{node.node_id}.json"
        lineage_path = graph_run_dir / "lineage" / "lineage_records.jsonl"
        manifest = CheckpointManifest(
            checkpoint_id=checkpoint_id,
            graph_run_id=graph_run.graph_run_id,
            node_id=node.node_id,
            graph_config_sha256=graph_run.config_sha256,
            valid_node_ids=sorted(
                node_id for node_id, result in state.node_results.items()
                if result.status == "success"
            ),
            dirty_node_ids=sorted(dirty_node_ids or []),
            state_path=str(checkpoint_path),
            lineage_path=str(lineage_path),
        ).to_dict()
        checkpoint = {
            "checkpoint_id": checkpoint_id,
            "graph_run_id": graph_run.graph_run_id,
            "node_id": node.node_id,
            "created_at": utc_now(),
            "state": state.to_dict(),
            "manifest": manifest,
        }
        state.checkpoints.append({
            "checkpoint_id": checkpoint_id,
            "node_id": node.node_id,
            "created_at": checkpoint["created_at"],
            "path": str(checkpoint_path),
            "manifest": manifest,
        })
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        manifest_path = graph_run_dir / "lineage" / "checkpoint_manifests.jsonl"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(manifest, ensure_ascii=False) + "\n")
        return manifest

    def _append_jsonl(self, path: Path, item: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._trace_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _path_with_inferred_suffix(path: Path, run_dir: Path) -> Path:
    if path.suffix:
        return path
    suffix = _infer_suffix(path)
    if not suffix:
        return path
    inferred = run_dir / "inputs" / f"{path.name}{suffix}"
    if not inferred.exists():
        shutil.copy2(path, inferred)
    return inferred


def _llm_profile_for_node(
    node: NodeSpec,
    state: GraphState,
    route_decision: dict[str, Any],
) -> str:
    explicit = node.executor.get("profile")
    if explicit:
        return str(explicit).lower()

    reason = str(route_decision.get("routing_reason") or "").lower()
    if "complex" in reason:
        return "complex"
    if "simple" in reason:
        return "simple"

    model_ref = str(route_decision.get("model_ref") or "")
    if model_ref:
        if model_ref == os.environ.get("GRAPHYAGENT_COMPLEX_MODEL_REF"):
            return "complex"
        if model_ref == os.environ.get("GRAPHYAGENT_SIMPLE_MODEL_REF"):
            return "simple"

    return classify_node_complexity(node, state)


def _project_id_for_config(config: GraphConfig) -> str:
    metadata = config.metadata.get("graphyagent") if isinstance(config.metadata, dict) else {}
    if isinstance(metadata, dict) and metadata.get("project_id"):
        return str(metadata["project_id"])
    if config.context.get("project_id"):
        return str(config.context["project_id"])
    return "runtime"


def _is_generated_workflow_llm_node(node: NodeSpec) -> bool:
    if str((node.executor or {}).get("type") or "").lower() != "llm":
        return False
    prompt = str((node.executor or {}).get("prompt") or "")
    return "GraphyAgent 工作流中的节点智能体" in prompt


def _small_token_value(value: Any) -> bool:
    try:
        return int(value) <= 1200
    except (TypeError, ValueError):
        return False


def _is_optional_node_input(node: NodeSpec, friendly_name: str, reference: Any) -> bool:
    executor = node.executor or {}
    if str(executor.get("type") or "").lower() != "audit":
        return False
    if bool(executor.get("metadata_required")):
        return False
    metadata_name = str(executor.get("metadata_input") or "metadata")
    reference_text = str(reference)
    return friendly_name == metadata_name or reference_text == metadata_name


def _infer_suffix(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    sample = text[:4096].lstrip()
    if not sample:
        return ""
    first_line = sample.splitlines()[0] if sample.splitlines() else sample
    if sample.startswith("["):
        return ".json"
    if sample.startswith("{"):
        try:
            json.loads(text)
            return ".json"
        except json.JSONDecodeError:
            return ".jsonl"
    if "," in first_line:
        return ".csv"
    return ""


def _looks_like_readonly_sql(query: str) -> bool:
    stripped = query.lstrip().lower()
    return stripped.startswith(("select", "with", "pragma"))


def _sanitize_graph_config_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    return _mask_secret_values(deepcopy(data))


def _mask_secret_values(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(str(key)):
                masked[key] = "***"
            else:
                masked[key] = _mask_secret_values(item)
        return masked
    if isinstance(value, list):
        return [_mask_secret_values(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(term in lowered for term in ("api_key", "apikey", "secret", "token", "password", "credential"))
