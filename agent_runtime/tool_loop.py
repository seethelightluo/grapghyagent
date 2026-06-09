"""Anthropic-style tool loop for graph chat commands."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..core.types import utc_now
from ..data_manager.project_store import GRAPH_UNCLASSIFIED, NODE_FILES, PROJECT_UNCLASSIFIED
from ..model_routing.llm_client import tool_chat_completion
from .tool_registry import execute_tool as execute_registered_tool


MAX_TOOL_RESULT_CHARS = 24_000


def run_chat_graph_tool_loop(
    runtime: Any,
    record: dict[str, Any],
    payload: dict[str, Any],
    *,
    project_id: str,
    graph_id: str | None,
    prompt: str,
) -> dict[str, Any]:
    """Run a blocking model/tool loop for the chat_graph entrypoint."""
    memory_target, normalized_prompt = _parse_memory_prompt(prompt)
    if not normalized_prompt:
        raise ValueError("chat_graph requires prompt")

    current_graph_id = graph_id
    if current_graph_id:
        runtime.project_store.append_memory_event(
            project_id,
            current_graph_id,
            memory_target,
            "user",
            normalized_prompt,
        )
    else:
        runtime.project_store.append_memory_event(
            project_id,
            "",
            {"type": "project", "name": project_id},
            "user",
            normalized_prompt,
        )

    loop_state: dict[str, Any] = {
        "project_id": project_id,
        "graph_id": current_graph_id,
        "memory_target": memory_target,
        "last_run": None,
        "changed": False,
        "opened_canvas": False,
        "diffs": [],
        "file_assignments": [],
    }
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": _initial_user_message(runtime, project_id, current_graph_id, memory_target, normalized_prompt),
                }
            ],
        }
    ]
    tools = _chat_graph_tool_schemas()
    trace: list[dict[str, Any]] = []
    max_steps = _positive_int_env("GRAPHYAGENT_AGENT_LOOP_MAX_STEPS", default=10)
    final_text = ""
    last_completion: dict[str, Any] = {}

    for step_index in range(max_steps):
        completion = tool_chat_completion(
            messages,
            tools,
            profile="complex",
            system=_system_prompt(),
            fallback_profiles=[],
            max_tokens=_positive_int_env("GRAPHYAGENT_AGENT_LOOP_MAX_TOKENS", default=8000),
            temperature=0.1,
            timeout_seconds=float(os.environ.get("GRAPHYAGENT_AGENT_LOOP_TIMEOUT_SECONDS") or 180),
        )
        last_completion = completion
        content = completion.get("content") if isinstance(completion.get("content"), list) else []
        messages.append({"role": "assistant", "content": content})
        tool_uses = completion.get("tool_uses") if isinstance(completion.get("tool_uses"), list) else []
        step_trace: dict[str, Any] = {
            "step": step_index + 1,
            "assistant_text": _clip(str(completion.get("text") or ""), 3000),
            "tool_uses": [],
            "model": completion.get("model"),
            "profile": completion.get("profile"),
            "stop_reason": completion.get("stop_reason"),
        }
        trace.append(step_trace)
        if not tool_uses:
            final_text = str(completion.get("text") or "").strip()
            break

        tool_results: list[dict[str, Any]] = []
        for tool_use in tool_uses:
            tool_name = str((tool_use or {}).get("name") or "")
            tool_input = (tool_use or {}).get("input")
            if not isinstance(tool_input, dict):
                tool_input = {}
            tool_use_id = str((tool_use or {}).get("id") or "")
            try:
                result = _execute_loop_tool(
                    runtime,
                    tool_name,
                    tool_input,
                    record,
                    payload,
                    loop_state,
                    original_prompt=normalized_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                result = {"status": "error", "error": str(exc), "tool": tool_name}
                is_error = True
            else:
                is_error = False
            call_trace = _agent_tool_call_trace(
                tool_use_id,
                tool_name,
                tool_input,
                result,
                loop_state,
                is_error=is_error,
            )
            step_trace["tool_uses"].append(call_trace)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": str((tool_use or {}).get("id") or ""),
                    "content": _tool_result_content(result),
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})
    else:
        final_text = "已达到工具循环步数上限，已保留当前完成的工具结果；如需继续，请再次发送指令。"

    result = _final_result(
        runtime,
        project_id,
        loop_state,
        final_text=final_text,
        trace=trace,
        completion=last_completion,
    )
    if current_graph_id or loop_state.get("graph_id"):
        runtime.project_store.append_memory_event(
            project_id,
            str(loop_state.get("graph_id") or current_graph_id or ""),
            memory_target if memory_target.get("type") in {"graph", "node", "file"} else {"type": "graph", "name": str(loop_state.get("graph_id") or current_graph_id or "")},
            "assistant",
            result.get("message") or "",
        )
    return result


def _chat_graph_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "InspectWorkspace",
            "description": "查看当前 project、graph、节点、未分类文件、节点文件和数据审计候选；不会修改状态。",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "ReadFile",
            "description": "读取文本、Markdown、JSON、PDF、图片 OCR 或表格文件的内容预览。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 120000},
                    "page_range": {"type": "string"},
                    "sheet": {"type": "string"},
                },
                "required": ["file_path"],
            },
        },
        {
            "name": "ReadTable",
            "description": "读取 CSV/TSV/Excel 的前若干行，适合判断字段、样本行和数据类型。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "sheet": {"type": "string"},
                    "max_rows": {"type": "integer", "default": 80},
                    "max_chars": {"type": "integer", "default": 120000},
                },
                "required": ["file_path"],
            },
        },
        {
            "name": "AuditDataset",
            "description": "对 CSV/JSON/JSONL 数据集执行本地 data_audit 质量审计，并可写出审计产物。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "dataset": {"type": "string"},
                    "metadata": {"type": "string"},
                    "output_dir": {"type": "string"},
                },
                "required": ["dataset"],
            },
        },
        {
            "name": "DecomposeTaskToGraph",
            "description": "根据已经读取/审计到的上下文创建或重建 workflow 图。此工具会调用 task_decompose 并持久化图。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "name": {"type": "string"},
                    "create_new_graph": {"type": "boolean", "default": True},
                },
                "required": ["prompt"],
            },
        },
        {
            "name": "UpdateWorkflowGraph",
            "description": "保存模型调整后的当前图结构；用于扩展节点、修正依赖、调整 executor、inputs 或 output_roles。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "graph": {"type": "object"},
                    "reason": {"type": "string"},
                },
                "required": ["graph"],
            },
        },
        {
            "name": "AssignFileToNode",
            "description": "把项目/图/节点文件移动到当前图的指定节点，并自动同步为 node.inputs 与 initial_artifacts。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "file_name": {"type": "string"},
                    "node_id": {"type": "string"},
                    "graph_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["node_id"],
            },
        },
        {
            "name": "RunGraph",
            "description": "运行当前图并持久化 GraphRun、节点输出、产物索引和记忆。只有用户要求执行或需要验证结果时调用。",
            "input_schema": {"type": "object", "properties": {"graph_id": {"type": "string"}}},
        },
        {
            "name": "RunNode",
            "description": "运行当前图中的一个节点及其上游依赖。",
            "input_schema": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}, "graph_id": {"type": "string"}},
                "required": ["node_id"],
            },
        },
        {
            "name": "SaveWorkflow",
            "description": "保存当前工作流版本快照。",
            "input_schema": {"type": "object", "properties": {"note": {"type": "string"}}},
        },
        {
            "name": "OpenCanvas",
            "description": "返回当前图供前端打开画板；不会修改图。",
            "input_schema": {"type": "object", "properties": {"graph_id": {"type": "string"}}},
        },
    ]


def _execute_loop_tool(
    runtime: Any,
    tool_name: str,
    arguments: dict[str, Any],
    record: dict[str, Any],
    payload: dict[str, Any],
    loop_state: dict[str, Any],
    *,
    original_prompt: str,
) -> dict[str, Any]:
    project_id = str(loop_state["project_id"])
    graph_id = arguments.get("graph_id") or loop_state.get("graph_id")

    if tool_name == "InspectWorkspace":
        return _workspace_snapshot(runtime, project_id, str(graph_id) if graph_id else None)

    if tool_name in {"ReadFile", "ReadTable"}:
        file_path = str(arguments.get("file_path") or "")
        if not file_path:
            file_path = _file_path_from_id_or_name(runtime, project_id, arguments)
        allowed = {"file_path", "max_chars", "page_range", "sheet", "max_rows"}
        read_arguments = {
            key: value
            for key, value in arguments.items()
            if key in allowed
        }
        read_arguments["file_path"] = file_path
        registry_tool = "ReadTable" if tool_name == "ReadTable" else "ReadFile"
        return execute_registered_tool(
            registry_tool,
            read_arguments,
            workspace_root=str(runtime.workspace_root),
            allow_outside_workspace=True,
            use_cache=True,
        )

    if tool_name == "AuditDataset":
        audit_payload = dict(arguments)
        result = runtime._audit_dataset(  # noqa: SLF001
            {**record, "project_id": project_id, "graph_id": graph_id},
            audit_payload,
        )
        return {"status": "success", "audit": _compact_audit_result(result), "paths": result.get("paths")}

    if tool_name == "DecomposeTaskToGraph":
        tool_prompt = str(arguments.get("prompt") or original_prompt)
        enriched_prompt = _decompose_prompt_with_context(runtime, project_id, str(graph_id) if graph_id else None, tool_prompt)
        create_new_graph = arguments.get("create_new_graph")
        if create_new_graph is None:
            create_new_graph = not bool(graph_id)
        result = runtime.project_store.decompose_task_to_graph(
            project_id,
            enriched_prompt,
            graph_id=str(graph_id) if graph_id else None,
            name=arguments.get("name"),
            create_new_graph=bool(create_new_graph),
        )
        resolved_graph_id = result.get("graph", {}).get("graph_id") or graph_id
        loop_state["graph_id"] = resolved_graph_id
        loop_state["changed"] = True
        loop_state["opened_canvas"] = True
        loop_state["diffs"].append({"tool": tool_name, "summary": result.get("message"), "diff": result.get("diff")})
        return _decompose_result_for_model(result)

    if tool_name == "UpdateWorkflowGraph":
        graph = arguments.get("graph")
        if not isinstance(graph, dict):
            raise ValueError("UpdateWorkflowGraph requires graph object")
        if not graph_id:
            graph_id = graph.get("graph_id")
        if not graph_id:
            raise ValueError("UpdateWorkflowGraph requires a current graph")
        result = runtime.project_store.save_graph(project_id, str(graph_id), graph)
        loop_state["graph_id"] = str(graph_id)
        loop_state["changed"] = True
        loop_state["opened_canvas"] = True
        loop_state["diffs"].append({"tool": tool_name, "summary": arguments.get("reason"), "diff": result.get("diff")})
        return _graph_save_result_for_model(result)

    if tool_name == "AssignFileToNode":
        if not graph_id:
            raise ValueError("AssignFileToNode requires a current graph")
        node_id = str(arguments.get("node_id") or "")
        if not node_id:
            raise ValueError("AssignFileToNode requires node_id")
        file_id = _resolve_file_id(runtime, project_id, arguments)
        result = runtime.project_store.move_file(
            project_id,
            file_id,
            NODE_FILES,
            graph_id=str(graph_id),
            node_id=node_id,
        )
        loop_state["graph_id"] = str(graph_id)
        loop_state["changed"] = True
        loop_state["opened_canvas"] = True
        assignment = {
            "file_id": file_id,
            "file_name": result.get("file", {}).get("name"),
            "node_id": node_id,
            "reason": arguments.get("reason"),
        }
        loop_state["file_assignments"].append(assignment)
        loop_state["diffs"].append({"tool": tool_name, "summary": f"文件 {assignment['file_name']} -> 节点 {node_id}"})
        return {
            "status": "success",
            "assignment": assignment,
            "node": _node_summary(runtime.project_store.read_graph(project_id, str(graph_id)), node_id),
            "snapshot_summary": _workspace_snapshot(runtime, project_id, str(graph_id)),
        }

    if tool_name == "RunGraph":
        if not graph_id:
            raise ValueError("RunGraph requires a current graph")
        result = runtime._run_graph(  # noqa: SLF001
            {**record, "project_id": project_id, "graph_id": str(graph_id)},
            {**payload, "project_id": project_id, "graph_id": str(graph_id), "disable_recovery": True},
        )
        loop_state["graph_id"] = str(graph_id)
        loop_state["last_run"] = result.get("run")
        loop_state["opened_canvas"] = True
        loop_state["diffs"].append({"tool": tool_name, "summary": f"运行图：{(result.get('run') or {}).get('status')}"})
        return _run_result_for_model(result)

    if tool_name == "RunNode":
        if not graph_id:
            raise ValueError("RunNode requires a current graph")
        node_id = str(arguments.get("node_id") or "")
        if not node_id:
            raise ValueError("RunNode requires node_id")
        result = runtime._run_node(  # noqa: SLF001
            {**record, "project_id": project_id, "graph_id": str(graph_id), "node_id": node_id},
            {**payload, "project_id": project_id, "graph_id": str(graph_id), "node_id": node_id, "disable_recovery": True},
        )
        loop_state["graph_id"] = str(graph_id)
        loop_state["last_run"] = result.get("run")
        loop_state["opened_canvas"] = True
        loop_state["diffs"].append({"tool": tool_name, "summary": f"运行节点 {node_id}：{(result.get('run') or {}).get('status')}"})
        return _run_result_for_model(result)

    if tool_name == "SaveWorkflow":
        if not graph_id:
            raise ValueError("SaveWorkflow requires a current graph")
        from ..graph_saver import save_workflow_version

        graph = runtime.project_store.read_graph(project_id, str(graph_id))
        result = save_workflow_version(
            runtime.project_store,
            project_id,
            str(graph_id),
            graph=graph,
            note=str(arguments.get("note") or "agent tool loop save")[:500],
            source="agent_tool_loop",
        )
        loop_state["diffs"].append({"tool": tool_name, "summary": f"保存版本：{result.get('version', {}).get('version_id')}"})
        return {"status": "success", "version": result.get("version")}

    if tool_name == "OpenCanvas":
        if not graph_id:
            raise ValueError("OpenCanvas requires a current graph")
        loop_state["graph_id"] = str(graph_id)
        loop_state["opened_canvas"] = True
        return {"status": "success", "graph": _graph_summary(runtime.project_store.read_graph(project_id, str(graph_id)))}

    raise ValueError(f"unknown agent loop tool: {tool_name}")


def _system_prompt() -> str:
    return (
        "你是 GraphyAgent 的 agent runtime。你必须用工具处理会改变 project/graph/node/file/run 状态的请求。"
        "你正在使用 Anthropic 风格协议：assistant 输出 tool_use，runtime 执行后以 user/tool_result 返回观察结果，然后你继续判断下一步。\n\n"
        "核心策略：\n"
        "1. 普通解释或记忆问答可以直接最终回答；不要为了闲聊调用工具。\n"
        "2. 用户要求规划/创建/重建 workflow 时，先 InspectWorkspace；如果存在未分类文件，必须读取相关文件或表格，数据文件先 AuditDataset，再 DecomposeTaskToGraph。\n"
        "3. DecomposeTaskToGraph 后，如果输入文件应属于某个节点，必须调用 AssignFileToNode，把文件移动到最合适的节点，让 node.inputs 和 initial_artifacts 同步出现。\n"
        "4. 如果用户要求执行、运行、产出结果或验证可运行，先确认文件已分配到节点，再 RunGraph；运行失败时根据 tool_result 思考是否 UpdateWorkflowGraph 或重新分配文件，再决定是否重跑。\n"
        "5. 不要假装读过文件、生成过结果或保存过工作流；没有工具结果就不能声称状态已改变。\n"
        "6. 图结构调整必须通过 DecomposeTaskToGraph 或 UpdateWorkflowGraph；文件移动必须通过 AssignFileToNode。\n"
        "7. 需要动作时必须发出 tool_use，不要把动作写成可解析文本或自定义动作伪协议。\n"
        "8. 最终回答必须是中文，明确列出：图是否变更、文件分配、运行状态、关键输出或失败原因。"
    )


def _initial_user_message(
    runtime: Any,
    project_id: str,
    graph_id: str | None,
    memory_target: dict[str, str],
    prompt: str,
) -> str:
    context = runtime.target_context(project_id, graph_id, memory_target.get("id") if memory_target.get("type") == "node" else None)
    workspace = _workspace_snapshot(runtime, project_id, graph_id)
    return (
        "## 用户输入\n"
        f"{prompt}\n\n"
        "## 对话目标\n"
        f"{json.dumps(memory_target, ensure_ascii=False, indent=2)}\n\n"
        "## 当前 runtime 上下文摘要\n"
        f"{json.dumps(_compact_for_trace(context), ensure_ascii=False, indent=2)}\n\n"
        "## 当前文件/图摘要\n"
        f"{json.dumps(workspace, ensure_ascii=False, indent=2)}"
    )


def _workspace_snapshot(runtime: Any, project_id: str, graph_id: str | None) -> dict[str, Any]:
    project = runtime.project_store.read_project(project_id)
    graph = runtime.project_store.read_graph(project_id, graph_id) if graph_id else None
    tree = runtime.project_store.virtual_tree()
    files = _flatten_tree_files(tree)
    return {
        "project": {
            "project_id": project.get("project_id"),
            "name": project.get("name"),
            "current_graph_id": project.get("current_graph_id"),
            "graph_count": len(project.get("graphs") or []),
        },
        "graph": _graph_summary(graph) if graph else None,
        "files": files[:80],
        "data_audit_candidates": [
            {
                "file_id": item.get("file_id"),
                "name": item.get("name"),
                "storage_path": item.get("storage_path"),
                "scope": item.get("scope"),
                "node_id": item.get("node_id"),
            }
            for item in files
            if Path(str(item.get("name") or "")).suffix.lower() in {".csv", ".json", ".jsonl"}
        ][:30],
    }


def _flatten_tree_files(tree: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for folder in tree.get("folders") or []:
        if folder.get("id") == "nodes":
            for child in folder.get("children") or []:
                for file_record in child.get("files") or []:
                    item = _file_summary(file_record)
                    item.update({
                        "scope": NODE_FILES,
                        "graph_id": child.get("graph_id"),
                        "node_id": child.get("node_id"),
                    })
                    files.append(item)
            continue
        scope = folder.get("scope")
        for file_record in folder.get("files") or []:
            item = _file_summary(file_record)
            item.update({
                "scope": scope,
                "graph_id": folder.get("graph_id"),
                "node_id": folder.get("node_id"),
            })
            files.append(item)
    return files


def _file_summary(file_record: dict[str, Any]) -> dict[str, Any]:
    analysis = file_record.get("analysis") if isinstance(file_record.get("analysis"), dict) else {}
    return {
        "file_id": file_record.get("file_id"),
        "name": file_record.get("name"),
        "storage_path": file_record.get("storage_path"),
        "source_path": file_record.get("source_path"),
        "size": file_record.get("size"),
        "sha256": file_record.get("sha256"),
        "analysis": {
            "summary": analysis.get("summary"),
            "extension": analysis.get("extension"),
            "suggested_role": analysis.get("suggested_role"),
            "audit": analysis.get("audit"),
        },
    }


def _graph_summary(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not graph:
        return None
    meta = graph.get("metadata", {}).get("graphyagent", {})
    files = meta.get("files") if isinstance(meta.get("files"), dict) else {}
    return {
        "graph_id": graph.get("graph_id"),
        "name": meta.get("name") or graph.get("graph_id"),
        "node_count": len(graph.get("nodes") or []),
        "output_nodes": graph.get("output_nodes") or [],
        "nodes": [_node_summary(graph, str(node.get("id") or "")) for node in (graph.get("nodes") or [])[:30]],
        "graph_unclassified_files": [_file_summary(item) for item in (files.get("unclassified") or [])[:30]],
        "node_file_counts": {
            str(node_id): len(items or [])
            for node_id, items in (files.get("nodes") or {}).items()
        },
        "latest_run": meta.get("latest_run"),
    }


def _node_summary(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    node = next((item for item in graph.get("nodes") or [] if str(item.get("id")) == node_id), None)
    if not node:
        return {"node_id": node_id, "missing": True}
    meta = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    node_files = (
        graph.get("metadata", {})
        .get("graphyagent", {})
        .get("files", {})
        .get("nodes", {})
        .get(node_id, [])
    )
    return {
        "node_id": node_id,
        "task_type": node.get("task_type"),
        "description": meta.get("description"),
        "depends_on": node.get("depends_on") or [],
        "inputs": node.get("inputs") or {},
        "output_roles": node.get("output_roles") or {},
        "executor_type": (node.get("executor") or {}).get("type"),
        "files": [_file_summary(item) for item in node_files[:20]],
    }


def _decompose_prompt_with_context(runtime: Any, project_id: str, graph_id: str | None, tool_prompt: str) -> str:
    workspace = _workspace_snapshot(runtime, project_id, graph_id)
    return (
        f"{tool_prompt}\n\n"
        "请基于以下已检查到的项目文件和当前图状态规划 workflow。"
        "如果某些文件需要作为节点输入，请在图生成后通过 AssignFileToNode 绑定到对应节点；"
        "本次 task_decompose 只负责生成/调整图结构，不要声称已经移动文件。\n\n"
        "当前工作区摘要：\n"
        f"{json.dumps(workspace, ensure_ascii=False, indent=2)}"
    )


def _decompose_result_for_model(result: dict[str, Any]) -> dict[str, Any]:
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else None
    return {
        "status": "success",
        "message": result.get("message"),
        "created": result.get("created"),
        "graph": _graph_summary(graph),
        "diff": result.get("diff"),
        "decomposition": result.get("decomposition"),
    }


def _graph_save_result_for_model(result: dict[str, Any]) -> dict[str, Any]:
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else None
    return {
        "status": "success",
        "graph": _graph_summary(graph),
        "diff": result.get("diff"),
        "ai_suggestions": result.get("ai_suggestions"),
    }


def _run_result_for_model(result: dict[str, Any]) -> dict[str, Any]:
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    return {
        "status": "success",
        "run": _compact_run(run),
        "recovery": result.get("recovery"),
        "graph": _graph_summary(result.get("graph")) if isinstance(result.get("graph"), dict) else None,
    }


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    final_state = run.get("final_state") if isinstance(run.get("final_state"), dict) else {}
    node_results = final_state.get("node_results") if isinstance(final_state.get("node_results"), dict) else {}
    return {
        "graph_run_id": run.get("graph_run_id"),
        "graph_id": run.get("graph_id"),
        "status": run.get("status"),
        "error": _clip(str(run.get("error") or ""), 3000) if run.get("error") else None,
        "output_dir": run.get("output_dir"),
        "node_runs": run.get("node_runs"),
        "node_results": {
            node_id: {
                "status": (result or {}).get("status"),
                "outputs": (result or {}).get("outputs"),
                "node_run_id": (result or {}).get("node_run_id"),
                "error": _clip(str((result or {}).get("error") or ""), 1200) if (result or {}).get("error") else None,
            }
            for node_id, result in node_results.items()
        },
    }


def _compact_audit_result(result: dict[str, Any]) -> dict[str, Any]:
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    return {
        "verdict": report.get("verdict"),
        "dataset_metrics": report.get("dataset_metrics"),
        "tag_summary": report.get("tag_summary"),
        "issues": (report.get("issues") or [])[:20],
    }


def _final_result(
    runtime: Any,
    project_id: str,
    loop_state: dict[str, Any],
    *,
    final_text: str,
    trace: list[dict[str, Any]],
    completion: dict[str, Any],
) -> dict[str, Any]:
    graph_id = loop_state.get("graph_id")
    graph = None
    if graph_id:
        try:
            graph = runtime.project_store.read_graph(project_id, str(graph_id))
        except FileNotFoundError:
            graph = None
    diff = _aggregate_diff(loop_state)
    message = final_text.strip() or _fallback_final_message(loop_state)
    result: dict[str, Any] = {
        "message": message,
        "open_canvas": bool(loop_state.get("opened_canvas") or graph),
        "graph": graph,
        "diff": diff,
        "agent_context": runtime.target_context(project_id, str(graph_id) if graph_id else None),
        "snapshot": runtime.project_store.snapshot(),
        "agent_loop": {
            "protocol": "anthropic_tools",
            "content_blocks": ["text", "tool_use", "tool_result"],
            "steps": trace,
            "model": completion.get("model"),
            "profile": completion.get("profile"),
            "api_format": completion.get("api_format"),
            "finished_at": utc_now(),
        },
        "routed_module_command": {
            "module": "agent_runtime",
            "command": "chat_graph_tool_loop",
            "reason": "provider_native_tool_loop",
        },
    }
    if loop_state.get("last_run"):
        result["run"] = loop_state["last_run"]
    return result


def _aggregate_diff(loop_state: dict[str, Any]) -> dict[str, Any]:
    diffs = loop_state.get("diffs") if isinstance(loop_state.get("diffs"), list) else []
    assignments = loop_state.get("file_assignments") if isinstance(loop_state.get("file_assignments"), list) else []
    if not diffs and not assignments:
        return {"summary": "图无变化。"}
    pieces = []
    for item in diffs:
        if isinstance(item, dict) and item.get("summary"):
            pieces.append(str(item["summary"]))
    if assignments:
        pieces.append(
            "文件分配：" + "，".join(
                f"{item.get('file_name') or item.get('file_id')} -> {item.get('node_id')}"
                for item in assignments
                if isinstance(item, dict)
            )
        )
    return {
        "summary": "；".join(pieces)[:1000] if pieces else "图已更新。",
        "steps": diffs,
        "file_assignments": assignments,
    }


def _fallback_final_message(loop_state: dict[str, Any]) -> str:
    run = loop_state.get("last_run") if isinstance(loop_state.get("last_run"), dict) else None
    parts = []
    if loop_state.get("changed"):
        parts.append("已根据工具循环更新当前工作流。")
    if loop_state.get("file_assignments"):
        parts.append("已把相关文件分配到节点输入。")
    if run:
        parts.append(f"运行状态：{run.get('status') or 'unknown'}。")
    return "\n".join(parts) or "已完成对话处理，当前图无变化。"


def _resolve_file_id(runtime: Any, project_id: str, arguments: dict[str, Any]) -> str:
    file_id = str(arguments.get("file_id") or "").strip()
    file_name = str(arguments.get("file_name") or arguments.get("name") or "").strip()
    tree = runtime.project_store.virtual_tree()
    files = _flatten_tree_files(tree)
    if file_id and any(str(item.get("file_id")) == file_id for item in files):
        return file_id
    for item in files:
        if file_id and file_id in {str(item.get("file_id")), str(item.get("name")), str(item.get("storage_path"))}:
            return str(item.get("file_id"))
        if file_name and file_name in {str(item.get("name")), Path(str(item.get("storage_path") or "")).name}:
            return str(item.get("file_id"))
    raise FileNotFoundError(f"file not found for assignment: {file_id or file_name}")


def _file_path_from_id_or_name(runtime: Any, project_id: str, arguments: dict[str, Any]) -> str:
    file_id = str(arguments.get("file_id") or "").strip()
    file_name = str(arguments.get("file_name") or arguments.get("name") or "").strip()
    files = _flatten_tree_files(runtime.project_store.virtual_tree())
    for item in files:
        if file_id and file_id in {str(item.get("file_id")), str(item.get("name")), str(item.get("storage_path"))}:
            return str(item.get("storage_path") or "")
        if file_name and file_name in {str(item.get("name")), Path(str(item.get("storage_path") or "")).name}:
            return str(item.get("storage_path") or "")
    raise FileNotFoundError(f"file not found for reading: {file_id or file_name}")


def _agent_tool_call_trace(
    tool_use_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    loop_state: dict[str, Any],
    *,
    is_error: bool,
) -> dict[str, Any]:
    binding = _tool_node_binding(tool_name, arguments, result, loop_state)
    return {
        "schema": "graphyagent.agent_tool_call.v1",
        "trace_type": "agent_tool_call",
        "protocol": "anthropic_tools",
        "control_axis": "global_react_tool_loop",
        "tool_use_id": tool_use_id,
        "id": tool_use_id,
        "name": tool_name,
        "semantic_role": _tool_semantic_role(tool_name),
        "status": "error" if is_error else str(result.get("status") or "success"),
        "input": _compact_for_trace(arguments),
        "result": _compact_for_trace(result),
        "error": result.get("error") if is_error else None,
        "node_binding": binding,
        "online_reflection": _tool_reflection_policy(binding),
        "created_at": utc_now(),
    }


def _tool_node_binding(
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    loop_state: dict[str, Any],
) -> dict[str, Any]:
    project_id = str(loop_state.get("project_id") or "")
    graph_id = str(arguments.get("graph_id") or loop_state.get("graph_id") or "")
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    if tool_name == "RunNode":
        node_id = str(arguments.get("node_id") or run.get("node_id") or "")
        node_runs = _node_run_bindings(run, fallback_node_id=node_id)
        return {
            "binding_type": "workflow_node_run",
            "project_id": project_id,
            "graph_id": graph_id or run.get("graph_id"),
            "node_id": node_id,
            "graph_run_id": run.get("graph_run_id"),
            "node_runs": node_runs,
            "reflection_owner": "graph_runner",
            "reflection_policy": "graph_runner_managed",
            "credit_assignment": "node_run",
        }
    if tool_name == "RunGraph":
        node_runs = _node_run_bindings(run)
        return {
            "binding_type": "workflow_graph_run",
            "project_id": project_id,
            "graph_id": graph_id or run.get("graph_id"),
            "graph_run_id": run.get("graph_run_id"),
            "node_runs": node_runs,
            "reflection_owner": "graph_runner",
            "reflection_policy": "graph_runner_managed",
            "credit_assignment": "graph_run_node_runs",
        }
    if tool_name in {"DecomposeTaskToGraph", "UpdateWorkflowGraph", "SaveWorkflow"}:
        return {
            "binding_type": "workflow_structure",
            "project_id": project_id,
            "graph_id": graph_id or loop_state.get("graph_id"),
            "reflection_policy": "offline_optimizer_only",
            "credit_assignment": "structure_change_trace",
        }
    if tool_name == "AssignFileToNode":
        return {
            "binding_type": "workflow_node_artifact_binding",
            "project_id": project_id,
            "graph_id": graph_id,
            "node_id": str(arguments.get("node_id") or ""),
            "reflection_policy": "not_a_node_execution",
            "credit_assignment": "artifact_binding_trace",
        }
    return {
        "binding_type": "control_observation",
        "project_id": project_id,
        "graph_id": graph_id or None,
        "reflection_policy": "not_applicable",
        "credit_assignment": "agent_control_trace",
    }


def _node_run_bindings(run: dict[str, Any], *, fallback_node_id: str = "") -> list[dict[str, Any]]:
    final_state = run.get("final_state") if isinstance(run.get("final_state"), dict) else {}
    node_results = final_state.get("node_results") if isinstance(final_state.get("node_results"), dict) else {}
    bindings = []
    for node_id, node_result in sorted(node_results.items()):
        if not isinstance(node_result, dict):
            continue
        node_run_id = node_result.get("node_run_id")
        if node_run_id:
            bindings.append({
                "node_id": str(node_id),
                "node_run_id": str(node_run_id),
                "status": node_result.get("status"),
            })
    if not bindings and fallback_node_id:
        for node_run_id in run.get("node_runs") or []:
            bindings.append({
                "node_id": fallback_node_id,
                "node_run_id": str(node_run_id),
                "status": run.get("status"),
            })
    return bindings


def _tool_reflection_policy(binding: dict[str, Any]) -> dict[str, Any]:
    policy = str(binding.get("reflection_policy") or "not_applicable")
    if policy == "graph_runner_managed":
        return {
            "triggered": True,
            "owner": "graph_runner",
            "scope": binding.get("binding_type"),
            "note": "NodeRun online reflection and weight updates are handled inside GraphExecutor.",
        }
    return {
        "triggered": False,
        "owner": None,
        "scope": binding.get("binding_type"),
        "note": policy,
    }


def _tool_semantic_role(tool_name: str) -> str:
    roles = {
        "InspectWorkspace": "control_context",
        "ReadFile": "control_context",
        "ReadTable": "control_context",
        "AuditDataset": "preflight_knowledge",
        "DecomposeTaskToGraph": "workflow_structure",
        "UpdateWorkflowGraph": "workflow_structure",
        "AssignFileToNode": "artifact_binding",
        "RunGraph": "workflow_execution",
        "RunNode": "workflow_execution",
        "SaveWorkflow": "workflow_versioning",
        "OpenCanvas": "ui_state",
    }
    return roles.get(tool_name, "control")


def _tool_result_content(result: dict[str, Any]) -> str:
    return _clip(json.dumps(_compact_for_trace(result), ensure_ascii=False, default=str), MAX_TOOL_RESULT_CHARS)


def _compact_for_trace(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return _clip(str(value), 1000)
    if isinstance(value, dict):
        if "graph" in value and isinstance(value.get("graph"), dict):
            value = {**value, "graph": _graph_summary(value["graph"])}
        if "snapshot" in value:
            value = {key: val for key, val in value.items() if key != "snapshot"}
        if "raw" in value:
            value = {key: val for key, val in value.items() if key != "raw"}
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"content", "text"} and isinstance(item, str):
                compact[key] = _clip(item, 8000)
            else:
                compact[key] = _compact_for_trace(item, depth=depth + 1)
        return compact
    if isinstance(value, list):
        items = value[:80]
        compacted = [_compact_for_trace(item, depth=depth + 1) for item in items]
        if len(value) > len(items):
            compacted.append({"truncated_count": len(value) - len(items)})
        return compacted
    if isinstance(value, str):
        return _clip(value, 8000)
    return value


def _clip(text: str, max_chars: int) -> str:
    value = str(text or "")
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 120)] + f"\n...[truncated {len(value) - max_chars + 120} chars]"


def _parse_memory_prompt(prompt: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^【(?P<label>项目|图|节点|文件)记忆：(?P<name>[^】]+)】\s*(?P<body>.*)$", str(prompt or ""), re.S)
    if not match:
        return {"type": "project", "name": "项目"}, str(prompt or "").strip()
    label = match.group("label")
    target_type = {
        "项目": "project",
        "图": "graph",
        "节点": "node",
        "文件": "file",
    }.get(label, "project")
    name = match.group("name").strip()
    return {"type": target_type, "id": name, "name": name}, match.group("body").strip()


def _positive_int_env(name: str, *, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default
