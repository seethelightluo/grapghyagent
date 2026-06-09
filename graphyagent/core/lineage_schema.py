"""Execution lineage schemas for checkpoint verification and replay."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .types import utc_now


@dataclass
class ExecutionLineageRecord:
    graph_run_id: str
    node_run_id: str
    node_id: str
    input_fingerprint: str
    input_artifacts: list[dict[str, Any]] = field(default_factory=list)
    output_artifacts: list[dict[str, Any]] = field(default_factory=list)
    executor_signature: str = ""
    context_packet_hash: str | None = None
    preflight_verdict: dict[str, Any] = field(default_factory=dict)
    postflight_verdict: dict[str, Any] = field(default_factory=dict)
    checkpoint_id: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "graphyagent.execution_lineage_record.v1",
            "graph_run_id": self.graph_run_id,
            "node_run_id": self.node_run_id,
            "node_id": self.node_id,
            "input_fingerprint": self.input_fingerprint,
            "input_artifacts": deepcopy(self.input_artifacts),
            "output_artifacts": deepcopy(self.output_artifacts),
            "executor_signature": self.executor_signature,
            "context_packet_hash": self.context_packet_hash,
            "preflight_verdict": deepcopy(self.preflight_verdict),
            "postflight_verdict": deepcopy(self.postflight_verdict),
            "checkpoint_id": self.checkpoint_id,
            "created_at": self.created_at,
        }


@dataclass
class CheckpointManifest:
    checkpoint_id: str
    graph_run_id: str
    node_id: str
    graph_config_sha256: str | None = None
    valid_node_ids: list[str] = field(default_factory=list)
    dirty_node_ids: list[str] = field(default_factory=list)
    state_path: str = ""
    lineage_path: str = ""
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "graphyagent.checkpoint_manifest.v1",
            "checkpoint_id": self.checkpoint_id,
            "graph_run_id": self.graph_run_id,
            "node_id": self.node_id,
            "graph_config_sha256": self.graph_config_sha256,
            "valid_node_ids": list(self.valid_node_ids),
            "dirty_node_ids": list(self.dirty_node_ids),
            "state_path": self.state_path,
            "lineage_path": self.lineage_path,
            "created_at": self.created_at,
        }


__all__ = ["CheckpointManifest", "ExecutionLineageRecord"]
