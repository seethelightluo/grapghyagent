"""Content-addressed artifact storage and symlink views."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..core.types import Artifact, GraphState, utc_now


class ArtifactStore:
    """Local content-addressed artifact store.

    Layout:
        <workspace>/artifacts/files/<sha-prefix>/<sha256>
        <workspace>/graphs/<graph_run_id>/...
    """

    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.artifacts_root = self.workspace_root / "artifacts"
        self.files_root = self.artifacts_root / "files"
        self.index_path = self.artifacts_root / "index.json"
        self.graphs_root = self.workspace_root / "graphs"
        self.files_root.mkdir(parents=True, exist_ok=True)
        self.graphs_root.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index({"artifacts": {}})

    def graph_run_dir(self, graph_run_id: str) -> Path:
        path = self.graphs_root / graph_run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def hash_file(self, path: str | Path) -> str:
        h = hashlib.sha256()
        with Path(path).open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def artifact_path(self, artifact_id: str) -> Path:
        return self.files_root / artifact_id[:2] / artifact_id

    def register_file(
        self,
        path: str | Path,
        artifact_type: str = "other",
        metadata: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> Artifact:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"artifact source is not a file: {source}")

        artifact_id = self.hash_file(source)
        dest = self.artifact_path(artifact_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(str(source), str(dest))

        stat = source.stat()
        merged_metadata = {
            "size": stat.st_size,
            "sha256": artifact_id,
            "source_path": str(source),
            "original_name": source.name,
        }
        if metadata:
            merged_metadata.update(metadata)
        artifact = Artifact(
            artifact_id=artifact_id,
            uri=str(dest),
            type=artifact_type,
            metadata=merged_metadata,
            name=name or source.name,
        )
        self._record_artifact(artifact, source_path=source)
        return artifact

    def list_artifacts(
        self,
        *,
        limit: int = 200,
        artifact_type: str | None = None,
    ) -> list[dict[str, Any]]:
        records = list(self._read_index().get("artifacts", {}).values())
        if artifact_type:
            records = [
                record
                for record in records
                if record.get("type") == artifact_type
                or artifact_type in record.get("types", [])
            ]
        records.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return records[: max(1, limit)]

    def describe_artifact(self, artifact_id: str) -> dict[str, Any]:
        clean_id = _clean_artifact_id(artifact_id)
        index = self._read_index()
        record = index.get("artifacts", {}).get(clean_id)
        if record:
            return record
        path = self.artifact_path(clean_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact not found: {artifact_id}")
        stat = path.stat()
        return {
            "artifact_id": clean_id,
            "uri": str(path),
            "path": str(path),
            "type": "unknown",
            "types": [],
            "name": path.name,
            "names": [path.name],
            "metadata": {"size": stat.st_size, "sha256": clean_id},
            "source_paths": [],
            "size": stat.st_size,
            "sha256": clean_id,
            "created_at": None,
            "updated_at": None,
        }

    def link_artifact(self, artifact: Artifact, link_path: str | Path) -> None:
        target = Path(artifact.uri)
        link = Path(link_path)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            if link.is_dir() and not link.is_symlink():
                shutil.rmtree(link)
            else:
                link.unlink()
        try:
            os.symlink(str(target), str(link))
        except OSError:
            shutil.copy2(str(target), str(link))

    def materialize_inputs(
        self,
        run_dir: Path,
        bindings: dict[str, str],
        state: GraphState,
    ) -> dict[str, dict[str, Any]]:
        input_dir = run_dir / "inputs"
        input_dir.mkdir(parents=True, exist_ok=True)
        snapshot: dict[str, dict[str, Any]] = {}
        for friendly_name, artifact_id in bindings.items():
            artifact = state.artifacts[artifact_id]
            self.link_artifact(artifact, input_dir / friendly_name)
            snapshot[friendly_name] = artifact.to_dict()
        return snapshot

    def register_outputs(
        self,
        run_dir: Path,
        output_roles: dict[str, str] | None = None,
    ) -> dict[str, Artifact]:
        output_dir = run_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        roles = output_roles or {}
        artifacts: dict[str, Artifact] = {}

        for output_path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
            rel = output_path.relative_to(output_dir).as_posix()
            role = roles.get(rel, roles.get(output_path.name, "other"))
            artifact = self.register_file(output_path, artifact_type=role, name=rel)
            artifacts[rel] = artifact

        for rel, artifact in artifacts.items():
            self.link_artifact(artifact, output_dir / rel)

        return artifacts

    def link_graph_outputs(
        self,
        graph_run_dir: Path,
        state: GraphState,
        output_nodes: list[str],
    ) -> Path:
        output_dir = graph_run_dir / "graphoutput"
        output_dir.mkdir(parents=True, exist_ok=True)
        selected_nodes = output_nodes or [
            node_id
            for node_id, result in state.node_results.items()
            if result.status == "success"
        ]
        used_names: set[str] = set()

        for node_id in selected_nodes:
            result = state.node_results.get(node_id)
            if not result or result.status != "success":
                continue
            for rel, artifact_id in result.outputs.items():
                artifact = state.artifacts[artifact_id]
                target_rel = rel
                if target_rel in used_names:
                    target_rel = f"{node_id}/{rel}"
                used_names.add(target_rel)
                self.link_artifact(artifact, output_dir / target_rel)
        return output_dir

    def _record_artifact(self, artifact: Artifact, *, source_path: Path) -> None:
        index = self._read_index()
        artifacts = index.setdefault("artifacts", {})
        now = utc_now()
        existing = artifacts.get(artifact.artifact_id) or {}
        source_paths = _ordered_unique([
            *(existing.get("source_paths") or []),
            str(source_path),
        ])
        names = _ordered_unique([
            *(existing.get("names") or []),
            artifact.name or source_path.name,
        ])
        types = _ordered_unique([
            *(existing.get("types") or []),
            artifact.type,
        ])
        metadata = dict(existing.get("metadata") or {})
        metadata.update(artifact.metadata)
        artifacts[artifact.artifact_id] = {
            "artifact_id": artifact.artifact_id,
            "uri": artifact.uri,
            "path": artifact.uri,
            "type": artifact.type,
            "types": types,
            "name": artifact.name or source_path.name,
            "names": names,
            "metadata": metadata,
            "source_paths": source_paths,
            "size": metadata.get("size"),
            "sha256": artifact.artifact_id,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
        }
        self._write_index(index)

    def _read_index(self) -> dict[str, Any]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"artifacts": {}}
        if not isinstance(data, dict):
            return {"artifacts": {}}
        data.setdefault("artifacts", {})
        return data

    def _write_index(self, data: dict[str, Any]) -> None:
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean_artifact_id(artifact_id: str) -> str:
    value = "".join(ch for ch in str(artifact_id).strip() if ch.isalnum())
    if len(value) < 2:
        raise ValueError(f"invalid artifact id: {artifact_id}")
    return value


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
