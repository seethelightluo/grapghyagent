"""Serializable data types for the GraphyAgent runtime."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Artifact:
    artifact_id: str
    uri: str
    type: str = "other"
    metadata: dict[str, Any] = field(default_factory=dict)
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "uri": self.uri,
            "type": self.type,
            "metadata": deepcopy(self.metadata),
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Artifact":
        return cls(
            artifact_id=str(data["artifact_id"]),
            uri=str(data["uri"]),
            type=str(data.get("type", "other")),
            metadata=dict(data.get("metadata") or {}),
            name=data.get("name"),
        )


@dataclass
class ModelSpec:
    model_id: str
    capabilities: list[str] = field(default_factory=list)
    tier: str = "standard"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str) -> "ModelSpec":
        if isinstance(data, str):
            return cls(model_id=data)
        model_id = data.get("model_id") or data.get("id") or data.get("name")
        if not model_id:
            raise ValueError("model config is missing required field: model_id")
        capabilities = data.get("capabilities") or data.get("tags") or []
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        return cls(
            model_id=str(model_id),
            capabilities=[str(item) for item in capabilities],
            tier=str(data.get("tier", "standard")),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "capabilities": list(self.capabilities),
            "tier": self.tier,
            "metadata": deepcopy(self.metadata),
        }


@dataclass
class ProviderSpec:
    provider_id: str
    models: list[ModelSpec] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderSpec":
        provider_id = data.get("provider_id") or data.get("id") or data.get("name")
        if not provider_id:
            raise ValueError("provider config is missing required field: provider_id")
        raw_models = data.get("models") or []
        if isinstance(raw_models, dict):
            raw_models = [
                {"model_id": model_id, **(spec if isinstance(spec, dict) else {})}
                for model_id, spec in raw_models.items()
            ]
        return cls(
            provider_id=str(provider_id),
            models=[ModelSpec.from_dict(model) for model in raw_models],
            config=dict(data.get("config") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "models": [model.to_dict() for model in self.models],
            "config": deepcopy(self.config),
            "metadata": deepcopy(self.metadata),
        }


@dataclass
class RouterConfig:
    strategy: str = "simple_vs_complex"
    default_model_ref: str | None = None
    cost_preference: str = "balanced"
    max_tier: str | None = None
    routes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RouterConfig":
        if not data:
            return cls()
        return cls(
            strategy=str(data.get("strategy") or data.get("default_strategy") or "simple_vs_complex"),
            default_model_ref=data.get("default_model_ref") or data.get("model_ref"),
            cost_preference=str(data.get("cost_preference", "balanced")),
            max_tier=data.get("max_tier"),
            routes=dict(data.get("routes") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "default_model_ref": self.default_model_ref,
            "cost_preference": self.cost_preference,
            "max_tier": self.max_tier,
            "routes": deepcopy(self.routes),
            "metadata": deepcopy(self.metadata),
        }


@dataclass
class RouteDecision:
    provider_id: str | None = None
    model_id: str | None = None
    model_ref: str | None = None
    routing_reason: str = "unrouted"
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "model_ref": self.model_ref,
            "routing_reason": self.routing_reason,
            "parameters": deepcopy(self.parameters),
        }


@dataclass
class NodeSpec:
    node_id: str
    executor: dict[str, Any]
    depends_on: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    output_roles: dict[str, str] = field(default_factory=dict)
    interface: dict[str, Any] = field(default_factory=dict)
    input_spec: Any = None
    output_spec: Any = None
    input_example: Any = None
    output_example: Any = None
    verification_rule: str | None = None
    gate_condition: str | None = None
    gate: dict[str, Any] = field(default_factory=dict)
    evidence_pointers: list[Any] = field(default_factory=list)
    model_ref: str | None = None
    task_type: str | None = None
    routing: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeSpec":
        node_id = data.get("id") or data.get("node_id")
        if not node_id:
            raise ValueError("node is missing required field: id")
        executor = data.get("executor") or {}
        if not isinstance(executor, dict):
            raise ValueError(f"node {node_id}: executor must be an object")
        depends_on = data.get("depends_on", data.get("dependencies", []))
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        interface = data.get("interface") or {}
        if not isinstance(interface, dict):
            interface = {}
        gate = data.get("gate") or {}
        if not isinstance(gate, dict):
            gate = {"status": str(gate)}
        evidence_pointers = data.get("evidence_pointers", [])
        if isinstance(evidence_pointers, (str, dict)):
            evidence_pointers = [evidence_pointers]
        return cls(
            node_id=str(node_id),
            executor=executor,
            depends_on=[str(dep) for dep in depends_on],
            inputs=dict(data.get("inputs") or {}),
            output_roles=dict(data.get("output_roles") or data.get("outputs") or {}),
            interface=interface,
            input_spec=data.get("input_spec"),
            output_spec=data.get("output_spec"),
            input_example=data.get("input_example"),
            output_example=data.get("output_example"),
            verification_rule=data.get("verification_rule"),
            gate_condition=data.get("gate_condition"),
            gate=gate,
            evidence_pointers=list(evidence_pointers),
            model_ref=data.get("model_ref") or executor.get("model_ref"),
            task_type=data.get("task_type") or data.get("type"),
            routing=dict(data.get("routing") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.node_id,
            "executor": self.executor,
            "depends_on": self.depends_on,
            "inputs": deepcopy(self.inputs),
            "output_roles": dict(self.output_roles),
            "model_ref": self.model_ref,
            "task_type": self.task_type,
            "routing": deepcopy(self.routing),
            "metadata": deepcopy(self.metadata),
        }
        if self.interface:
            data["interface"] = deepcopy(self.interface)
        if self.input_spec is not None:
            data["input_spec"] = deepcopy(self.input_spec)
        if self.output_spec is not None:
            data["output_spec"] = deepcopy(self.output_spec)
        if self.input_example is not None:
            data["input_example"] = deepcopy(self.input_example)
        if self.output_example is not None:
            data["output_example"] = deepcopy(self.output_example)
        if self.verification_rule:
            data["verification_rule"] = self.verification_rule
        if self.gate_condition:
            data["gate_condition"] = self.gate_condition
        if self.gate:
            data["gate"] = deepcopy(self.gate)
        if self.evidence_pointers:
            data["evidence_pointers"] = deepcopy(self.evidence_pointers)
        return data


@dataclass
class GraphConfig:
    graph_id: str
    nodes: list[NodeSpec]
    output_nodes: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    experiment: dict[str, Any] = field(default_factory=dict)
    initial_artifacts: dict[str, Any] = field(default_factory=dict)
    providers: list[ProviderSpec] = field(default_factory=list)
    router: RouterConfig = field(default_factory=RouterConfig)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphConfig":
        graph_id = data.get("graph_id") or data.get("id") or data.get("name")
        if not graph_id:
            raise ValueError("graph config is missing required field: graph_id")
        raw_nodes = data.get("nodes") or []
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError("graph config must contain a non-empty nodes list")
        output_nodes = data.get("output_nodes", data.get("graph_outputs", []))
        if isinstance(output_nodes, str):
            output_nodes = [output_nodes]
        return cls(
            graph_id=str(graph_id),
            nodes=[NodeSpec.from_dict(node) for node in raw_nodes],
            output_nodes=[str(node_id) for node_id in output_nodes],
            context=dict(data.get("context") or {}),
            experiment=dict(data.get("experiment") or {}),
            initial_artifacts=dict(data.get("initial_artifacts") or {}),
            providers=[
                ProviderSpec.from_dict(provider)
                for provider in (data.get("providers") or [])
            ],
            router=RouterConfig.from_dict(data.get("router")),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "output_nodes": list(self.output_nodes),
            "context": deepcopy(self.context),
            "experiment": deepcopy(self.experiment),
            "initial_artifacts": deepcopy(self.initial_artifacts),
            "providers": [provider.to_dict() for provider in self.providers],
            "router": self.router.to_dict(),
            "metadata": deepcopy(self.metadata),
        }


@dataclass
class NodeResult:
    status: str
    outputs: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    node_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "outputs": dict(self.outputs),
            "summary": deepcopy(self.summary),
            "error": self.error,
            "node_run_id": self.node_run_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeResult":
        return cls(
            status=str(data.get("status", "unknown")),
            outputs=dict(data.get("outputs") or {}),
            summary=dict(data.get("summary") or {}),
            error=data.get("error"),
            node_run_id=data.get("node_run_id"),
        )


@dataclass
class GraphState:
    context: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    experiment: dict[str, Any] = field(default_factory=dict)
    artifact_aliases: dict[str, str] = field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context": deepcopy(self.context),
            "artifacts": {
                artifact_id: artifact.to_dict()
                for artifact_id, artifact in self.artifacts.items()
            },
            "node_results": {
                node_id: result.to_dict()
                for node_id, result in self.node_results.items()
            },
            "experiment": deepcopy(self.experiment),
            "artifact_aliases": dict(self.artifact_aliases),
            "checkpoints": deepcopy(self.checkpoints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphState":
        return cls(
            context=dict(data.get("context") or {}),
            artifacts={
                artifact_id: Artifact.from_dict(artifact)
                for artifact_id, artifact in (data.get("artifacts") or {}).items()
            },
            node_results={
                node_id: NodeResult.from_dict(result)
                for node_id, result in (data.get("node_results") or {}).items()
            },
            experiment=dict(data.get("experiment") or {}),
            artifact_aliases=dict(data.get("artifact_aliases") or {}),
            checkpoints=list(data.get("checkpoints") or []),
        )


@dataclass
class NodeRun:
    node_run_id: str
    node_id: str
    graph_run_id: str
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    ended_at: str | None = None
    duration_ms: int | None = None
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    output_snapshot: dict[str, Any] = field(default_factory=dict)
    call: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_run_id": self.node_run_id,
            "node_id": self.node_id,
            "graph_run_id": self.graph_run_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "input_snapshot": deepcopy(self.input_snapshot),
            "output_snapshot": deepcopy(self.output_snapshot),
            "call": deepcopy(self.call),
            "error": self.error,
        }


@dataclass
class GraphRun:
    graph_run_id: str
    graph_id: str
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    ended_at: str | None = None
    node_runs: list[str] = field(default_factory=list)
    graph_config: dict[str, Any] = field(default_factory=dict)
    experiment: dict[str, Any] = field(default_factory=dict)
    config_sha256: str | None = None
    graph_config_path: str | None = None
    initial_state: dict[str, Any] = field(default_factory=dict)
    final_state: dict[str, Any] = field(default_factory=dict)
    output_dir: str | None = None
    run_dir: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_run_id": self.graph_run_id,
            "graph_id": self.graph_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "node_runs": list(self.node_runs),
            "graph_config": deepcopy(self.graph_config),
            "experiment": deepcopy(self.experiment),
            "config_sha256": self.config_sha256,
            "graph_config_path": self.graph_config_path,
            "initial_state": deepcopy(self.initial_state),
            "final_state": deepcopy(self.final_state),
            "output_dir": self.output_dir,
            "run_dir": self.run_dir,
            "error": self.error,
        }
