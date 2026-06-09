"""Local GraphyAgent project/graph canvas and API."""
from __future__ import annotations

import json
import mimetypes
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..agent_runtime.agents import GraphyAgentAgentRuntime
from ..agent_runtime.module_registry import list_module_commands, list_modules
from ..data_manager.project_store import PROJECT_UNCLASSIFIED, ProjectStore
from ..front_bridge.agent_commands import AgentCommandStore
from ..graph_runner.executor import GraphExecutionError
from ..model_routing.settings import load_env_file, read_settings
from .service import (
    inspect_graph_config,
    list_graph_runs,
    read_graph_run,
    read_node_runs,
)


def start_graphyagent_web_server(
    port: int = 8765,
    host: str = "127.0.0.1",
    workspace: str | Path = ".graphyagent",
    default_config: str | Path = "apps/windows/templates/blank.json",
) -> None:
    load_env_file()
    store = ProjectStore(workspace)
    store.bootstrap(default_config)
    handler = _make_handler(Path(workspace), str(default_config), store)
    server = ThreadingHTTPServer((host, port), handler)
    print("GraphyAgent project canvas")
    print(f"URL: http://{host}:{port}")
    print(f"Workspace: {Path(workspace).expanduser().resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGraphyAgent web canvas stopped.")
    finally:
        server.server_close()


def _make_handler(workspace: Path, default_config: str, store: ProjectStore):
    class GraphyAgentHandler(BaseHTTPRequestHandler):
        workspace_root = workspace
        default_config_path = default_config
        project_store = store
        command_store = AgentCommandStore(workspace)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT.value)
                self.end_headers()
                return
            if path in {"/", "/index.html"}:
                self._send_html(_build_html(self.default_config_path))
                return
            if path == "/api/health":
                self._send_json({
                    "ok": True,
                    "workspace": str(self.workspace_root.expanduser().resolve()),
                    "default_config": self.default_config_path,
                })
                return
            if path == "/api/workspace":
                self.project_store.bootstrap(self.default_config_path)
                self._send_json(self.project_store.snapshot())
                return
            if path in {"/api/settings", "/api/settings/api-keys"}:
                self._send_json(read_settings())
                return
            if path == "/api/graph":
                config_path = _first(query, "path")
                try:
                    if config_path:
                        self._send_json({
                            "config_path": config_path,
                            "graph": inspect_graph_config(config_path),
                        })
                    else:
                        snapshot = self.project_store.snapshot()
                        self._send_json({
                            "graph": snapshot.get("current_graph"),
                            "virtual_tree": snapshot.get("virtual_tree"),
                            "ai_suggestions": snapshot.get("ai_suggestions", []),
                        })
                except Exception as exc:  # noqa: BLE001
                    self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            if path == "/api/runs/active":
                active = _get_active_run(self.workspace_root)
                self._send_json({"active": active})
                return
            if path == "/api/runs":
                runs = list_graph_runs(self.workspace_root)
                active = _get_active_run(self.workspace_root)
                if active:
                    if not any(r.get("graph_run_id") == active.get("graph_run_id") for r in runs):
                        runs.insert(0, {
                            "graph_run_id": active["graph_run_id"],
                            "graph_id": active["graph_id"],
                            "status": "running",
                            "started_at": active["started_at"],
                            "ended_at": None,
                        })
                self._send_json({"runs": runs})
                return
            if path == "/api/agent/commands":
                limit = int(_first(query, "limit") or "50")
                self._send_json({"commands": self.command_store.list_commands(limit=limit)})
                return
            if path == "/api/agent/tools":
                target = _first(query, "target")
                runtime = GraphyAgentAgentRuntime(self.workspace_root, self.project_store)
                from ..agent_runtime.tool_registry import get_tool_schemas

                self._send_json({
                    "tools": runtime.list_tools(target),
                    "common_tools": get_tool_schemas(target),
                })
                return
            if path == "/api/agent/modules":
                module = _first(query, "module")
                target = _first(query, "target")
                self._send_json({
                    "modules": list_modules(),
                    "commands": list_module_commands(module, target),
                })
                return
            if path == "/api/files/open":
                file_path = _first(query, "path")
                if not file_path:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
                    return
                self._send_local_file(file_path)
                return
            if path.startswith("/api/runs/"):
                graph_run_id = unquote(path.rsplit("/", 1)[-1])
                try:
                    active = _get_active_run_by_id(self.workspace_root, graph_run_id)
                    if active:
                        self._send_json({
                            "run": active,
                            "node_runs": active.get("node_runs_detailed", []),
                        })
                        return
                    self._send_json({
                        "run": read_graph_run(self.workspace_root, graph_run_id),
                        "node_runs": read_node_runs(self.workspace_root, graph_run_id),
                    })
                except FileNotFoundError as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/agent/commands":
                    self._handle_agent_command()
                elif path == "/api/agent/process":
                    self._handle_agent_process()
                elif path == "/api/run":
                    self._handle_run()
                elif path == "/api/projects/create":
                    body = self._read_json()
                    record = self._submit_and_maybe_process(
                        project_id=None,
                        graph_id=None,
                        node_id=None,
                        target_type="project",
                        module="data_manager",
                        command="create_project",
                        payload={"name": str(body.get("name") or "新项目")},
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/projects/select":
                    body = self._read_json()
                    record = self._submit_and_maybe_process(
                        project_id=str(body.get("project_id") or ""),
                        graph_id=None,
                        node_id=None,
                        target_type="project",
                        module="data_manager",
                        command="select_project",
                        payload={},
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/projects/delete":
                    body = self._read_json()
                    record = self._submit_and_maybe_process(
                        project_id=str(body.get("project_id") or ""),
                        graph_id=None,
                        node_id=None,
                        target_type="project",
                        module="data_manager",
                        command="delete_project",
                        payload={},
                        process=body.get("process", True),
                    )
                    if not self.project_store.list_projects():
                        self.project_store.bootstrap(self.default_config_path)
                    self._send_compat_command_response(record)
                elif path == "/api/graphs/create":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    payload: dict[str, Any] = {"name": str(body.get("name") or "新图")}
                    if isinstance(body.get("graph"), dict):
                        payload["graph"] = body["graph"]
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=None,
                        node_id=None,
                        target_type="project",
                        module="data_manager",
                        command="create_graph",
                        payload=payload,
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/graphs/select":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=str(body.get("graph_id") or ""),
                        node_id=None,
                        target_type="graph",
                        module="data_manager",
                        command="select_graph",
                        payload={},
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/graphs/delete":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=str(body.get("graph_id") or ""),
                        node_id=None,
                        target_type="graph",
                        module="data_manager",
                        command="delete_graph",
                        payload={},
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/graphs/save":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    graph_id = _graph_id(body, self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=graph_id,
                        node_id=None,
                        target_type="graph",
                        module="data_manager",
                        command="save_graph",
                        payload={"graph": body.get("graph") or {}},
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/graphs/open-folder":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    graph_id = _graph_id(body, self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=graph_id,
                        node_id=None,
                        target_type="graph",
                        module="data_manager",
                        command="graph_folder_info",
                        payload={},
                        process=body.get("process", True),
                    )
                    if record.get("status") == "failed":
                        self._send_error_json(
                            HTTPStatus.BAD_REQUEST,
                            str(record.get("error") or "graph folder command failed"),
                        )
                        return
                    result = record.get("result") if isinstance(record.get("result"), dict) else {}
                    folder_path = str(result.get("folder_path") or "")
                    open_result = _open_local_folder(folder_path, self.workspace_root)
                    self._send_json({
                        "command": record,
                        "opened": open_result["opened"],
                        "folder_path": open_result["folder_path"],
                        "graph_json_path": result.get("graph_json_path"),
                        "memory_path": result.get("memory_path"),
                        "files_path": result.get("files_path"),
                        "snapshot": self.project_store.snapshot(),
                    })
                elif path == "/api/files/import":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    graph_id = body.get("graph_id") or _optional_graph_id(self.project_store)
                    node_id = str(body.get("node_id")) if body.get("node_id") else None
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=str(graph_id) if graph_id else None,
                        node_id=node_id,
                        target_type="node" if node_id else "graph" if graph_id else "project",
                        module="data_manager",
                        command="import_file",
                        payload={
                            "scope": str(body.get("scope") or PROJECT_UNCLASSIFIED),
                            "path": body.get("path"),
                            "name": body.get("name"),
                            "contentBase64": body.get("contentBase64") or body.get("content_base64"),
                        },
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/files/move":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    graph_id = body.get("graph_id") or _optional_graph_id(self.project_store)
                    node_id = str(body.get("node_id")) if body.get("node_id") else None
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=str(graph_id) if graph_id else None,
                        node_id=node_id,
                        target_type="node" if node_id else "graph" if graph_id else "project",
                        module="data_manager",
                        command="move_file",
                        payload={
                            "file_id": str(body.get("file_id") or ""),
                            "target_scope": str(body.get("target_scope") or body.get("scope") or PROJECT_UNCLASSIFIED),
                        },
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/files/delete":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=body.get("graph_id") or _optional_graph_id(self.project_store),
                        node_id=str(body.get("node_id")) if body.get("node_id") else None,
                        target_type=str(body.get("target_type") or "file"),
                        module="data_manager",
                        command="delete_file",
                        payload={"file_id": str(body.get("file_id") or "")},
                        process=body.get("process", True),
                    )
                    self._send_compat_command_response(record)
                elif path == "/api/nodes/decompose":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    graph_id = _graph_id(body, self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=graph_id,
                        node_id=str(body.get("node_id") or ""),
                        target_type="node",
                        module="task_decompose",
                        command="decompose_node",
                        payload={
                            "child_names": body.get("child_names")
                            if isinstance(body.get("child_names"), list)
                            else None
                        },
                        process=body.get("process", True),
                    )
                    self._send_json({"command": record, "snapshot": self.project_store.snapshot()})
                elif path == "/api/chat-graph":
                    body = self._read_json()
                    project_id = _project_id(body, self.project_store)
                    target_type = str(body.get("target_type") or "graph")
                    graph_id = body.get("graph_id")
                    if graph_id is None and target_type in {"graph", "node", "file"}:
                        graph_id = _optional_graph_id(self.project_store)
                    record = self._submit_and_maybe_process(
                        project_id=project_id,
                        graph_id=str(graph_id) if graph_id else None,
                        node_id=str(body.get("node_id")) if body.get("node_id") else None,
                        target_type=target_type,
                        module="agent_runtime",
                        command="chat_graph",
                        payload={"prompt": str(body.get("prompt") or "")},
                        process=body.get("process", True),
                    )
                    self._send_json({"command": record, "snapshot": self.project_store.snapshot()})
                elif path in {"/api/settings", "/api/settings/api-keys"}:
                    body = self._read_json()
                    record = self._submit_and_maybe_process(
                        project_id=_optional_project_id(body, self.project_store),
                        graph_id=None,
                        node_id=None,
                        target_type="settings",
                        module="model_routing",
                        command="update_settings",
                        payload=body,
                        process=body.get("process", True),
                    )
                    if record.get("status") == "failed":
                        self._send_error_json(
                            HTTPStatus.BAD_REQUEST,
                            str(record.get("error") or "settings update failed"),
                        )
                        return
                    result = record.get("result") if isinstance(record.get("result"), dict) else {}
                    settings = result.get("settings") if isinstance(result, dict) else None
                    if isinstance(settings, dict):
                        payload = dict(settings)
                        payload["command"] = record
                        self._send_json(payload)
                    else:
                        self._send_json({"command": record, "snapshot": self.project_store.snapshot()})
                else:
                    self._send_error_json(HTTPStatus.NOT_FOUND, "not found")
            except FileNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except ValueError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except GraphExecutionError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def _handle_run(self) -> None:
            body = self._read_json()
            project_id = _optional_project_id(body, self.project_store)
            graph_id = body.get("graph_id") or _optional_graph_id(self.project_store)
            payload: dict[str, Any] = {}
            if isinstance(body.get("graph"), dict):
                payload["graph"] = body["graph"]
            elif body.get("config_path"):
                payload["config_path"] = body.get("config_path")
            record = self._submit_and_maybe_process(
                project_id=project_id,
                graph_id=str(graph_id) if graph_id else None,
                node_id=None,
                target_type="graph",
                module="graph_runner",
                command="run_graph",
                payload=payload,
                process=body.get("process", True),
            )
            self._send_json({"command": record, "snapshot": self.project_store.snapshot()})

        def _handle_agent_command(self) -> None:
            body = self._read_json()
            project_id = _optional_project_id(body, self.project_store)
            command = str(body.get("command") or "run_graph")
            module = str(body.get("module") or "").strip() or None
            payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
            target_type = str(body.get("target_type") or ("node" if body.get("node_id") else "graph"))
            graph_id = body.get("graph_id")
            if graph_id is None and target_type in {"graph", "node", "file", "run"}:
                graph_id = _optional_graph_id(self.project_store)
            record = self._submit_and_maybe_process(
                project_id=project_id,
                graph_id=str(graph_id) if graph_id else None,
                node_id=str(body.get("node_id")) if body.get("node_id") else None,
                target_type=target_type,
                module=module,
                command=command,
                payload=payload,
                process=body.get("process", True),
            )
            self._send_json({"command": record, "snapshot": self.project_store.snapshot()})

        def _submit_and_maybe_process(
            self,
            *,
            project_id: str | None,
            graph_id: str | None,
            node_id: str | None,
            target_type: str,
            module: str | None,
            command: str,
            payload: dict[str, Any],
            process: bool,
        ) -> dict[str, Any]:
            record = self.command_store.submit_command(
                project_id=project_id,
                graph_id=graph_id,
                node_id=node_id,
                target_type=target_type,
                command=command,
                module=module,
                payload=payload,
                origin="web",
            )
            if process:
                record = self.command_store.process_command(self.project_store, record["command_id"])
            return record

        def _send_compat_command_response(self, record: dict[str, Any]) -> None:
            if record.get("status") == "failed":
                self._send_error_json(
                    HTTPStatus.BAD_REQUEST,
                    str(record.get("error") or "agent command failed"),
                )
                return
            payload: dict[str, Any] = {
                "command": record,
                "snapshot": self.project_store.snapshot(),
            }
            result = record.get("result")
            if isinstance(result, dict):
                payload.update(result)
            self._send_json(payload)

        def _handle_agent_process(self) -> None:
            body = self._read_json()
            limit = int(body.get("limit") or 20)
            if body.get("command_id"):
                record = self.command_store.process_command(self.project_store, str(body["command_id"]))
                self._send_json({"command": record, "snapshot": self.project_store.snapshot()})
                return
            processed = self.command_store.process_until_idle(self.project_store, limit=limit)
            self._send_json({"commands": processed, "snapshot": self.project_store.snapshot()})

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _send_json(self, obj: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"error": message}, status)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_local_file(self, file_path: str) -> None:
            path = Path(file_path).expanduser().resolve()
            try:
                path.relative_to(self.workspace_root.expanduser().resolve())
            except ValueError:
                self._send_error_json(HTTPStatus.FORBIDDEN, "file must be inside workspace")
                return
            if not path.is_file():
                self._send_error_json(HTTPStatus.NOT_FOUND, f"file not found: {path}")
                return
            body = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            if content_type.startswith("text/") or path.suffix.lower() in {".json", ".jsonl", ".md"}:
                content_type = "text/plain; charset=utf-8" if path.suffix.lower() in {".md", ".jsonl"} else f"{content_type}; charset=utf-8"
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return GraphyAgentHandler


def _project_id(body: dict[str, Any], store: ProjectStore) -> str:
    if body.get("project_id"):
        return str(body["project_id"])
    project = store.get_current_project()
    if not project:
        raise ValueError("no current project")
    return str(project["project_id"])


def _optional_project_id(body: dict[str, Any], store: ProjectStore) -> str | None:
    if body.get("project_id"):
        return str(body["project_id"])
    project = store.get_current_project()
    return str(project["project_id"]) if project else None


def _graph_id(body: dict[str, Any], store: ProjectStore) -> str:
    if body.get("graph_id"):
        return str(body["graph_id"])
    graph_id = _optional_graph_id(store)
    if not graph_id:
        raise ValueError("no current graph")
    return graph_id


def _optional_graph_id(store: ProjectStore) -> str | None:
    project = store.get_current_project()
    return str(project.get("current_graph_id")) if project and project.get("current_graph_id") else None


def _open_local_folder(folder_path: str, workspace_root: Path) -> dict[str, Any]:
    path = Path(folder_path).expanduser().resolve()
    workspace = workspace_root.expanduser().resolve()
    try:
        path.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("graph folder must be inside workspace") from exc
    if not path.is_dir():
        raise FileNotFoundError(f"graph folder not found: {path}")
    subprocess.Popen(
        ["explorer.exe", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"opened": True, "folder_path": str(path)}


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    return values[0]


def _build_active_run_dict(run_dir: Path, mtime: float) -> dict[str, Any]:
    import datetime
    run_id = run_dir.name
    try:
        config_data = json.loads((run_dir / "graph_config.json").read_text(encoding="utf-8"))
    except Exception:
        config_data = {}

    node_runs = []
    traces_path = run_dir / "traces" / "node_runs.jsonl"
    if traces_path.exists():
        try:
            for line in traces_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    node_runs.append(json.loads(line))
        except Exception:
            pass

    started_at = datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc).isoformat()

    return {
        "graph_run_id": run_id,
        "graph_id": config_data.get("graph_id"),
        "status": "running",
        "started_at": started_at,
        "ended_at": None,
        "node_runs": [nr.get("node_run_id") for nr in node_runs],
        "node_runs_detailed": node_runs,
        "graph_config": config_data,
    }


def _get_active_run(workspace_root: Path) -> dict[str, Any] | None:
    graphs_root = workspace_root / "graph_runs"
    if not graphs_root.exists():
        return None
    active_dirs = []
    for d in graphs_root.iterdir():
        if d.is_dir() and (d / "graph_config.json").exists() and not (d / "graph_run.json").exists():
            try:
                mtime = (d / "graph_config.json").stat().st_mtime
                active_dirs.append((mtime, d))
            except Exception:
                continue
    if not active_dirs:
        return None
    active_dirs.sort(key=lambda x: x[0], reverse=True)
    mtime, run_dir = active_dirs[0]
    return _build_active_run_dict(run_dir, mtime)


def _get_active_run_by_id(workspace_root: Path, graph_run_id: str) -> dict[str, Any] | None:
    run_dir = workspace_root / "graph_runs" / graph_run_id
    if run_dir.exists() and (run_dir / "graph_config.json").exists() and not (run_dir / "graph_run.json").exists():
        try:
            mtime = (run_dir / "graph_config.json").stat().st_mtime
            return _build_active_run_dict(run_dir, mtime)
        except Exception:
            pass
    return None


def _build_html(default_config: str) -> str:
    html = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>图智能体工作流工作区</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Inter:wght@400;500;600&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg-main: #131314;
  --bg-sidebar: #1e1e1f;
  --bg-card: #1e1e1f;
  --bg-input: #1e1e1f;
  --text-primary: #e3e3e3;
  --text-secondary: #c4c7c5;
  --text-muted: #8e918f;
  --border-color: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(255, 255, 255, 0.16);
  --accent-blue: #4285f4;
  --accent-purple: #9b72cb;
  --accent-gradient: linear-gradient(90deg, #4285f4, #9b72cb, #d96570, #4285f4);
  --glow-success: rgba(21, 128, 61, 0.4);
  --glow-failed: rgba(180, 35, 24, 0.4);
  --glow-running: rgba(66, 133, 244, 0.4);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-main);
  color: var(--text-primary);
  font-family: 'Inter', sans-serif;
}
button, input, select, textarea { font-family: inherit; color: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: 0.5; }

.app {
  display: grid;
  grid-template-columns: 300px 1fr;
  height: 100vh;
  width: 100vw;
}

/* Sidebar Styles */
.sidebar {
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
}
.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-logo {
  font-size: 20px;
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: bold;
}
.brand-title {
  font-family: 'Outfit', sans-serif;
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.5px;
}
.sidebar-body {
  flex-grow: 1;
  overflow-y: auto;
  padding: 12px 8px;
}
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}
.settings-btn {
  width: 100%;
  height: 38px;
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  color: var(--text-secondary);
  padding: 0 12px;
  font-size: 13px;
  transition: background 0.2s, border-color 0.2s;
}
.settings-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: var(--border-hover);
  color: white;
}

/* Unified Tree Explorer */
.unified-tree {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tree-item {
  display: flex;
  flex-direction: column;
}
.tree-row {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
  font-size: 12.5px;
  color: var(--text-secondary);
  transition: background 0.15s, color 0.15s;
  gap: 6px;
}
.tree-row:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-primary);
}
.tree-item.active > .tree-row {
  background: rgba(66, 133, 244, 0.08);
  color: #8ab4f8;
  font-weight: 500;
}
.tree-children {
  display: none;
  padding-left: 10px;
  flex-direction: column;
  gap: 2px;
  border-left: 1px dashed rgba(255, 255, 255, 0.05);
  margin-left: 6px;
  margin-top: 2px;
}
.tree-item.expanded > .tree-children {
  display: flex;
}
.twisty {
  width: 14px;
  text-align: center;
  font-size: 9px;
  color: var(--text-muted);
}
.icon {
  font-size: 14px;
  display: inline-flex;
  align-items: center;
}
.name {
  flex-grow: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-action-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s;
  padding: 0 4px;
}
.tree-row:hover .tree-action-btn {
  opacity: 1;
}
.tree-action-btn:hover {
  color: var(--text-primary);
}
.count-badge, .file-size-badge {
  font-size: 10px;
  background: rgba(255, 255, 255, 0.05);
  padding: 1px 4px;
  border-radius: 4px;
  color: var(--text-muted);
}
.file-delete-btn {
  background: transparent;
  border: none;
  color: #da3633;
  opacity: 0;
  cursor: pointer;
  transition: opacity 0.15s;
  font-size: 12px;
  padding: 0 4px;
}
.tree-row:hover .file-delete-btn {
  opacity: 1;
}
.tree-empty-text {
  font-size: 11px;
  color: var(--text-muted);
  padding: 4px 8px 4px 22px;
  font-style: italic;
}

/* Main Content Area */
.main-content {
  display: grid;
  grid-template-rows: minmax(0,1fr) 340px;
  height: 100vh;
  overflow: hidden;
}

/* Workspace Canvas */
.workspace {
  min-height: 0;
  display: grid;
  grid-template-rows: 52px minmax(0, 1fr);
}
.graph-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-sidebar);
}
.graph-title-container {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.graph-title {
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-family: 'Outfit', sans-serif;
  font-size: 16px;
  font-weight: 700;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.graph-title:hover {
  background: rgba(255, 255, 255, 0.04);
}
.graph-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.btn {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--border-color);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.02);
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 500;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.btn:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: var(--border-hover);
  color: white;
}
.btn.primary {
  background: var(--accent-gradient);
  border: none;
  color: white;
  box-shadow: 0 2px 8px rgba(66, 133, 244, 0.3);
}
.btn.primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}
.canvas {
  position: relative;
  min-height: 0;
  overflow: auto;
  background: #0f0f10;
}
.canvas-inner {
  position: relative;
  min-width: 1200px;
  min-height: 800px;
}
.edges {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.edge {
  stroke: rgba(255, 255, 255, 0.12);
  stroke-width: 1.5;
  fill: none;
  marker-end: url(#arrow);
  transition: stroke 0.2s;
}

/* Read-only Workflow Nodes */
.node {
  position: absolute;
  width: 320px;
  height: 220px;
  overflow: hidden;
  padding: 16px;
  border: 1px solid var(--border-color);
  background: var(--bg-card);
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.4);
  transition: border-color 0.2s, box-shadow 0.2s;
  display: flex;
  flex-direction: column;
  backdrop-filter: blur(10px);
}
.node:hover {
  border-color: var(--border-hover);
}
.node.selected {
  border-color: var(--accent-purple);
  box-shadow: 0 0 15px rgba(155, 114, 203, 0.3);
}
.node.success {
  border-color: #81c995;
  box-shadow: 0 0 12px rgba(129, 201, 149, 0.2);
}
.node.failed {
  border-color: #f28b82;
  box-shadow: 0 0 12px rgba(242, 139, 130, 0.2);
}
.node.running {
  border-color: #8ab4f8;
  animation: pulse-blue 1.5s infinite alternate;
}
@keyframes pulse-blue {
  from { box-shadow: 0 0 4px rgba(138, 180, 248, 0.2); }
  to { box-shadow: 0 0 16px rgba(138, 180, 248, 0.6); }
}

.node-port {
  position: absolute;
  left: 50%;
  width: 8px;
  height: 8px;
  transform: translateX(-50%);
  background: #5f6368;
  border-radius: 50%;
}
.node-port.in { top: -4px; }
.node-port.out { bottom: -4px; }

.node-actions {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  gap: 6px;
}
.node-action-btn {
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border-color);
  color: var(--text-secondary);
  border-radius: 6px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  transition: background 0.15s, color 0.15s;
}
.node-action-btn:hover {
  background: rgba(255,255,255,0.08);
  color: white;
}
.node-action-btn.run:hover {
  background: rgba(129, 201, 149, 0.1);
  color: #81c995;
  border-color: rgba(129, 201, 149, 0.2);
}

.node-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  text-align: left;
}
.node-header-info {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}
.node-id-tag {
  font-size: 10px;
  color: var(--text-muted);
  font-family: 'Fira Code', monospace;
}
.node-type-badge {
  font-size: 9px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-color);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--text-secondary);
  text-transform: uppercase;
}
.node-title {
  font-family: 'Outfit', sans-serif;
  font-weight: 700;
  font-size: 13.5px;
  margin-bottom: 8px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-task {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.4;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  height: 48px;
}
.node-files-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: auto;
}
.mini-file-chip {
  font-size: 9.5px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--text-muted);
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mini-file-more {
  font-size: 9px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
}
.node-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
  padding-top: 8px;
}
.node-route-badge {
  font-size: 10px;
  color: var(--text-muted);
}
.node-status-badge {
  font-size: 9px;
  border-radius: 4px;
  padding: 1px 5px;
  font-weight: bold;
}
.node-status-badge.success { background: rgba(129, 201, 149, 0.1); color: #81c995; }
.node-status-badge.failed { background: rgba(242, 139, 130, 0.1); color: #f28b82; }

/* Chat Panel */
.chat {
  background: var(--bg-main);
  border-top: 1px solid var(--border-color);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  padding: 12px 24px;
  box-sizing: border-box;
  gap: 10px;
  height: 100%;
}
.chat-status {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.chat-messages {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 4px;
}
.chat-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 12.5px;
  font-style: italic;
}
.chat-msg {
  display: flex;
  flex-direction: column;
  max-width: 80%;
  animation: fadeIn 0.18s ease-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
.chat-msg.user {
  align-self: flex-end;
  background: #303134;
  border: 1px solid var(--border-color);
  border-radius: 18px 18px 4px 18px;
  padding: 12px 16px;
  color: var(--text-primary);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}
.chat-msg.assistant {
  align-self: flex-start;
  max-width: 85%;
  display: grid;
  grid-template-columns: 32px 1fr;
  gap: 12px;
}
.chat-msg.error {
  align-self: flex-start;
  background: rgba(242, 139, 130, 0.06);
  border: 1px solid rgba(242, 139, 130, 0.15);
  border-radius: 18px 18px 18px 4px;
  padding: 12px 16px;
  color: #f8b4b4;
}
.ai-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--accent-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 14px;
  color: white;
  box-shadow: 0 2px 6px rgba(0,0,0,0.3);
}
.assistant-bubble-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.chat-msg-head {
  font-size: 10px;
  color: var(--text-muted);
  display: flex;
  gap: 8px;
  align-items: center;
}
.chat-msg-body {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  word-break: break-word;
}
.chat-msg-body p { margin: 0 0 8px; }
.chat-msg-body p:last-child { margin-bottom: 0; }
.chat-msg-body strong { color: white; }
.chat-msg-body pre.code-block {
  background: #0f0f10;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
  margin: 8px 0;
}
.chat-msg-body pre.code-block code {
  font-family: 'Fira Code', monospace;
  font-size: 12px;
  color: #a8d0e6;
}
.chat-msg-body code.inline-code {
  font-family: 'Fira Code', monospace;
  background: #303134;
  border-radius: 4px;
  padding: 2px 5px;
  font-size: 11.5px;
  color: #ffcdd2;
}
.chat-msg-body ul, .chat-msg-body ol {
  margin: 4px 0 8px;
  padding-left: 20px;
}
.chat-msg-body li { margin-bottom: 4px; }
.markdown-table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 12px;
}
.markdown-table th, .markdown-table td {
  border: 1px solid rgba(255, 255, 255, 0.06);
  padding: 8px 12px;
  text-align: left;
}
.markdown-table th {
  background: rgba(255, 255, 255, 0.03);
  font-weight: 600;
  color: white;
}
.markdown-table tr:nth-child(even) { background: rgba(255, 255, 255, 0.01); }

.chat-thinking {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

/* Streaming Progress Widget */
.streaming-progress-widget {
  background: #0f0f10;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 12px;
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: 460px;
}
.progress-header {
  font-size: 12px;
  font-weight: bold;
  color: #8ab4f8;
  display: flex;
  align-items: center;
  gap: 8px;
}
.progress-header.completed {
  color: #81c995;
}
.progress-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(138, 180, 248, 0.2);
  border-top-color: #8ab4f8;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg); } }
.progress-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.progress-node-row {
  display: grid;
  grid-template-columns: 20px 1fr 60px auto;
  font-size: 11.5px;
  align-items: center;
  color: var(--text-secondary);
}
.progress-node-row.success { color: #81c995; }
.progress-node-row.failed { color: #f28b82; }
.progress-node-row.running { color: #8ab4f8; font-weight: 500; }
.progress-node-duration {
  color: var(--text-muted);
  font-size: 10px;
  text-align: right;
}

/* Advanced Chat Input Area */
.chat-input-capsule-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.attached-files-container {
  display: none;
  flex-wrap: wrap;
  gap: 6px;
  padding: 2px 8px;
}
.attached-chip {
  background: rgba(66, 133, 244, 0.08);
  border: 1px solid rgba(66, 133, 244, 0.15);
  border-radius: 16px;
  display: flex;
  align-items: center;
  padding: 4px 10px;
  gap: 6px;
  font-size: 11px;
}
.chip-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #8ab4f8;
}
.chip-remove-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.chip-remove-btn:hover { color: white; }

.chat-input-capsule {
  background: #1e1e1f;
  border: 1px solid var(--border-color);
  border-radius: 24px;
  display: flex;
  align-items: center;
  padding: 8px 16px;
  gap: 8px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.chat-input-capsule:focus-within {
  border-color: #8ab4f8;
  box-shadow: 0 0 12px rgba(66, 133, 244, 0.15);
}
.chat-input-capsule.goal-active {
  border-color: #f1a80a;
  box-shadow: 0 0 12px rgba(241, 168, 10, 0.15);
}
.chat-input-capsule.goal-active textarea::placeholder {
  color: rgba(241, 168, 10, 0.5);
}

.capsule-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 6px;
  border-radius: 50%;
  transition: background 0.15s, color 0.15s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.capsule-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: white;
}
.capsule-btn.active {
  color: #f1a80a;
  background: rgba(241, 168, 10, 0.08);
}
.chat-input-capsule textarea {
  flex-grow: 1;
  background: transparent;
  border: none;
  resize: none;
  color: var(--text-primary);
  font-family: inherit;
  font-size: 13.5px;
  line-height: 1.5;
  outline: none;
  max-height: 120px;
  padding: 4px 0;
  box-sizing: border-box;
}
.chat-send-btn {
  background: transparent;
  border: none;
  color: #8ab4f8;
  cursor: pointer;
  padding: 8px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.chat-send-btn:hover {
  background: rgba(66, 133, 244, 0.08);
}
.chat-send-btn:disabled {
  color: var(--text-muted);
  cursor: not-allowed;
  background: transparent;
}

/* Drawer & settings drawer */
.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 440px;
  background: var(--bg-sidebar);
  border-left: 1px solid var(--border-color);
  box-shadow: -10px 0 30px rgba(0,0,0,0.5);
  transform: translateX(100%);
  transition: transform 0.2s ease;
  z-index: 100;
  display: flex;
  flex-direction: column;
}
.drawer.open {
  transform: translateX(0);
}
.drawer-head {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.drawer-head strong {
  font-family: 'Outfit', sans-serif;
  font-size: 15px;
  font-weight: 700;
}
.drawer-body {
  flex-grow: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.drawer-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.drawer-section h3 {
  margin: 0;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--text-muted);
  letter-spacing: 0.5px;
}
.drawer-description {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  margin: 0;
}
.drawer-code-block {
  background: #0f0f10;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  margin: 0;
  overflow-x: auto;
}
.drawer-code-block code {
  font-family: 'Fira Code', monospace;
  font-size: 11.5px;
  color: #a8d0e6;
}
.executor-details, .drawer-run-info, .settings-section {
  background: rgba(255,255,255,0.01);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.run-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}
.run-row span:first-child {
  color: var(--text-muted);
}
.badge-type {
  background: rgba(255,255,255,0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
}
.badge.status-ok { color: #81c995; font-weight: bold; }
.badge.status-warn { color: #f28b82; font-weight: bold; }
.run-error {
  margin-top: 8px;
  border-top: 1px solid var(--border-color);
  padding-top: 8px;
}
.run-error span {
  color: #f28b82;
  font-size: 11.5px;
  font-weight: bold;
}
.run-error pre {
  margin: 4px 0 0;
  background: rgba(242, 139, 130, 0.05);
  padding: 8px;
  border-radius: 6px;
  font-size: 11px;
  overflow-x: auto;
  color: #f8b4b4;
  white-space: pre-wrap;
  font-family: 'Fira Code', monospace;
}

.label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}
.label span {
  font-weight: 600;
  color: white;
}
.input, .select, .textarea {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #131314;
  color: var(--text-primary);
  outline: none;
  padding: 6px 10px;
  font-size: 12.5px;
  transition: border-color 0.2s;
}
.input:focus, .select:focus, .textarea:focus {
  border-color: #8ab4f8;
}
.select { height: 32px; }
.help {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}
.drawer-files {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.file-chip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: rgba(255,255,255,0.02);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  font-size: 12px;
}
.file-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
}
.file-action {
  background: rgba(66, 133, 244, 0.08);
  border: 1px solid rgba(66, 133, 244, 0.15);
  color: #8ab4f8;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10.5px;
}
.file-action:hover {
  background: rgba(66, 133, 244, 0.15);
}

.toolbar {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

@media (max-width: 1100px) {
  .app {
    grid-template-columns: 1fr;
    grid-template-rows: 240px 1fr;
  }
  .sidebar {
    height: 240px;
    border-right: none;
    border-bottom: 1px solid var(--border-color);
  }
  .main-content {
    height: calc(100vh - 240px);
  }
}

/* Thinking process styling (collapsible block) */
.chat-thinking-block {
  border-left: 2px solid rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.02);
  border-radius: 4px;
  margin-bottom: 12px;
  padding: 8px 12px;
}
.chat-thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 500;
}
.chat-thinking-header:hover {
  color: var(--text-primary);
}
.chat-thinking-arrow {
  margin-left: auto;
  transition: transform 0.2s;
  font-size: 10px;
}
.chat-thinking-block.collapsed .chat-thinking-content {
  display: none;
}
.chat-thinking-block.collapsed .chat-thinking-arrow {
  transform: rotate(-90deg);
}
.chat-thinking-content {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding-top: 6px;
  margin-top: 6px;
}
.thinking-cursor {
  display: inline-block;
  width: 2px;
  background: var(--text-muted);
  margin-left: 2px;
  animation: blink 0.8s infinite;
}
@keyframes blink {
  0%, 100% { opacity: 0; }
  50% { opacity: 1; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="sidebar-header">
      <span class="brand-logo">✦</span>
      <span class="brand-title">GraphyAgent</span>
    </div>
    <div class="sidebar-body">
      <input id="filePicker" type="file" multiple hidden>
      <input id="chatFilePicker" type="file" multiple hidden onchange="handleAttachedFiles(event)">
      <div id="unifiedTree" class="unified-tree"></div>
    </div>
    <div class="sidebar-footer">
      <button class="settings-btn" onclick="openSettings()" title="环境配置">
        <span>⚙</span>
        <span>环境配置</span>
      </button>
    </div>
  </aside>
  
  <main class="main-content">
    <section class="workspace">
      <div class="graph-bar">
        <div class="graph-title-container">
          <button id="graphTitle" class="graph-title" onclick="focusCurrentGraph()" ondblclick="renameCurrentGraph()">加载中...</button>
        </div>
        <div class="graph-tools">
          <button class="btn" onclick="openGraphFolder()">图文件夹</button>
          <button class="btn primary" onclick="runCurrentGraph()">运行工作流</button>
        </div>
      </div>
      <div id="canvasView" class="canvas dropzone">
        <div id="canvasInner" class="canvas-inner"></div>
      </div>
    </section>
    
    <section class="chat">
      <div id="chatStatus" class="chat-status">当前：项目记忆 / 项目</div>
      <div id="chatMessages" class="chat-messages"></div>
      <div class="chat-input-capsule-wrapper">
        <div id="attachedFilesContainer" class="attached-files-container"></div>
        <div class="chat-input-capsule">
          <button id="attachFileBtn" class="capsule-btn" title="附加文件" onclick="triggerFilePicker()">
            <svg style="width:18px;height:18px;" viewBox="0 0 24 24"><path fill="currentColor" d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-3.31 2.69-6 6-6s6 2.69 6 6v10.5c0 4.42-3.58 8-8 8s-8-3.58-8-8V6h2v10.5c0 3.31 2.69 6 6 6s6-2.69 6-6V5c0-2.21-1.79-4-4-4s-4 1.79-4 4v12.5c0 1.1.9 2 2 2s2-.9 2-2V6h2z"/></svg>
          </button>
          <button id="goalModeBtn" class="capsule-btn" title="目标模式 (Goal Mode)" onclick="toggleGoalMode()">
            <svg style="width:18px;height:18px;" viewBox="0 0 24 24"><path fill="currentColor" d="M12 2C6.49 2 2 6.49 2 12s4.49 10 10 10s10-4.49 10-10S17.51 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8s8 3.59 8 8s-3.59 8-8 8zm3-8c0 1.66-1.34 3-3 3s-3-1.34-3-3s1.34-3 3-3s3 1.34 3 3z"/></svg>
          </button>
          <textarea id="chatPrompt" placeholder="输入问题。上方会显示当前对话目标。Shift+Enter 换行。" rows="1" oninput="autoGrowInput(this)"></textarea>
          <button id="chatSend" class="chat-send-btn" title="发送" onclick="chatGraph()">
            <svg style="width:18px;height:18px;" viewBox="0 0 24 24"><path fill="currentColor" d="M2.01 21L23 12L2.01 3L2 10l15 2l-15 2z"/></svg>
          </button>
        </div>
      </div>
    </section>
  </main>
  
  <aside id="drawer" class="drawer">
    <div class="drawer-head">
      <strong id="drawerTitle">节点详情</strong>
      <button class="capsule-btn" onclick="closeDrawer()">×</button>
    </div>
    <div id="drawerBody" class="drawer-body"></div>
  </aside>
  
  <aside id="settingsDrawer" class="drawer">
    <div class="drawer-head">
      <strong>环境配置</strong>
      <button class="capsule-btn" onclick="closeSettings()">×</button>
    </div>
    <div id="settingsBody" class="drawer-body"></div>
  </aside>
</div>

<script>
const defaultConfig=__DEFAULT_CONFIG__;
const SYNC_INTERVAL_MS=10000;
const state={
  snapshot:null,
  graph:null,
  selectedNodeId:null,
  drawerOpen:false,
  settingsOpen:false,
  settings:null,
  chatTarget:{type:'project',id:null,name:'项目'},
  pendingFileTarget:{scope:'project_unclassified'},
  dragFileId:null,
  dragNodeId:null,
  nodePositions:{},
  nodeOutputs:{},
  runs:[],
  commands:[],
  lastMessage:'',
  chatMessages:[],
  chatBusy:false,
  syncing:false,
  lastSyncAt:null,
  lastSeenCommandId:null,
  goalMode:false,
  fastPolling:false,
  expandedKeys:new Set(['project_space','workflows','nodes','data_catalog'])
};
function isExpanded(key){
  return state.expandedKeys.has(key);
}
function toggleKey(key,event){
  if(event)event.stopPropagation();
  if(state.expandedKeys.has(key)){
    state.expandedKeys.delete(key);
  }else{
    state.expandedKeys.add(key);
  }
  renderUnifiedTree();
}
const els={
  unifiedTree:document.getElementById('unifiedTree'),
  filePicker:document.getElementById('filePicker'),
  chatFilePicker:document.getElementById('chatFilePicker'),
  canvasInner:document.getElementById('canvasInner'),
  canvasView:document.getElementById('canvasView'),
  graphTitle:document.getElementById('graphTitle'),
  drawer:document.getElementById('drawer'),
  drawerTitle:document.getElementById('drawerTitle'),
  drawerBody:document.getElementById('drawerBody'),
  settingsDrawer:document.getElementById('settingsDrawer'),
  settingsBody:document.getElementById('settingsBody'),
  chatPrompt:document.getElementById('chatPrompt'),
  chatStatus:document.getElementById('chatStatus'),
  chatMessages:document.getElementById('chatMessages'),
  chatSend:document.getElementById('chatSend')
};
const NODE_W=320,NODE_H=220,COL_GAP=72,ROW_GAP=96;
let attachedFiles=[];

async function api(path,body){
  const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  const res=await fetch(path,options);
  const text=await res.text();
  const data=text?JSON.parse(text):{};
  if(!res.ok)throw new Error(data.error||res.statusText);
  return data;
}

async function loadWorkspace(){
  applySnapshot(await api('/api/workspace'));
}

async function syncWorkspace(){
  if(state.syncing)return;
  state.syncing=true;
  try{
    const [snapshot,commands]=await Promise.all([api('/api/workspace'),api('/api/agent/commands?limit=20')]);
    state.commands=commands.commands||[];
    applySnapshot(snapshot);
    state.lastSyncAt=new Date();
    
    // Check if any command is currently running to trigger fast polling
    const hasRunning = state.commands.some(item => item.status === 'running');
    if (hasRunning && !state.fastPolling) {
      startFastPolling();
    } else if (!hasRunning && state.fastPolling) {
      stopFastPolling();
    }
    
    const latest=state.commands.find(item=>item.status==='success'||item.status==='failed');
    if(latest&&latest.command_id!==state.lastSeenCommandId){
      state.lastSeenCommandId=latest.command_id;
      setStatusNote(`同步成功：${latest.command} / ${latest.status}`);
    }else {
      renderChatStatus();
    }
  }catch(err){
    setStatusNote(`同步失败：${err.message||String(err)}`);
  }finally{
    state.syncing=false;
  }
}

let fastPollInterval = null;
function startFastPolling() {
  if (state.fastPolling) return;
  state.fastPolling = true;
  fastPollInterval = setInterval(() => {
    syncWorkspace();
  }, 1000);
}
function stopFastPolling() {
  state.fastPolling = false;
  if (fastPollInterval) {
    clearInterval(fastPollInterval);
    fastPollInterval = null;
  }
}

function applySnapshot(snapshot){
  state.snapshot=snapshot;
  state.graph=snapshot.current_graph;
  state.nodePositions=state.graph?.metadata?.graphyagent?.layout||{};
  state.nodeOutputs={...state.nodeOutputs,...(state.graph?.metadata?.graphyagent?.last_node_outputs||{})};
  if(!state.selectedNodeId&&state.graph?.nodes?.length)state.selectedNodeId=state.graph.nodes[0].id;
  if(!state.chatTarget.id)setChatTarget('project',snapshot.current_project?.project_id,snapshot.current_project?.name||'项目',false);
  
  if(snapshot.current_project?.project_id){
    state.expandedKeys.add('project_' + snapshot.current_project.project_id);
    state.expandedKeys.add('workflows_' + snapshot.current_project.project_id);
  }
  if(state.graph?.graph_id){
    state.expandedKeys.add('graph_' + state.graph.graph_id);
    state.expandedKeys.add('nodes_' + state.graph.graph_id);
    state.expandedKeys.add('data_catalog_' + state.graph.graph_id);
  }
  
  renderAll();
}

function currentProjectId(){return state.snapshot?.current_project?.project_id}
function currentGraphId(){return state.snapshot?.current_graph?.graph_id}

function renderAll(){
  renderUnifiedTree();
  renderGraphHeader();
  renderCanvas();
  renderDrawer();
  renderSettingsDrawer();
  renderChatStatus();
  renderChatMessages();
}

function currentGraphName(){
  return state.graph?.metadata?.graphyagent?.name||state.graph?.graph_id||'未选择工作流图';
}

function renderGraphHeader(){
  const graphName=currentGraphName();
  els.graphTitle.textContent=graphName;
  els.graphTitle.title='双击重命名工作流';
}

function focusCurrentGraph(){
  if(!state.graph)return;
  setChatTarget('graph',currentGraphId(),currentGraphName());
}

/* Sidebar Antigravity-like unified tree explorer */
function renderUnifiedTree(){
  const s=state.snapshot;
  if(!s){
    els.unifiedTree.innerHTML='';
    return;
  }
  const currentProj=s.current_project;
  const projects=s.projects||[];
  const graphs=currentProj?.graphs||[];
  const nodes=state.graph?.nodes||[];
  
  const isProjSpaceExp = isExpanded('project_space');
  els.unifiedTree.innerHTML=`
    <div class="tree-item folder-item ${isProjSpaceExp ? 'expanded' : ''}">
      <div class="tree-row" onclick="toggleKey('project_space', event)">
        <span class="twisty">${isProjSpaceExp ? '▼' : '▶'}</span>
        <span class="icon">💼</span>
        <span class="name">项目空间</span>
        <button class="tree-action-btn" title="新建项目" onclick="event.stopPropagation();createProject()">+</button>
      </div>
      <div class="tree-children">
        ${projects.map(proj => {
          const isProjActive = proj.project_id === currentProj?.project_id;
          const isProjExp = isExpanded('project_' + proj.project_id);
          const isWorkflowsExp = isExpanded('workflows_' + proj.project_id);
          return `
            <div class="tree-item folder-item ${isProjActive ? 'active' : ''} ${isProjExp ? 'expanded' : ''}">
              <div class="tree-row" onclick="selectProject('${escapeJs(proj.project_id)}'); toggleKey('project_' + proj.project_id, event)">
                <span class="twisty" onclick="toggleKey('project_' + proj.project_id, event)">${isProjExp ? '▼' : '▶'}</span>
                <span class="icon">📁</span>
                <span class="name" title="${escapeAttr(proj.name)}">${escapeHtml(proj.name)}</span>
                <button class="file-delete-btn" title="删除项目" onclick="event.stopPropagation();deleteProject('${escapeJs(proj.project_id)}')">×</button>
              </div>
              ${isProjActive ? `
                <div class="tree-children">
                  <div class="tree-item folder-item ${isWorkflowsExp ? 'expanded' : ''}">
                    <div class="tree-row section-header" onclick="toggleKey('workflows_' + proj.project_id, event)">
                      <span class="twisty">${isWorkflowsExp ? '▼' : '▶'}</span>
                      <span class="icon">📊</span>
                      <span class="name">工作流图</span>
                      <button class="tree-action-btn" title="新建图" onclick="event.stopPropagation();createGraph()">+</button>
                    </div>
                    <div class="tree-children">
                      ${graphs.map(g => {
                        const isGraphActive = g.graph_id === currentGraphId();
                        const isGraphExp = isExpanded('graph_' + g.graph_id);
                        const isNodesExp = isExpanded('nodes_' + g.graph_id);
                        const isCatalogExp = isExpanded('data_catalog_' + g.graph_id);
                        return `
                          <div class="tree-item folder-item ${isGraphActive ? 'active' : ''} ${isGraphExp ? 'expanded' : ''}">
                            <div class="tree-row" onclick="selectGraph('${escapeJs(g.graph_id)}'); toggleKey('graph_' + g.graph_id, event)">
                              <span class="twisty" onclick="toggleKey('graph_' + g.graph_id, event)">${isGraphExp ? '▼' : '▶'}</span>
                              <span class="icon">🔗</span>
                              <span class="name" title="${escapeAttr(g.name||g.graph_id)}">${escapeHtml(g.name||g.graph_id)}</span>
                              <button class="file-delete-btn" title="删除图" onclick="event.stopPropagation();deleteGraph('${escapeJs(g.graph_id)}')">×</button>
                            </div>
                            ${isGraphActive ? `
                              <div class="tree-children">
                                <!-- Nodes Section -->
                                <div class="tree-item folder-item ${isNodesExp ? 'expanded' : ''}">
                                  <div class="tree-row section-header" onclick="toggleKey('nodes_' + g.graph_id, event)">
                                    <span class="twisty">${isNodesExp ? '▼' : '▶'}</span>
                                    <span class="icon">⚙️</span>
                                    <span class="name">任务节点</span>
                                  </div>
                                  <div class="tree-children">
                                    ${nodes.map(n => {
                                      const isNodeActive = state.selectedNodeId === n.id;
                                      const isNodeExp = isExpanded('node_' + n.id);
                                      const nFiles = getNodeFiles(n.id);
                                      return `
                                        <div class="tree-item folder-item ${isNodeActive ? 'active' : ''} ${isNodeExp ? 'expanded' : ''}">
                                          <div class="tree-row" onclick="selectNode('${escapeJs(n.id)}', false); if(event.target.tagName !== 'BUTTON') toggleKey('node_' + n.id, event)">
                                            <span class="twisty" onclick="toggleKey('node_' + n.id, event)">${nFiles.length ? (isNodeExp ? '▼' : '▶') : '•'}</span>
                                            <span class="icon">🔸</span>
                                            <span class="name" title="${escapeAttr(n.metadata?.title || n.id)}">${escapeHtml(n.metadata?.title || n.id)}</span>
                                            <button class="tree-action-btn" title="导入文件" onclick="event.stopPropagation();pickFiles('node', '${escapeJs(n.id)}')">+</button>
                                          </div>
                                          ${nFiles.length ? `
                                            <div class="tree-children">
                                              ${nFiles.map(f => renderTreeFileRow(f)).join('')}
                                            </div>
                                          ` : ''}
                                        </div>
                                      `;
                                    }).join('')}
                                  </div>
                                </div>
                                
                                <!-- Files Section -->
                                <div class="tree-item folder-item ${isCatalogExp ? 'expanded' : ''}">
                                  <div class="tree-row section-header" onclick="toggleKey('data_catalog_' + g.graph_id, event)">
                                    <span class="twisty">${isCatalogExp ? '▼' : '▶'}</span>
                                    <span class="icon">📂</span>
                                    <span class="name">数据目录</span>
                                  </div>
                                  <div class="tree-children">
                                    <!-- Graph Files -->
                                    ${renderTreeFolderRow("图级数据", "graph_unclassified", getGraphFiles(), "graph_unclassified_" + g.graph_id)}
                                    <!-- Project Files -->
                                    ${renderTreeFolderRow("项目级数据", "project_unclassified", getProjectFiles(), "project_unclassified_" + currentProj.project_id)}
                                  </div>
                                </div>
                              </div>
                            ` : ''}
                          </div>
                        `;
                      }).join('')}
                    </div>
                  </div>
                </div>
              ` : ''}
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
  bindDraggables();
}

function toggleFolder(element){
  const parent=element.parentElement;
  parent.classList.toggle('expanded');
  const twisty=element.querySelector('.twisty');
  if(twisty)twisty.textContent=parent.classList.contains('expanded')?'▼':'▶';
}

function getNodeFiles(nodeId){
  const nodesFolder=state.snapshot?.virtual_tree?.folders?.find(f=>f.id==='nodes');
  const nodeFolder=nodesFolder?.children?.find(c=>c.node_id===nodeId);
  return nodeFolder?.files||[];
}

function getGraphFiles(){
  const folder=state.snapshot?.virtual_tree?.folders?.find(f=>f.id==='graph_unclassified');
  return folder?.files||[];
}

function getProjectFiles(){
  const folder=state.snapshot?.virtual_tree?.folders?.find(f=>f.id==='project_unclassified');
  return folder?.files||[];
}

function renderTreeFolderRow(label, scope, files, folderId){
  const key = 'folder_' + folderId;
  const isExp = isExpanded(key);
  return `
    <div class="tree-item folder-item dropzone ${isExp ? 'expanded' : ''}" data-scope="${escapeAttr(scope)}" data-folder-id="${escapeAttr(folderId)}">
      <div class="tree-row" onclick="toggleKey('${escapeJs(key)}', event)">
        <span class="twisty">${isExp ? '▼' : '▶'}</span>
        <span class="icon">📁</span>
        <span class="name">${escapeHtml(label)}</span>
        <span class="count-badge">${files.length}</span>
        <button class="tree-action-btn" title="导入文件" onclick="event.stopPropagation();pickFiles('${escapeJs(scope)}')">+</button>
      </div>
      <div class="tree-children">
        ${files.map(f => renderTreeFileRow(f)).join('') || '<div class="tree-empty-text">无文件 (拖入或点 +)</div>'}
      </div>
    </div>
  `;
}

function renderTreeFileRow(file){
  const isFileActive=state.chatTarget.type==='file'&&state.chatTarget.id===file.file_id;
  const title=file.analysis?.summary||file.storage_path||file.name;
  return `
    <div class="tree-item file-item ${isFileActive?'active':''}" onclick="event.stopPropagation(); setChatTarget('file','${escapeJs(file.file_id)}','${escapeJs(file.name)}')">
      <div class="tree-row" draggable="true" data-file-id="${escapeAttr(file.file_id)}" title="${escapeAttr(title)}">
        <span class="twisty">•</span>
        <span class="icon">📄</span>
        <span class="name">${escapeHtml(file.name)}</span>
        <span class="file-size-badge">${formatBytes(file.size||0)}</span>
        <button class="file-delete-btn" title="删除文件" onclick="event.stopPropagation();deleteFile('${escapeJs(file.file_id)}')">×</button>
      </div>
    </div>
  `;
}

/* Middle Workflow Canvas rendering */
function renderCanvas(){
  const graph=state.graph;
  if(!graph){
    els.canvasInner.innerHTML='<div class="chat-empty">请在左侧创建或加载工作流图</div>';
    return;
  }
  const nodes=graph.nodes||[];
  const meta=graph.metadata?.graphyagent||{};
  const auto=computeAutoPositions(nodes);
  const layout=meta.layout_locked?state.nodePositions||{}:{};
  const pos={};
  
  for(const node of nodes){
    pos[node.id]=layout[node.id]||auto[node.id]||{x:80,y:48};
  }
  
  const width=Math.max(1200,...Object.values(pos).map(p=>p.x+NODE_W+100));
  const height=Math.max(800,...Object.values(pos).map(p=>p.y+NODE_H+100));
  els.canvasInner.style.width=width+'px';
  els.canvasInner.style.height=height+'px';
  els.canvasInner.style.minWidth=width+'px';
  els.canvasInner.style.minHeight=height+'px';
  
  const edges=[];
  for(const node of nodes){
    for(const source of node.depends_on||[]){
      if(!pos[source]||!pos[node.id])continue;
      const from=pos[source],to=pos[node.id],x1=from.x+NODE_W/2,y1=from.y+NODE_H,x2=to.x+NODE_W/2,y2=to.y,dy=Math.max(42,(y2-y1)/2);
      edges.push(`<path class="edge" d="M ${x1} ${y1} C ${x1} ${y1+dy} ${x2} ${y2-dy} ${x2} ${y2}"></path>`);
    }
  }
  
  els.canvasInner.innerHTML=`
    <svg class="edges" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <defs>
        <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L6,3 z" fill="rgba(255,255,255,0.2)"></path>
        </marker>
      </defs>
      ${edges.join('')}
    </svg>
    ${nodes.map(node=>renderNode(node,pos[node.id])).join('')}
  `;
  bindDraggables();
}

function renderNode(node,pos){
  const selected=state.selectedNodeId===node.id?' selected':'';
  const latest=node.metadata?.latest_run;
  
  let statusClass='';
  if(latest){
    if(latest.status==='success')statusClass=' success';
    else if(latest.status==='failed')statusClass=' failed';
    else if(latest.status==='running')statusClass=' running';
  }
  
  const title=node.metadata?.title||node.metadata?.name||node.id;
  const description=node.metadata?.description||node.task_type||'任务节点';
  const nodeFiles=getNodeFiles(node.id);
  const route=routeLabelForNode(node);
  
  return `
    <div class="node${selected}${statusClass}" draggable="true" data-node-id="${escapeAttr(node.id)}" style="left:${pos.x}px;top:${pos.y}px">
      <span class="node-port in"></span>
      <span class="node-port out"></span>
      <div class="node-actions">
        <button class="node-action-btn" title="查看详情" onclick="event.stopPropagation();selectNode('${escapeJs(node.id)}',true)">📋</button>
        <button class="node-action-btn run" title="运行节点" onclick="event.stopPropagation();runNode('${escapeJs(node.id)}')">▶</button>
      </div>
      <div class="node-content">
        <div class="node-header-info">
          <span class="node-id-tag">#${escapeHtml(node.id)}</span>
          <span class="node-type-badge">${escapeHtml(node.executor?.type||'noop')}</span>
        </div>
        <div class="node-title">${escapeHtml(title)}</div>
        <div class="node-task">${escapeHtml(description)}</div>
        <div class="node-files-summary">
          ${nodeFiles.slice(0, 2).map(f => `<span class="mini-file-chip">📄 ${escapeHtml(f.name)}</span>`).join('')}
          ${nodeFiles.length > 2 ? `<span class="mini-file-more">+${nodeFiles.length - 2}</span>` : ''}
        </div>
        <div class="node-footer">
          <span class="node-route-badge">${escapeHtml(route||'default')}</span>
          ${latest ? `<span class="node-status-badge ${latest.status}">${escapeHtml(latest.status)}</span>` : ''}
        </div>
      </div>
    </div>
  `;
}

function inputNamesForNode(node){
  const nodeFiles=state.graph?.metadata?.graphyagent?.files?.nodes?.[node.id]||[];
  const names=nodeFiles.map(file=>file.name).filter(Boolean);
  for(const name of Object.keys(node.inputs||{})){
    if(!names.includes(name))names.push(name);
  }
  return names;
}
function outputNamesForNode(node){
  return Object.keys(node.output_roles||node.outputs||node.executor?.write_outputs||{});
}
function routeLabelForNode(node){
  const preview=state.graph?.route_preview?.[node.id]||{};
  return node.routing?.complexity||preview.routing_reason?.replace(/^env:/,'')||preview.model_id||node.executor?.profile||'';
}
function scriptSummary(node){
  if(node.executor?.script)return node.executor.script;
  if(node.executor?.command)return Array.isArray(node.executor.command)?node.executor.command.join(' '):node.executor.command;
  if(node.executor?.code)return `${node.executor.type||'python'} 代码`;
  return node.executor?.type||'noop';
}
function scriptBody(node){
  if(node.executor?.code)return node.executor.code;
  if(node.executor?.script)return node.executor.script;
  if(node.executor?.command)return Array.isArray(node.executor.command)?node.executor.command.join('\n'):node.executor.command;
  return JSON.stringify(node.executor||{},null,2);
}

/* Detailed Node Drawer (Read-only) */
function renderDrawer(){
  if(!state.drawerOpen||!state.selectedNodeId){
    els.drawer.classList.remove('open');
    return;
  }
  const node=(state.graph?.nodes||[]).find(n=>n.id===state.selectedNodeId);
  if(!node){
    els.drawer.classList.remove('open');
    return;
  }
  
  const title=node.metadata?.title||node.metadata?.name||node.id;
  const description=node.metadata?.description||node.task_type||'任务节点';
  const type=node.executor?.type||'noop';
  const script=scriptBody(node);
  const route=routeLabelForNode(node);
  const latest=node.metadata?.latest_run;
  
  let runInfoHtml='<div class="help">无执行历史</div>';
  if(latest){
    const statusClass=latest.status==='success'?'status-ok':'status-warn';
    runInfoHtml=`
      <div class="drawer-run-info">
        <div class="run-row"><span>执行状态:</span><span class="badge ${statusClass}">${latest.status}</span></div>
        <div class="run-row"><span>模型路由:</span><span>${latest.routing?.chosen_model||latest.routing?.model||'默认'}</span></div>
        <div class="run-row"><span>执行时长:</span><span>${(latest.duration_ms/1000).toFixed(2)}s</span></div>
        ${latest.error?`<div class="run-error"><span>错误信息:</span><pre>${escapeHtml(latest.error)}</pre></div>`:''}
      </div>
    `;
  }
  
  els.drawerTitle.textContent=title;
  els.drawerBody.innerHTML=`
    <div class="drawer-section">
      <h3>任务描述</h3>
      <p class="drawer-description">${escapeHtml(description)}</p>
    </div>
    <div class="drawer-section">
      <h3>配置与路由</h3>
      <div class="executor-details">
        <div class="run-row"><span>节点类型:</span><span class="badge-type">${escapeHtml(type)}</span></div>
        ${route?`<div class="run-row"><span>选用模型:</span><span>${escapeHtml(route)}</span></div>`:''}
      </div>
    </div>
    <div class="drawer-section">
      <h3>脚本代码</h3>
      <pre class="drawer-code-block"><code>${escapeHtml(script)}</code></pre>
    </div>
    <div class="drawer-section">
      <h3>输入文件</h3>
      <div class="drawer-files">
        ${renderInputFiles(node)}
      </div>
    </div>
    <div class="drawer-section">
      <h3>输出结果</h3>
      <div class="drawer-files">
        ${renderOutputFiles(node)}
      </div>
    </div>
    <div class="drawer-section">
      <h3>运行指标</h3>
      ${runInfoHtml}
    </div>
  `;
  els.drawer.classList.add('open');
}

function renderInputFiles(node){
  const nodeFiles=state.graph?.metadata?.graphyagent?.files?.nodes?.[node.id]||[];
  const seen=new Set(nodeFiles.map(file=>file.name));
  const bound=Object.keys(node.inputs||{}).filter(name=>!seen.has(name)).map(name=>`<div class="file-chip"><span>${escapeHtml(name)}</span><span class="file-meta">映射</span></div>`);
  const rows=[...nodeFiles.map(file=>renderDrawerFile(file)),...bound];
  return rows.join('')||'<div class="help">无输入文件</div>';
}

function renderOutputFiles(node){
  const outputs=state.nodeOutputs?.[node.id]||[];
  if(!outputs.length)return '<div class="help">暂无输出工件 (运行节点后生成)</div>';
  return outputs.map(file=>`
    <div class="file-chip">
      <span>${escapeHtml(file.name)}</span>
      <span class="file-meta">
        ${escapeHtml(file.type||'output')}
        ${file.path?`<button class="file-action" onclick="openLocalFile('${escapeJs(file.path)}')">打开</button>`:''}
      </span>
    </div>
  `).join('');
}

function renderDrawerFile(file){
  const audit=file.analysis?.audit;
  const reportPath=auditReportPath(audit);
  let status=formatBytes(file.size||0);
  let action='';
  if(isDatasetFile(file)){
    if(!audit||audit.status==='running'||audit.status==='queued'){
      status='<span class="spinner" title="审计中"></span> 审计中';
    }else if(audit.status==='completed'){
      status=escapeHtml(audit.verdict||'审计完毕');
      if(reportPath)action=`<button class="file-action" onclick="openLocalFile('${escapeJs(reportPath)}')">报告</button>`;
    }else if(audit.status==='failed'){
      status='审计失败';
    }
  }
  return `
    <div class="file-chip" data-file-id="${escapeAttr(file.file_id)}">
      <span>${escapeHtml(file.name)}</span>
      <span class="file-meta">${status}${action}</span>
    </div>
  `;
}

function isDatasetFile(file){
  return /\.(csv|json|jsonl)$/i.test(file.name||file.storage_path||'')&&!/(metadata|schema|datasheet|datacard|task_spec|provenance|元数据|字段)/i.test(file.name||'');
}
function auditReportPath(audit){
  const paths=audit?.paths||{};
  return paths.audit_report_md||paths.audit_report_json||audit?.llm_summary?.path||'';
}
function openLocalFile(path){
  if(!path)return;
  window.open('/api/files/open?path='+encodeURIComponent(path),'_blank');
}
function closeDrawer(){
  state.drawerOpen=false;
  els.drawer.classList.remove('open');
}

/* Environment Settings Drawer */
async function openSettings(){
  state.settingsOpen=true;
  state.drawerOpen=false;
  renderDrawer();
  renderSettingsDrawer();
  try {
    state.settings=await api('/api/settings/api-keys');
    renderSettingsDrawer();
  }catch(err){
    els.settingsBody.innerHTML=`<div class="help">${escapeHtml(err.message||String(err))}</div>`;
    els.settingsDrawer.classList.add('open');
  }
}
function closeSettings(){
  state.settingsOpen=false;
  els.settingsDrawer.classList.remove('open');
}

function renderSettingsDrawer(){
  if(!state.settingsOpen){
    els.settingsDrawer.classList.remove('open');
    return;
  }
  const s=state.settings;
  if(!s){
    els.settingsBody.innerHTML='<div class="help">配置读取中...</div>';
    els.settingsDrawer.classList.add('open');
    return;
  }
  els.settingsBody.innerHTML=`
    ${renderProfileSetting('simple',s.profiles?.simple||{},'简单模型：适用于节点运行、节点对话。')}
    ${renderProfileSetting('complex',s.profiles?.complex||{},'复杂模型：适用于工作流编排、数据审计与总结。')}
    <div class="settings-section">
      <h3>运行配置文件</h3>
      <div class="help" style="font-family:'Fira Code',monospace;">${escapeHtml(s.env_path||'.env')}</div>
    </div>
    <div class="toolbar">
      <button class="btn primary" onclick="saveSettings()">保存环境配置</button>
      <button class="btn" onclick="closeSettings()">关闭</button>
    </div>
  `;
  els.settingsDrawer.classList.add('open');
}

function renderProfileSetting(name,item,helpText){
  const label=name==='simple'?'简单任务 API':'复杂任务 API';
  const masked=item.api_key_masked?`已配置: ${escapeHtml(item.api_key_masked)}`:'未配置';
  return `
    <div class="settings-section">
      <h3>${label}</h3>
      <div class="help">${escapeHtml(helpText)}</div>
      <label class="label">
        <span>协议格式</span>
        <select id="set_${name}_api_format" class="select">
          <option value="openai" ${item.api_format==='openai'?'selected':''}>OpenAI 格式</option>
          <option value="anthropic" ${item.api_format==='anthropic'?'selected':''}>Anthropic 格式</option>
        </select>
      </label>
      <label class="label">
        <span>API Key</span>
        <input id="set_${name}_api_key" class="input" type="password" autocomplete="off" placeholder="留空则不修改">
        <div class="help">${masked}</div>
      </label>
      <label class="label">
        <span>接口基址 (Base URL)</span>
        <input id="set_${name}_base_url" class="input" value="${escapeAttr(item.base_url||'')}" placeholder="https://api.example.com/v1">
      </label>
      <label class="label">
        <span>默认模型 (Model)</span>
        <input id="set_${name}_model" class="input" value="${escapeAttr(item.model||'')}" placeholder="${name==='complex'?'gemini-1.5-pro':'gemini-1.5-flash'}">
      </label>
    </div>
  `;
}

async function saveSettings(){
  const profiles={};
  for(const name of ['simple','complex']){
    profiles[name]={
      api_format:document.getElementById(`set_${name}_api_format`)?.value||'',
      api_key:document.getElementById(`set_${name}_api_key`)?.value.trim()||'',
      base_url:document.getElementById(`set_${name}_base_url`)?.value.trim()||'',
      model:document.getElementById(`set_${name}_model`)?.value.trim()||''
    };
  }
  state.settings=await api('/api/settings/api-keys',{profiles});
  setStatusNote('接口配置已成功保存！');
  renderSettingsDrawer();
}

function computeAutoPositions(nodes){
  const byId=new Map(nodes.map(node=>[node.id,node]));
  const depth=new Map();
  const visiting=new Set();
  function visit(node){
    if(depth.has(node.id))return depth.get(node.id);
    if(visiting.has(node.id))return 0;
    visiting.add(node.id);
    const deps=(node.depends_on||[]).filter(dep=>byId.has(dep));
    const value=deps.length?Math.max(...deps.map(dep=>visit(byId.get(dep))))+1:0;
    visiting.delete(node.id);
    depth.set(node.id,value);
    return value;
  }
  nodes.forEach(visit);
  const layers=[];
  for(const node of nodes){
    const level=depth.get(node.id)||0;
    layers[level]=layers[level]||[];
    layers[level].push(node);
  }
  const maxCount=Math.max(1,...layers.map(layer=>layer?.length||0));
  const maxWidth=maxCount*NODE_W+(maxCount-1)*COL_GAP;
  const positions={};
  layers.forEach((layer,level)=>{
    if(!layer)return;
    const layerWidth=layer.length*NODE_W+(layer.length-1)*COL_GAP;
    const offset=(maxWidth-layerWidth)/2;
    layer.forEach((node,index)=>{
      positions[node.id]={x:80+offset+index*(NODE_W+COL_GAP),y:48+level*(NODE_H+ROW_GAP)};
    });
  });
  return positions;
}

/* Actions and API calls */
async function createProject(){
  const name=prompt('新项目名称','项目_1');
  if(!name)return;
  const data=await api('/api/projects/create',{name});
  setChatTarget('project',data.project.project_id,data.project.name,false);
  applySnapshot(data.snapshot);
}
async function deleteProject(id){
  const pid = id || currentProjectId();
  if(!pid||!confirm(`确认要删除项目 [${pid}] 及其包含的所有数据吗？`))return;
  const data=await api('/api/projects/delete',{project_id:pid});
  state.chatTarget={type:'project',id:null,name:'项目'};
  applySnapshot(data.snapshot);
}
async function createGraph(){
  const name=prompt('新工作流图名称','工作流_1');
  if(!name)return;
  const data=await api('/api/graphs/create',{project_id:currentProjectId(),name});
  setChatTarget('graph',data.graph.graph_id,data.graph.metadata?.graphyagent?.name||data.graph.graph_id,false);
  applySnapshot(data.snapshot);
}
async function deleteGraph(id){
  const gid = id || currentGraphId();
  if(!gid||!confirm(`确认要删除工作流 [${gid}] 吗？`))return;
  const data=await api('/api/graphs/delete',{project_id:currentProjectId(),graph_id:gid});
  state.selectedNodeId=null;
  applySnapshot(data.snapshot);
}
async function selectProject(id){
  const data=await api('/api/projects/select',{project_id:id});
  state.selectedNodeId=null;
  state.drawerOpen=false;
  state.expandedKeys.add('project_' + id);
  setChatTarget('project',data.project.project_id,data.project.name,false);
  applySnapshot(data.snapshot);
}
async function selectGraph(id){
  const data=await api('/api/graphs/select',{project_id:currentProjectId(),graph_id:id});
  state.selectedNodeId=null;
  state.drawerOpen=false;
  state.expandedKeys.add('graph_' + id);
  setChatTarget('graph',data.graph.graph_id,data.graph.metadata?.graphyagent?.name||data.graph.graph_id,false);
  applySnapshot(data.snapshot);
}
async function renameCurrentGraph(){
  if(!state.graph)return;
  setChatTarget('graph',currentGraphId(),state.graph.metadata?.graphyagent?.name||state.graph.graph_id);
  const oldName=state.graph.metadata?.graphyagent?.name||state.graph.graph_id;
  const name=prompt('重命名工作流图',oldName);
  if(!name||name===oldName)return;
  state.graph.metadata=state.graph.metadata||{};
  state.graph.metadata.graphyagent=state.graph.metadata.graphyagent||{};
  state.graph.metadata.graphyagent.name=name;
  await saveGraph();
}
async function openGraphFolder(){
  try {
    const data=await api('/api/graphs/open-folder',{project_id:currentProjectId(),graph_id:currentGraphId()});
    if(data.snapshot)applySnapshot(data.snapshot);
    setStatusNote(`成功打开图文件夹：${data.folder_path||currentGraphId()}`);
    return data;
  }catch(err){
    const msg=`打开图文件夹失败：${err.message||String(err)}`;
    setStatusNote(msg);
    alert(msg);
    throw err;
  }
}
async function saveGraph(){
  state.graph.metadata=state.graph.metadata||{};
  state.graph.metadata.graphyagent=state.graph.metadata.graphyagent||{};
  state.graph.metadata.graphyagent.layout=state.nodePositions;
  const data=await api('/api/graphs/save',{project_id:currentProjectId(),graph_id:currentGraphId(),graph:state.graph});
  state.graph=data.graph;
  setStatusNote(`工作流图已保存：${data.diff?.summary||'无变更'}`);
  applySnapshot(data.snapshot);
  return data;
}

async function runCurrentGraph(){
  try {
    const data=await api('/api/agent/commands',{
      project_id:currentProjectId(),
      graph_id:currentGraphId(),
      target_type:'graph',
      command:'run_graph',
      process:true,
      payload:{graph:state.graph}
    });
    const command=data.command||{};
    if(command.status!=='success')throw new Error(command.error||'命令运行失败');
    const run=command.result?.run||{};
    rememberRunOutputs(run);
    setStatusNote(`运行成功：${run.graph_id||currentGraphId()}`);
    if(data.snapshot)applySnapshot(data.snapshot);
    renderDrawer();
    return data;
  }catch(err){
    const msg=`运行失败：${err.message||String(err)}`;
    setStatusNote(msg);
    alert(msg);
    throw err;
  }
}

async function runNode(id){
  try {
    const keepDrawer=state.drawerOpen;
    selectNode(id,keepDrawer);
    const data=await api('/api/agent/commands',{
      project_id:currentProjectId(),
      graph_id:currentGraphId(),
      node_id:id,
      target_type:'node',
      command:'run_node',
      process:true,
      payload:{graph:state.graph,node_id:id}
    });
    const command=data.command||{};
    if(command.status!=='success')throw new Error(command.error||'节点命令运行失败');
    const run=command.result?.run||{};
    rememberRunOutputs(run);
    setStatusNote(`节点运行成功：${id}`);
    if(data.snapshot)applySnapshot(data.snapshot);
    state.drawerOpen=keepDrawer;
    renderDrawer();
    return data;
  }catch(err){
    const msg=`节点运行失败：${err.message||String(err)}`;
    setStatusNote(msg);
    alert(msg);
    throw err;
  }
}

function rememberRunOutputs(run){
  const finalState=run?.final_state||{};
  const artifacts=finalState.artifacts||{};
  const nodeResults=finalState.node_results||{};
  for(const [nodeId,result] of Object.entries(nodeResults)){
    const outputs=[];
    for(const [name,artifactId] of Object.entries(result.outputs||{})){
      const artifact=artifacts[artifactId]||{};
      outputs.push({name,path:artifact.uri,type:artifact.type,artifact_id:artifactId});
    }
    if(outputs.length)state.nodeOutputs[nodeId]=outputs;
  }
}

/* Chat functionality (Streaming, Markdown parser, Goal Mode, Attach File) */
async function chatGraph(){
  if(state.chatBusy)return;
  const raw=els.chatPrompt.value.trim();
  if(!raw&&!attachedFiles.length)return;
  
  const t={...state.chatTarget};
  let prompt=raw;
  if(state.goalMode){
    prompt=`/goal ${prompt}`;
  }
  
  els.chatPrompt.value='';
  els.chatPrompt.style.height='auto';
  setChatBusy(true);
  setStatusNote('正在上传附件并发送指令...');
  
  const userMessageText=raw||`附加文件: ${attachedFiles.map(f=>f.name).join(', ')}`;
  pushChatMessage('user',userMessageText,t);
  
  const thinkingBubble=pushChatMessage('assistant','正在处理任务...',t,true);
  
  let thinkingSteps = [
    "正在解析用户输入及当前对话目标记忆...",
    "正在调取项目级模型参数进行意图路由与规则计算...",
    "正在基于大语言模型助手，规划与推理任务步骤...",
    "已成功获得模型响应，正在执行节点契约、数据类型审计与安全评估...",
    "已完成数据校验，正在更新工作空间视图状态..."
  ];
  let stepIdx = 0;
  let thinkingInterval = null;

  try {
    // 1. Process attachments if any
    if(attachedFiles.length){
      const scope=t.type==='node'?'node':t.type==='graph'?'graph_unclassified':'project_unclassified';
      const nodeId=t.type==='node'?t.id:null;
      
      for(const item of attachedFiles){
        thinkingBubble.text=`正在上传文件: ${item.name}...`;
        renderChatMessages();
        const base64=await readFileBase64(item.file);
        await api('/api/files/import',{
          project_id:currentProjectId(),
          graph_id:currentGraphId(),
          scope:scope,
          node_id:nodeId,
          name:item.name,
          contentBase64:base64
        });
      }
      attachedFiles=[];
      renderAttachedFiles();
    }
    
    // 2. Submit command & track streaming logs
    thinkingBubble.text = `<think>⏳ ${thinkingSteps[0]}`;
    renderChatMessages();
    
    thinkingInterval = setInterval(() => {
      if (stepIdx < thinkingSteps.length - 1) {
        stepIdx++;
        let lines = "<think>";
        for (let i = 0; i <= stepIdx; i++) {
          lines += `${i === stepIdx ? '⏳' : '✅'} ${thinkingSteps[i]}\n`;
        }
        thinkingBubble.text = lines;
        renderChatMessages();
      }
    }, 1200);

    startStreamingTracker(thinkingBubble);
    
    const data=await submitChatCommand(memoryPrompt(t,prompt),t);
    
    clearInterval(thinkingInterval);
    stopStreamingTracker();
    
    const result=commandResult(data);
    
    let resultMessage = result.message || '';
    let llmThinking = '';
    const rThinkStart = resultMessage.indexOf('<think>');
    if (rThinkStart !== -1) {
      const rThinkEnd = resultMessage.indexOf('</think>');
      if (rThinkEnd !== -1) {
        llmThinking = resultMessage.substring(rThinkStart + 7, rThinkEnd).trim();
        resultMessage = resultMessage.substring(rThinkEnd + 8).trim();
      }
    }
    
    let thinkingLog = "";
    for(let i=0; i<thinkingSteps.length; i++){
      thinkingLog += `✅ ${thinkingSteps[i]}\n`;
    }
    if (llmThinking) {
      thinkingLog += `\n🤖 LLM 思考过程：\n${llmThinking}`;
    }
    const finalFullText = `<think>${thinkingLog}</think>${formatAgentReply({...result, message: resultMessage})}`;
    
    if(result.requires_decomposition){
      streamChatMessage(thinkingBubble,'assistant',finalFullText, async () => {
        const allow=confirm(result.message||'是否同意拆解当前节点？');
        if(allow){
          const nodeName=result.decomposition_node||t.name;
          const retryBubble=pushChatMessage('assistant',`已获授权拆解节点: ${nodeName}。正在执行...`,{type:'node',id:nodeName,name:nodeName},true);
          
          let retryStepIdx = 0;
          retryBubble.text = `<think>⏳ ${thinkingSteps[0]}`;
          renderChatMessages();
          const retryThinkingInterval = setInterval(() => {
            if (retryStepIdx < thinkingSteps.length - 1) {
              retryStepIdx++;
              let lines = "<think>";
              for (let i = 0; i <= retryStepIdx; i++) {
                lines += `${i === retryStepIdx ? '⏳' : '✅'} ${thinkingSteps[i]}\n`;
              }
              retryBubble.text = lines;
              renderChatMessages();
            }
          }, 1200);

          startStreamingTracker(retryBubble);
          try {
            const retry=await submitChatCommand(`【节点记忆：${nodeName}】允许将节点拆解为子图：${raw}`,{type:'node',id:nodeName,name:nodeName});
            clearInterval(retryThinkingInterval);
            stopStreamingTracker();
            const retryResult=commandResult(retry);
            
            let retryResultMessage = retryResult.message || '';
            let retryLlmThinking = '';
            const rThinkStart2 = retryResultMessage.indexOf('<think>');
            if (rThinkStart2 !== -1) {
              const rThinkEnd2 = retryResultMessage.indexOf('</think>');
              if (rThinkEnd2 !== -1) {
                retryLlmThinking = retryResultMessage.substring(rThinkStart2 + 7, rThinkEnd2).trim();
                retryResultMessage = retryResultMessage.substring(rThinkEnd2 + 8).trim();
              }
            }
            
            let retryThinkingLog = "";
            for(let i=0; i<thinkingSteps.length; i++){
              retryThinkingLog += `✅ ${thinkingSteps[i]}\n`;
            }
            if (retryLlmThinking) {
              retryThinkingLog += `\n🤖 LLM 思考过程：\n${retryLlmThinking}`;
            }
            const retryFinalText = `<think>${retryThinkingLog}</think>${formatAgentReply({...retryResult, message: retryResultMessage})}`;
            
            streamChatMessage(retryBubble,'assistant',retryFinalText, () => {
              if(retry.snapshot)applySnapshot(retry.snapshot);
            });
          } catch(err) {
            clearInterval(retryThinkingInterval);
            stopStreamingTracker();
            finishChatMessage(retryBubble,'error',`<think>❌ ${thinkingSteps[retryStepIdx]}</think>\n\n拆解失败: ${err.message||String(err)}`);
          }
        }else{
          setStatusNote(result.message||'拆解已中止');
        }
      });
      return;
    }
    
    streamChatMessage(thinkingBubble,'assistant',finalFullText, () => {
      setStatusNote(`${resultMessage||'任务执行完成'}${result.diff?.summary?' ｜ '+result.diff.summary:''}`);
      if(data.snapshot)applySnapshot(data.snapshot);
    });
    
  }catch(err){
    if (thinkingInterval) clearInterval(thinkingInterval);
    stopStreamingTracker();
    let errorLog = "";
    for(let i=0; i<=stepIdx; i++){
      errorLog += `${i === stepIdx ? '❌' : '✅'} ${thinkingSteps[i]}\n`;
    }
    finishChatMessage(thinkingBubble,'error',`<think>${errorLog}</think>\n\n执行失败：${err.message||String(err)}`);
    setStatusNote(`失败：${err.message||String(err)}`);
  }finally{
    setChatBusy(false);
  }
}

function memoryPrompt(target,raw){
  return target.type==='node'?`【节点记忆：${target.name}】${raw}`:target.type==='graph'?`【图记忆：${target.name}】${raw}`:target.type==='file'?`【文件记忆：${target.name}】${raw}`:`【项目记忆：${target.name}】${raw}`;
}
async function submitChatCommand(prompt,target){
  return await api('/api/agent/commands',{
    project_id:currentProjectId(),
    graph_id:currentGraphId(),
    node_id:target?.type==='node'?target.id:null,
    target_type:target?.type||'graph',
    command:'chat_graph',
    process:true,
    payload:{prompt}
  });
}
function commandResult(data){
  const command=data.command||{};
  if(command.status!=='success')throw new Error(command.error||'命令失败');
  return command.result||{};
}

/* File Picker & upload helpers */
function triggerFilePicker(){
  const picker=document.getElementById('chatFilePicker');
  picker.value='';
  picker.click();
}
function handleAttachedFiles(event){
  const files=event.target.files;
  for(const file of files){
    if(!attachedFiles.some(f=>f.name===file.name)){
      attachedFiles.push({name:file.name,file:file});
    }
  }
  renderAttachedFiles();
}
function renderAttachedFiles(){
  const container=document.getElementById('attachedFilesContainer');
  if(!attachedFiles.length){
    container.innerHTML='';
    container.style.display='none';
    return;
  }
  container.style.display='flex';
  container.innerHTML=attachedFiles.map((f,i)=>`
    <div class="attached-chip">
      <span class="chip-icon">📄</span>
      <span class="chip-name" title="${escapeAttr(f.name)}">${escapeHtml(f.name)}</span>
      <button class="chip-remove-btn" onclick="removeAttachedFile(${i})">×</button>
    </div>
  `).join('');
}
function removeAttachedFile(index){
  attachedFiles.splice(index,1);
  renderAttachedFiles();
}

/* Goal Mode Toggle */
function toggleGoalMode(){
  state.goalMode=!state.goalMode;
  const btn=document.getElementById('goalModeBtn');
  const capsule=document.querySelector('.chat-input-capsule');
  if(state.goalMode){
    btn.classList.add('active');
    capsule.classList.add('goal-active');
    setStatusNote('已激活 Goal 目标追踪模式');
  }else{
    btn.classList.remove('active');
    capsule.classList.remove('goal-active');
    setStatusNote('Goal 模式已关闭');
  }
}

/* Streaming Tracker Interval */
let streamingInterval=null;
function startStreamingTracker(bubble){
  stopStreamingTracker();
  let progressDiv=document.getElementById('streamingProgressWidget');
  if(!progressDiv){
    progressDiv=document.createElement('div');
    progressDiv.id='streamingProgressWidget';
    progressDiv.className='streaming-progress-widget';
  }
  
  streamingInterval=setInterval(async ()=>{
    try {
      const res=await api('/api/runs/active');
      const active=res.active;
      if(active){
        const nodeRunMap={};
        (active.node_runs_detailed||[]).forEach(nr=>{
          nodeRunMap[nr.node_id]=nr;
        });
        
        const nodesList=(state.graph?.nodes||[]).map(node=>{
          const nr=nodeRunMap[node.id];
          let icon='⚪';
          let label='等待中';
          let duration='';
          let statusClass='queued';
          
          if(nr){
            if(nr.status==='success'){
              icon='✅';
              label='完毕';
              statusClass='success';
            }else if(nr.status==='failed'){
              icon='❌';
              label='失败';
              statusClass='failed';
            }else if(nr.status==='running'){
              icon='⏳';
              label='执行中';
              statusClass='running';
            }
            if(nr.duration_ms){
              duration=`(${(nr.duration_ms/1000).toFixed(1)}s)`;
            }
          }
          return `
            <div class="progress-node-row ${statusClass}">
              <span class="progress-node-icon">${icon}</span>
              <span class="progress-node-name">${escapeHtml(node.id)}</span>
              <span class="progress-node-status">${label}</span>
              <span class="progress-node-duration">${duration}</span>
            </div>
          `;
        }).join('');
        
        progressDiv.innerHTML=`
          <div class="progress-header">
            <span class="progress-spinner"></span>
            <span>工作流执行进度 (ID: ${active.graph_run_id.slice(-8)})</span>
          </div>
          <div class="progress-body">
            ${nodesList}
          </div>
        `;
        
        const bubbleBody=document.querySelector('.chat-msg.assistant:last-child .chat-msg-body');
        if(bubbleBody&&!bubbleBody.contains(progressDiv)){
          bubbleBody.appendChild(progressDiv);
        }
        if(els.chatMessages)els.chatMessages.scrollTop=els.chatMessages.scrollHeight;
      }
    }catch(err){
      console.error(err);
    }
  },1000);
}

function stopStreamingTracker(){
  if(streamingInterval){
    clearInterval(streamingInterval);
    streamingInterval=null;
  }
  const progressDiv=document.getElementById('streamingProgressWidget');
  if(progressDiv){
    const header=progressDiv.querySelector('.progress-header');
    if(header){
      header.innerHTML='✨ 工作流执行已完毕';
      header.className='progress-header completed';
    }
    progressDiv.removeAttribute('id');
  }
}

/* File Tree drag, drop, and imports */
function pickFiles(scope,nodeId){
  state.pendingFileTarget={scope,node_id:nodeId};
  els.filePicker.value='';
  els.filePicker.click();
}
async function importBrowserFiles(files,target){
  for(const file of files){
    const payload={
      project_id:currentProjectId(),
      graph_id:currentGraphId(),
      scope:target.scope||'project_unclassified',
      node_id:target.node_id||null,
      name:file.name
    };
    if(file.path)payload.path=file.path;
    else payload.contentBase64=await readFileBase64(file);
    
    const data=await api('/api/files/import',payload);
    const note=auditStatusFromFile(data.file);
    applySnapshot(data.snapshot);
    if(note)setStatusNote(note);
  }
}
function readFileBase64(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');
    reader.onerror=reject;
    reader.readAsDataURL(file);
  });
}
async function moveFile(fileId,target){
  const data=await api('/api/files/move',{
    project_id:currentProjectId(),
    graph_id:currentGraphId(),
    file_id:fileId,
    target_scope:target.scope,
    node_id:target.node_id||null
  });
  const note=auditStatusFromFile(data.result?.file);
  applySnapshot(data.snapshot);
  if(note)setStatusNote(note);
}
async function deleteFile(fileId){
  if(!fileId||!confirm('确认要移除此文件吗？'))return;
  const data=await api('/api/files/delete',{project_id:currentProjectId(),file_id:fileId});
  applySnapshot(data.snapshot);
  state.drawerOpen=false;
  renderDrawer();
  setStatusNote(`文件已成功移除：${data.result?.deleted_file?.name||fileId}`);
}

function bindDraggables(){
  document.querySelectorAll('.node').forEach(el=>{
    el.addEventListener('click',()=>selectNode(el.dataset.nodeId,false));
    el.addEventListener('dragstart',event=>{
      state.dragNodeId=el.dataset.nodeId;
      event.dataTransfer.setData('application/x-graphyagent-node',state.dragNodeId);
    });
  });
  document.querySelectorAll('.file-row').forEach(el=>{
    el.addEventListener('dragstart',event=>{
      state.dragFileId=el.dataset.fileId;
      event.dataTransfer.setData('application/x-graphyagent-file',state.dragFileId||'');
    });
  });
  bindDropzones();
}

function bindDropzones(){
  document.querySelectorAll('.dropzone').forEach(zone=>{
    zone.addEventListener('dragover',event=>{
      event.preventDefault();
      zone.classList.add('dragging');
    });
    zone.addEventListener('dragleave',()=>zone.classList.remove('dragging'));
    zone.addEventListener('drop',async event=>{
      event.preventDefault();
      zone.classList.remove('dragging');
      
      const target={
        scope:zone.dataset.scope||'graph_unclassified',
        node_id:zone.dataset.node||zone.dataset.nodeId||null
      };
      
      const nodeId=event.dataTransfer.getData('application/x-graphyagent-node');
      const fileId=event.dataTransfer.getData('application/x-graphyagent-file');
      
      if(zone.id==='canvasView'){
        if(nodeId){
          const rect=els.canvasInner.getBoundingClientRect();
          state.nodePositions[nodeId]={
            x:Math.max(20,event.clientX-rect.left+els.canvasView.scrollLeft-NODE_W/2),
            y:Math.max(20,event.clientY-rect.top+els.canvasView.scrollTop-NODE_H/2)
          };
          state.graph.metadata=state.graph.metadata||{};
          state.graph.metadata.graphyagent=state.graph.metadata.graphyagent||{};
          state.graph.metadata.graphyagent.layout_locked=true;
          renderCanvas();
          await saveGraph();
        }else {
          setStatusNote('请在左侧文件目录中管理或绑定文件');
        }
        return;
      }
      
      if(fileId){
        await moveFile(fileId,target);
      }else if(event.dataTransfer.files?.length){
        await importBrowserFiles(event.dataTransfer.files,target);
      }
    });
  });
}

function selectNode(id,openDetails){
  state.selectedNodeId=id;
  state.drawerOpen=Boolean(openDetails);
  state.expandedKeys.add('node_' + id);
  setChatTarget('node',id,id,false);
  renderAll();
}

function setChatTarget(type,id,name,shouldRender=true){
  state.chatTarget={type,id,name:name||id||'项目'};
  updateChatPlaceholder();
  if(shouldRender)renderChatStatus();
}

function targetLabel(target){
  const t=target||state.chatTarget;
  const label=t.type==='node'?'节点':t.type==='graph'?'工作流':t.type==='file'?'文件':'项目';
  return `${label}记忆 / ${t.name||'-'}`;
}

function updateChatPlaceholder(){
  if(!els.chatPrompt)return;
  els.chatPrompt.placeholder=`输入问题... 对话目标: ${targetLabel(state.chatTarget)}`;
}

function renderChatStatus(){
  updateChatPlaceholder();
  els.chatStatus.textContent=`当前：${targetLabel(state.chatTarget)}${state.lastMessage?' ｜ '+state.lastMessage:''}`;
}

function setStatusNote(text){
  state.lastMessage=text;
  renderChatStatus();
}

function pushChatMessage(role,text,target,thinking=false){
  const entry={
    role,
    text:String(text||''),
    target:{...(target||state.chatTarget)},
    thinking,
    at:new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})
  };
  state.chatMessages.push(entry);
  if(state.chatMessages.length>80)state.chatMessages.shift();
  renderChatMessages();
  return entry;
}

function finishChatMessage(entry,role,text){
  entry.role=role;
  entry.text=String(text||'');
  entry.thinking=false;
  renderChatMessages();
}

function streamChatMessage(entry,role,text,onDone){
  entry.role=role;
  entry.thinking=false;
  const fullText=String(text||'');
  let index=0;
  entry.text='';
  const timer=setInterval(()=>{
    if(index<fullText.length){
      const chunk=Math.min(2,fullText.length-index);
      entry.text+=fullText.substr(index,chunk);
      index+=chunk;
      renderChatMessages();
      if(els.chatMessages)els.chatMessages.scrollTop=els.chatMessages.scrollHeight;
    }else{
      clearInterval(timer);
      entry.text=fullText;
      renderChatMessages();
      if(els.chatMessages)els.chatMessages.scrollTop=els.chatMessages.scrollHeight;
      if(onDone)onDone();
    }
  },25);
}

window.toggleThinking = function(header) {
  const block = header.parentElement;
  block.classList.toggle('collapsed');
};

function renderMsgBody(text, isThinking) {
  if (!text) return '';
  
  let thinkingHtml = '';
  let answerText = text;
  
  const thinkStart = text.indexOf('<think>');
  if (thinkStart !== -1) {
    const thinkEnd = text.indexOf('</think>');
    if (thinkEnd !== -1) {
      const thinkingContent = text.substring(thinkStart + 7, thinkEnd);
      answerText = text.substring(thinkEnd + 8);
      thinkingHtml = `
        <div class="chat-thinking-block">
          <div class="chat-thinking-header" onclick="toggleThinking(this)">
            <span class="thinking-icon">🧠</span>
            <span class="thinking-title">思考过程</span>
            <span class="thinking-arrow">▼</span>
          </div>
          <div class="chat-thinking-content">
            ${parseMarkdown(thinkingContent)}
          </div>
        </div>
      `;
    } else {
      const thinkingContent = text.substring(thinkStart + 7);
      answerText = '';
      thinkingHtml = `
        <div class="chat-thinking-block">
          <div class="chat-thinking-header" onclick="toggleThinking(this)">
            <span class="thinking-icon">🧠</span>
            <span class="thinking-title">正在思考中...</span>
            <span class="thinking-arrow">▼</span>
          </div>
          <div class="chat-thinking-content">
            ${parseMarkdown(thinkingContent)}<span class="thinking-cursor">|</span>
          </div>
        </div>
      `;
    }
  } else if (isThinking) {
    return `<span class="chat-thinking"><span class="progress-spinner"></span>${escapeHtml(text)}</span>`;
  }
  
  return thinkingHtml + parseMarkdown(answerText);
}

function renderChatMessages(){
  if(!els.chatMessages)return;
  if(!state.chatMessages.length){
    els.chatMessages.innerHTML='<div class="chat-empty">在此向智能体发送关于项目、图或节点的交互指令</div>';
    return;
  }
  els.chatMessages.innerHTML=state.chatMessages.map(msg=>{
    const role=msg.role==='user'?'用户':msg.role==='error'?'系统错误':'智能体';
    const body=renderMsgBody(msg.text, msg.thinking);
    return `
      <div class="chat-msg ${escapeAttr(msg.role)}">
        <div class="chat-msg-head">
          <span>${role}</span>
          <span>${escapeHtml(targetLabel(msg.target))}</span>
          <span>${escapeHtml(msg.at||'')}</span>
        </div>
        <div class="chat-msg-body">${body}</div>
      </div>
    `;
  }).join('');
  els.chatMessages.scrollTop=els.chatMessages.scrollHeight;
}

function setChatBusy(value){
  state.chatBusy=Boolean(value);
  if(els.chatSend)els.chatSend.disabled=state.chatBusy;
  if(els.chatPrompt)els.chatPrompt.setAttribute('aria-busy',state.chatBusy?'true':'false');
}

function formatAgentReply(result){
  const lines=[result.message||'指令已成功执行'];
  if(result.diff?.summary)lines.push(`工作流变更：${result.diff.summary}`);
  if(result.diff?.added_edges?.length){
    lines.push(`新增边：${result.diff.added_edges.map(e=>`${e.source} -> ${e.target}`).join('、')}`);
  }
  if(result.diff?.removed_edges?.length){
    lines.push(`删除边：${result.diff.removed_edges.map(e=>`${e.source} -> ${e.target}`).join('、')}`);
  }
  if(result.diff?.changed_nodes?.length){
    lines.push(`更动节点：${result.diff.changed_nodes.join('、')}`);
  }
  return lines.join('\n');
}

function auditStatusFromFile(file){
  const audit=file?.analysis?.audit;
  if(!audit)return '';
  if(audit.status==='completed'){
    const llm=audit.llm_summary?.status==='completed'?'总结完毕':'总结未成';
    return `审计完毕：${file.name} [结论: ${audit.verdict}] - ${audit.tagged_record_count||0}/${audit.row_count||0} 行标记 (${llm})`;
  }
  if(audit.status==='failed')return `审计失败：${file.name} (${audit.error||''})`;
  return `审计运行中: ${file.name} [${audit.status}]`;
}

function uniqueNodeId(prefix){
  const ids=new Set((state.graph.nodes||[]).map(node=>node.id));
  let idx=1;
  while(ids.has(`${prefix}_${idx}`))idx+=1;
  return `${prefix}_${idx}`;
}

function formatBytes(size){
  if(size<1024)return `${size} B`;
  if(size<1024*1024)return `${Math.round(size/1024)} KB`;
  return `${(size/1024/1024).toFixed(1)} MB`;
}

function escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function escapeAttr(value){
  return escapeHtml(value).replace(/`/g,'&#96;');
}
function escapeJs(value){
  return JSON.stringify(String(value??'')).slice(1,-1).replace(/'/g,"\\'");
}

function autoGrowInput(el){
  el.style.height='auto';
  el.style.height=(el.scrollHeight)+'px';
}

/* Custom Markdown parser for Gemini Chat bubbles */
function parseMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  
  // 1. Code blocks: ```lang\ncode\n```
  html = html.replace(/```(?:[a-zA-Z0-9_-]+)?\n?([\s\S]*?)```/g, (match, code) => {
    return `<pre class="code-block"><code>${code.trim()}</code></pre>`;
  });
  
  // 2. Inline code: `code`
  html = html.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');
  
  // 3. Bold: **text**
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  
  // 4. Headers
  html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
  
  // 5. Lists (unordered)
  html = html.replace(/^\s*[-*]\s+(.*)$/gim, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
  html = html.replace(/<\/ul>\s*<ul>/g, '');
  
  // 6. Simple tables
  const lines = html.split('\n');
  let inTable = false;
  let tableLines = [];
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      if (!inTable) {
        tableLines.push('<table class="markdown-table">');
        inTable = true;
        const cols = line.split('|').map(c => c.trim()).filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
        tableLines.push('<thead><tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>');
      } else if (line.includes('---') || line.includes(':::')) {
        continue;
      } else {
        const cols = line.split('|').map(c => c.trim()).filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
        tableLines.push('<tr>' + cols.map(c => `<td>${c}</td>`).join('') + '</tr>');
      }
    } else {
      if (inTable) {
        tableLines.push('</tbody></table>');
        inTable = false;
      }
      tableLines.push(lines[i]);
    }
  }
  if (inTable) {
    tableLines.push('</tbody></table>');
  }
  html = tableLines.join('\n');
  
  // 7. Line breaks
  html = html.replace(/\n/g, '<br>');
  
  return html;
}

els.filePicker.addEventListener('change',()=>importBrowserFiles(els.filePicker.files,state.pendingFileTarget));
els.chatPrompt.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){
    event.preventDefault();
    chatGraph();
  }
});

loadWorkspace().catch(err=>setStatusNote(err.message||String(err)));
setInterval(()=>syncWorkspace(),SYNC_INTERVAL_MS);
</script>
</body>
</html>"""
    return html.replace("__DEFAULT_CONFIG__", json.dumps(default_config))
