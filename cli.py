"""Command line entrypoint for GraphyAgent."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from .core.config import load_graph_config
from .core.schema import GRAPH_CONFIG_SCHEMA
from .core.types import GraphConfig
from .front_bridge.service import inspect_graph_config, list_graph_runs, read_graph_run, read_node_runs
from .graph_runner.executor import GraphExecutionError, GraphExecutor


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_graph_config(args.config)
    executor = GraphExecutor(args.workspace)
    try:
        graph_run = executor.run_graph(config)
    except GraphExecutionError as exc:
        print(f"Graph run failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(graph_run.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"GraphRun {graph_run.graph_run_id}: {graph_run.status}")
        print(f"Run dir: {graph_run.run_dir}")
        print(f"Graph output: {graph_run.output_dir}")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    print(json.dumps(inspect_graph_config(args.config), indent=2, ensure_ascii=False))
    return 0


def _cmd_list_runs(args: argparse.Namespace) -> int:
    runs = list_graph_runs(args.workspace)
    if args.json:
        print(json.dumps({"runs": runs}, indent=2, ensure_ascii=False))
        return 0
    if not runs:
        print("No graph runs found.")
        return 0
    for run in runs:
        print(
            f"{run['graph_run_id']}\t{run['status']}\t"
            f"{run.get('started_at') or '-'}\t{run.get('output_dir') or '-'}"
        )
    return 0


def _cmd_show_run(args: argparse.Namespace) -> int:
    run = read_graph_run(args.workspace, args.graph_run_id)
    if args.node_runs:
        run["node_runs_detail"] = read_node_runs(args.workspace, args.graph_run_id)
    print(json.dumps(run, indent=2, ensure_ascii=False))
    return 0


def _cmd_schema(args: argparse.Namespace) -> int:
    print(json.dumps(GRAPH_CONFIG_SCHEMA, indent=2, ensure_ascii=False))
    return 0


def _cmd_init_project(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore

    store = ProjectStore(args.workspace)
    project = store.create_project(args.name)
    if args.json:
        print(json.dumps({"project": project, "snapshot": store.snapshot()}, indent=2, ensure_ascii=False))
    else:
        print(f"Project {project['project_id']}: {project['name']}")
    return 0


def _cmd_import_project_file(args: argparse.Namespace) -> int:
    from .data_manager.project_store import GRAPH_UNCLASSIFIED, PROJECT_UNCLASSIFIED, ProjectStore

    store = ProjectStore(args.workspace)
    scope = args.scope
    if scope == "project":
        scope = PROJECT_UNCLASSIFIED
    elif scope == "graph":
        scope = GRAPH_UNCLASSIFIED
    result = store.import_file(
        args.project,
        scope,
        graph_id=args.graph,
        node_id=args.node,
        path=args.path,
        name=args.name,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_plan_graph(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore

    store = ProjectStore(args.workspace)
    result = store.decompose_task_to_graph(
        args.project,
        args.task,
        graph_id=args.graph,
        name=args.name,
        create_new_graph=not bool(args.graph and args.update_current),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_run_project_graph(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore

    store = ProjectStore(args.workspace)
    graph = store.read_graph(args.project, args.graph)
    try:
        run = GraphExecutor(args.workspace).run_graph(GraphConfig.from_dict(graph)).to_dict()
    except GraphExecutionError as exc:
        print(f"Graph run failed: {exc}", file=sys.stderr)
        return 1
    store.record_graph_run(args.project, args.graph, run, command_record={"origin": "cli", "command": "run-graph"})
    if args.json:
        print(json.dumps(run, indent=2, ensure_ascii=False))
    else:
        print(f"GraphRun {run['graph_run_id']}: {run['status']}")
        print(f"Run dir: {run.get('run_dir')}")
    return 0


def _cmd_export_trace(args: argparse.Namespace) -> int:
    from .graph_runner.history import export_trace_dataset

    result = export_trace_dataset(args.workspace, args.graph_run, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_optimize_graph(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore
    from .graph_optimizer import analyze_graph_runs, materialize_new_graph_version

    store = ProjectStore(args.workspace)
    graph = store.read_graph(args.project, args.graph)
    graph_run_ids = args.graph_run_ids or None
    analysis = analyze_graph_runs(args.graph, workspace=args.workspace, graph=graph, graph_run_ids=graph_run_ids)
    result: dict[str, Any] = {"analysis": analysis}
    if args.materialize:
        result["version"] = materialize_new_graph_version(
            graph,
            analysis.get("suggestions") or [],
            workspace=args.workspace,
            project_id=args.project,
            graph_id=args.graph,
            persist=args.persist,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_compare_graphs(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore
    from .evaluation import compare_graph_versions

    store = ProjectStore(args.workspace)
    base = store.read_graph(args.project, args.base)
    candidate = store.read_graph(args.project, args.candidate)
    print(json.dumps(compare_graph_versions(base, candidate), indent=2, ensure_ascii=False))
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .front_bridge.webapp import start_graphyagent_web_server

    start_graphyagent_web_server(
        host=args.host,
        port=args.port,
        workspace=args.workspace,
        default_config=args.config,
    )
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from .data_audit import audit_dataset, write_audit_outputs

    try:
        report = audit_dataset(args.dataset, metadata_path=args.metadata)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1
    if args.output_dir:
        paths = write_audit_outputs(report, args.output_dir)
        print(json.dumps(paths, indent=2, ensure_ascii=False))
    elif args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        metrics = report["dataset_metrics"]
        gate = report["gate"]
        print(f"Audit verdict: {report['verdict']}")
        print(f"Rows: {metrics['row_count']}  Evidence: {metrics['evidence_count']}")
        print(f"Tagged records: {metrics['tagged_record_count']} ({metrics['tagged_record_rate']:.2%})")
        if metrics.get("synthetic_evidence_families"):
            print("Synthetic evidence families: " + ", ".join(metrics["synthetic_evidence_families"]))
        print("Recommended actions: " + (", ".join(gate["recommended_actions"]) or "none"))
    return 0


def _cmd_agent_submit(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore
    from .front_bridge.agent_commands import AgentCommandStore

    try:
        payload = json.loads(args.payload_json or "{}")
    except json.JSONDecodeError as exc:
        print(f"Invalid payload JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("payload JSON must be an object", file=sys.stderr)
        return 1
    store = AgentCommandStore(args.workspace)
    module = args.module
    command_name = args.module_command or args.agent_command
    if not module and "." in command_name:
        module, command_name = command_name.split(".", 1)
    command = store.submit_command(
        project_id=args.project_id,
        graph_id=args.graph_id,
        node_id=args.node_id,
        target_type=args.target,
        command=command_name,
        module=module,
        payload=payload,
        origin="cli",
    )
    if args.process:
        command = store.process_command(ProjectStore(args.workspace), command["command_id"])
    print(json.dumps(command, indent=2, ensure_ascii=False))
    return 0 if command.get("status") != "failed" else 1


def _cmd_agent_worker(args: argparse.Namespace) -> int:
    from .data_manager.project_store import ProjectStore
    from .front_bridge.agent_commands import AgentCommandStore

    store = AgentCommandStore(args.workspace)
    project_store = ProjectStore(args.workspace)
    if args.command_id:
        command = store.process_command(project_store, args.command_id)
        print(json.dumps(command, indent=2, ensure_ascii=False))
        return 0 if command.get("status") != "failed" else 1
    if args.watch:
        return _cmd_agent_worker_watch(args, store, project_store)
    processed = store.process_until_idle(project_store, limit=args.limit)
    print(json.dumps({"processed": processed}, indent=2, ensure_ascii=False))
    return 0 if all(item.get("status") != "failed" for item in processed) else 1


def _cmd_agent_worker_watch(
    args: argparse.Namespace,
    store: Any,
    project_store: Any,
) -> int:
    processed_total = 0
    failed_total = 0
    idle_started: float | None = None
    interval = max(0.1, float(args.interval))
    idle_exit_seconds = (
        float(args.idle_exit_seconds)
        if args.idle_exit_seconds is not None
        else None
    )
    try:
        while True:
            processed = store.process_until_idle(project_store, limit=args.limit)
            if processed:
                idle_started = None
                processed_total += len(processed)
                failed_total += sum(1 for item in processed if item.get("status") == "failed")
                print(json.dumps({"processed": processed}, indent=2, ensure_ascii=False), flush=True)
                continue
            if idle_started is None:
                idle_started = time.monotonic()
            if idle_exit_seconds is not None and time.monotonic() - idle_started >= idle_exit_seconds:
                print(
                    json.dumps(
                        {
                            "status": "idle",
                            "processed_total": processed_total,
                            "failed_total": failed_total,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                )
                return 0 if failed_total == 0 else 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "processed_total": processed_total,
                    "failed_total": failed_total,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if failed_total == 0 else 1


def _cmd_agent_commands(args: argparse.Namespace) -> int:
    from .front_bridge.agent_commands import AgentCommandStore

    commands = AgentCommandStore(args.workspace).list_commands(limit=args.limit)
    print(json.dumps({"commands": commands}, indent=2, ensure_ascii=False))
    return 0


def _cmd_agent_tools(args: argparse.Namespace) -> int:
    from .agent_runtime.agents import GraphyAgentAgentRuntime
    from .agent_runtime.tool_catalog import format_agent_tools_markdown, list_module_inventory
    from .data_manager.project_store import ProjectStore

    if args.inventory:
        print(json.dumps({"modules": list_module_inventory(args.classification)}, indent=2, ensure_ascii=False))
        return 0
    runtime = GraphyAgentAgentRuntime(args.workspace, ProjectStore(args.workspace))
    if args.json:
        print(json.dumps({"tools": runtime.list_tools(args.target)}, indent=2, ensure_ascii=False))
    else:
        print(format_agent_tools_markdown(args.target))
    return 0


def _cmd_agent_modules(args: argparse.Namespace) -> int:
    from .agent_runtime.module_registry import (
        format_module_commands_markdown,
        list_module_commands,
        list_modules,
    )

    if args.json:
        print(json.dumps({
            "modules": list_modules(),
            "commands": list_module_commands(args.module, args.target),
        }, indent=2, ensure_ascii=False))
    else:
        print(format_module_commands_markdown(args.module, args.target))
    return 0


def _cmd_init_example(args: argparse.Namespace) -> int:
    target = Path(args.path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    example = {
        "graph_id": "hello_graphyagent",
        "context": {"purpose": "minimal GraphyAgent runtime demo"},
        "initial_artifacts": {
            "raw.txt": {
                "path": str(target.parent / "raw.txt"),
                "type": "raw_data",
            }
        },
        "nodes": [
            {
                "id": "clean",
                "inputs": {"raw.txt": "raw.txt"},
                "executor": {
                    "type": "python",
                    "code": (
                        "from pathlib import Path\n"
                        "raw = Path('inputs/raw.txt').read_text(encoding='utf-8')\n"
                        "Path('outputs/clean.txt').write_text(raw.strip().upper() + '\\n', encoding='utf-8')\n"
                    ),
                },
                "output_roles": {"clean.txt": "cleaned_data"},
            },
            {
                "id": "report",
                "depends_on": ["clean"],
                "inputs": {"clean.txt": "clean:clean.txt"},
                "executor": {
                    "type": "python",
                    "code": (
                        "import json\n"
                        "from pathlib import Path\n"
                        "text = Path('inputs/clean.txt').read_text(encoding='utf-8')\n"
                        "Path('outputs/report.json').write_text(json.dumps({'chars': len(text), 'text': text}, indent=2), encoding='utf-8')\n"
                    ),
                },
                "output_roles": {"report.json": "report"},
            },
        ],
        "output_nodes": ["report"],
    }
    if not (target.parent / "raw.txt").exists():
        (target.parent / "raw.txt").write_text("hello graphyagent\n", encoding="utf-8")
    target.write_text(json.dumps(example, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote example graph config: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from .agent_runtime.tool_catalog import agent_command_names, agent_target_types
    from .agent_runtime.module_registry import agent_module_names, module_target_types

    target_choices = sorted(set(agent_target_types()) | set(module_target_types()))

    parser = argparse.ArgumentParser(prog="graphyagent")
    parser.add_argument(
        "--workspace",
        default=".graphyagent",
        help="GraphyAgent workspace for artifacts, graph runs, and traces.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_project = sub.add_parser("init-project", help="Create a project workspace.")
    init_project.add_argument("--name", required=True, help="Project display name.")
    init_project.add_argument("--json", action="store_true", help="Print JSON.")
    init_project.set_defaults(func=_cmd_init_project)

    import_file = sub.add_parser("import-file", help="Import a file into a project, graph, or node scope.")
    import_file.add_argument("--project", required=True, help="Project id.")
    import_file.add_argument("--graph", help="Graph id for graph/node scope.")
    import_file.add_argument("--node", help="Node id for node scope.")
    import_file.add_argument("--scope", choices=["project", "graph", "node"], default="project", help="Import scope.")
    import_file.add_argument("--name", help="Stored file display name.")
    import_file.add_argument("path", help="Path to import.")
    import_file.set_defaults(func=_cmd_import_project_file)

    plan_graph = sub.add_parser("plan-graph", help="Plan a workflow graph from a task description.")
    plan_graph.add_argument("--project", required=True, help="Project id.")
    plan_graph.add_argument("--graph", help="Existing graph id to update.")
    plan_graph.add_argument("--name", help="Graph display name.")
    plan_graph.add_argument("--task", required=True, help="Task or workflow description.")
    plan_graph.add_argument("--update-current", action="store_true", help="Update --graph instead of creating a new graph.")
    plan_graph.set_defaults(func=_cmd_plan_graph)

    run_project_graph = sub.add_parser("run-graph", help="Run a project graph by id.")
    run_project_graph.add_argument("--project", required=True, help="Project id.")
    run_project_graph.add_argument("--graph", required=True, help="Graph id.")
    run_project_graph.add_argument("--json", action="store_true", help="Print GraphRun JSON.")
    run_project_graph.set_defaults(func=_cmd_run_project_graph)

    export_trace = sub.add_parser("export-trace", help="Export a GraphRun trace dataset.")
    export_trace.add_argument("--graph-run", required=True, help="GraphRun id.")
    export_trace.add_argument("--output-dir", help="Optional output directory.")
    export_trace.set_defaults(func=_cmd_export_trace)

    optimize_graph = sub.add_parser("optimize-graph", help="Analyze graph runs and suggest a new graph version.")
    optimize_graph.add_argument("--project", required=True, help="Project id.")
    optimize_graph.add_argument("--graph", required=True, help="Graph id.")
    optimize_graph.add_argument("--graph-run-ids", nargs="*", help="Optional GraphRun ids to analyze.")
    optimize_graph.add_argument("--materialize", action="store_true", help="Return a candidate graph version.")
    optimize_graph.add_argument("--persist", action="store_true", help="Persist the materialized candidate to the project graph.")
    optimize_graph.set_defaults(func=_cmd_optimize_graph)

    compare_graphs = sub.add_parser("compare-graphs", help="Compare two project graph versions.")
    compare_graphs.add_argument("--project", required=True, help="Project id.")
    compare_graphs.add_argument("--base", required=True, help="Base graph id.")
    compare_graphs.add_argument("--candidate", required=True, help="Candidate graph id.")
    compare_graphs.set_defaults(func=_cmd_compare_graphs)

    run = sub.add_parser("run", help="Run a graph config.")
    run.add_argument("config", help="Path to a JSON/YAML graph config.")
    run.add_argument("--json", action="store_true", help="Print GraphRun JSON.")
    run.set_defaults(func=_cmd_run)

    inspect = sub.add_parser("inspect", help="Print normalized graph config.")
    inspect.add_argument("config", help="Path to a JSON/YAML graph config.")
    inspect.set_defaults(func=_cmd_inspect)

    list_runs = sub.add_parser("list-runs", help="List recorded graph runs.")
    list_runs.add_argument("--json", action="store_true", help="Print JSON.")
    list_runs.set_defaults(func=_cmd_list_runs)

    show_run = sub.add_parser("show-run", help="Print a recorded graph run.")
    show_run.add_argument("graph_run_id", help="Graph run id.")
    show_run.add_argument(
        "--node-runs",
        action="store_true",
        help="Include NodeRun JSONL details.",
    )
    show_run.set_defaults(func=_cmd_show_run)

    schema = sub.add_parser("schema", help="Print the graph config JSON schema.")
    schema.set_defaults(func=_cmd_schema)

    serve = sub.add_parser("serve", help="Start the graph canvas and API.")
    serve.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    serve.add_argument("--port", type=int, default=8765, help="Port to bind.")
    serve.add_argument(
        "--config",
        default="apps/windows/templates/blank.json",
        help="Default graph config path shown in the UI.",
    )
    serve.set_defaults(func=_cmd_serve)

    audit = sub.add_parser("audit", help="Audit CSV/JSON/JSONL data quality.")
    audit.add_argument("dataset", help="Dataset path (.csv, .json, or .jsonl).")
    audit.add_argument("--metadata", help="Optional JSON metadata/schema/task/provenance file.")
    audit.add_argument("--output-dir", help="Write audit_report/evidence/record_tags outputs here.")
    audit.add_argument("--json", action="store_true", help="Print the full audit report JSON.")
    audit.set_defaults(func=_cmd_audit)

    agent_submit = sub.add_parser("agent-submit", help="Submit a graph/node agent command.")
    agent_submit.add_argument("--project-id", help="Project id. Required except create_project.")
    agent_submit.add_argument("--graph-id", help="Graph id.")
    agent_submit.add_argument("--node-id", help="Node id for node-level commands.")
    agent_submit.add_argument(
        "--target",
        default="graph",
        choices=target_choices,
        help="Command target scope.",
    )
    agent_submit.add_argument(
        "--agent-command",
        default="run_graph",
        choices=agent_command_names(),
        help="Command to submit.",
    )
    agent_submit.add_argument(
        "--module",
        choices=agent_module_names(),
        help="Optional module for module-first commands.",
    )
    agent_submit.add_argument(
        "--module-command",
        help="Command inside --module. Qualified form module.command also works.",
    )
    agent_submit.add_argument("--payload-json", default="{}", help="JSON object payload.")
    agent_submit.add_argument("--process", action="store_true", help="Process immediately after submit.")
    agent_submit.set_defaults(func=_cmd_agent_submit)

    agent_worker = sub.add_parser("agent-worker", help="Process queued graph/node agent commands.")
    agent_worker.add_argument("--command-id", help="Process one command id.")
    agent_worker.add_argument("--limit", type=int, default=20, help="Maximum queued commands to process.")
    agent_worker.add_argument("--watch", action="store_true", help="Keep polling and processing queued commands.")
    agent_worker.add_argument("--interval", type=float, default=2.0, help="Seconds between idle queue polls in watch mode.")
    agent_worker.add_argument(
        "--idle-exit-seconds",
        type=float,
        help="In watch mode, exit after this many idle seconds.",
    )
    agent_worker.set_defaults(func=_cmd_agent_worker)

    agent_commands = sub.add_parser("agent-commands", help="List recent graph/node agent commands.")
    agent_commands.add_argument("--limit", type=int, default=50, help="Maximum commands to show.")
    agent_commands.set_defaults(func=_cmd_agent_commands)

    agent_tools = sub.add_parser("agent-tools", help="List graph/node agent tools.")
    agent_tools.add_argument(
        "--target",
        choices=agent_target_types(),
        help="Filter tools by target type.",
    )
    agent_tools.add_argument("--json", action="store_true", help="Print JSON.")
    agent_tools.add_argument("--inventory", action="store_true", help="Print root module integration inventory.")
    agent_tools.add_argument("--classification", help="Filter module inventory by classification.")
    agent_tools.set_defaults(func=_cmd_agent_tools)

    agent_modules = sub.add_parser("agent-modules", help="List module-first agent commands.")
    agent_modules.add_argument("--module", choices=agent_module_names(), help="Filter by module.")
    agent_modules.add_argument(
        "--target",
        choices=target_choices,
        help="Filter module commands by target type.",
    )
    agent_modules.add_argument("--json", action="store_true", help="Print JSON.")
    agent_modules.set_defaults(func=_cmd_agent_modules)

    init_example = sub.add_parser("init-example", help="Create a runnable example config.")
    init_example.add_argument("path", help="Where to write the example JSON config.")
    init_example.set_defaults(func=_cmd_init_example)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
