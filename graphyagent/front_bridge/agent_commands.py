"""Persistent graph/node agent command queue.

The Web UI and external clients should submit commands here instead of calling
runtime internals directly. A foreground request can process a command
immediately, while a CLI worker can keep draining the same queue later.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from ..agent_runtime.agents import GraphyAgentAgentRuntime
from ..core.types import utc_now


class AgentCommandStore:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.commands_root = self.workspace_root / "agent_commands"
        self.commands_root.mkdir(parents=True, exist_ok=True)

    def submit_command(
        self,
        *,
        project_id: str | None,
        graph_id: str | None,
        node_id: str | None = None,
        target_type: str = "graph",
        command: str = "run_graph",
        module: str | None = None,
        payload: dict[str, Any] | None = None,
        origin: str = "api",
    ) -> dict[str, Any]:
        now = utc_now()
        command_id = f"cmd-{uuid.uuid4().hex[:16]}"
        record = {
            "command_id": command_id,
            "status": "queued",
            "origin": origin,
            "target_type": target_type,
            "project_id": project_id,
            "graph_id": graph_id,
            "node_id": node_id,
            "module": module,
            "command": command,
            "payload": payload or {},
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "ended_at": None,
            "result": None,
            "error": None,
        }
        self._write(record)
        return record

    def list_commands(self, limit: int = 50) -> list[dict[str, Any]]:
        records = [self._read(path) for path in self._paths()]
        records.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return records[:limit]

    def read_command(self, command_id: str) -> dict[str, Any]:
        path = self._path(command_id)
        if not path.exists():
            raise FileNotFoundError(f"agent command not found: {command_id}")
        return self._read(path)

    def process_next(self, project_store: Any) -> dict[str, Any] | None:
        queued = [
            record
            for record in (self._read(path) for path in self._paths())
            if record.get("status") == "queued"
        ]
        queued.sort(key=lambda item: item.get("created_at") or "")
        if not queued:
            return None
        return self.process_command(project_store, queued[0]["command_id"])

    def process_until_idle(self, project_store: Any, limit: int = 20) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        for _ in range(max(1, limit)):
            record = self.process_next(project_store)
            if not record:
                break
            processed.append(record)
        return processed

    def process_command(self, project_store: Any, command_id: str) -> dict[str, Any]:
        record = self.read_command(command_id)
        if record.get("status") not in {"queued", "failed"}:
            return record
        record["status"] = "running"
        record["started_at"] = utc_now()
        record["updated_at"] = record["started_at"]
        record["error"] = None
        self._write(record)
        try:
            result = self._execute(project_store, record)
        except Exception as exc:  # noqa: BLE001
            record["status"] = "failed"
            record["error"] = str(exc)
        else:
            record["status"] = "success"
            record["result"] = result
        record["ended_at"] = utc_now()
        record["updated_at"] = record["ended_at"]
        self._write(record)
        return record

    def _execute(self, project_store: Any, record: dict[str, Any]) -> dict[str, Any]:
        runtime = GraphyAgentAgentRuntime(self.workspace_root, project_store)
        return runtime.execute_command(record)

    def _paths(self) -> list[Path]:
        return sorted(self.commands_root.glob("cmd-*.json"))

    def _path(self, command_id: str) -> Path:
        return self.commands_root / f"{_clean_command_id(command_id)}.json"

    def _read(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict[str, Any]) -> None:
        self._path(str(record["command_id"])).write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _clean_command_id(command_id: str) -> str:
    value = str(command_id).strip()
    if not value.startswith("cmd-"):
        raise ValueError(f"invalid command id: {command_id}")
    return "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
