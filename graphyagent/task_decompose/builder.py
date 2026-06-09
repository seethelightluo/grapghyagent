"""Workflow graph construction for task_decompose."""
from __future__ import annotations

import json
import re
import ast
from copy import deepcopy
from typing import Any

from ..agent_runtime.context_budget import resolve_max_tokens
from ..model_routing.llm_client import LLMCallError, chat_completion


def build_workflow_graph(graph: dict[str, Any], prompt: str) -> dict[str, Any]:
    new_graph = _strip_graph_view(deepcopy(graph))
    llm_graph = _build_llm_workflow_graph(new_graph, prompt)
    if llm_graph:
        return llm_graph
    raise ValueError(
        "LLM workflow decomposition failed; refusing to use legacy template fallback. "
        "Check .env model/API settings or retry with a clearer workflow request."
    )


def _build_llm_workflow_graph(graph: dict[str, Any], prompt: str) -> dict[str, Any] | None:
    system = (
        "你是 GraphyAgent 的 task_decompose 模块。"
        "你的任务是把用户的自然语言 workflow 描述拆成可执行 DAG。"
        "必须根据用户输入本身推理节点、依赖、并行关系和模型复杂度，不能套用固定领域样例。"
    )
    user_prompt = (
        "请只输出一个 JSON 对象，不要 Markdown、不要解释。\n"
        "JSON schema:\n"
        "{\n"
        '  "name": "图名称",\n'
        '  "nodes": [\n'
        '    {"id": "中文短节点名", "task_type": "planning|ingestion|extraction|classification|validation|reasoning|writing|review|integration|analysis|reporting|audit|task", "description": "节点要完成的具体任务", "depends_on": ["上游节点id"], "complexity": "simple|complex", "executor": {"type": "llm|python|audit|noop", "code": "可选 Python 代码字符串", "output": "llm_result.md", "dataset_input": "dataset", "metadata_input": "metadata"}, "inputs": {"本节点输入文件名": "上游节点id:上游输出文件名 或 dataset/metadata 等初始文件别名"}, "output_roles": {"本节点输出文件名": "输出角色"}, "gate_condition": "可选，说明输出验收条件"}\n'
        "  ],\n"
        '  "output_nodes": ["最终输出节点id"]\n'
        "}\n"
        "约束：\n"
        "- 生成 5 到 14 个节点，节点名应短、清楚、可放进画布。\n"
        "- depends_on 只能引用 nodes 里已经存在的 id；不要引用自身。\n"
        "- 能并行的节点不要强行串行；有先后证据依赖的节点必须连边。\n"
        "- 如果用户明确说某些步骤可以并行，这些步骤应共享最早有效上游；除非一个步骤真实消费另一个步骤的输出，否则不要让它们彼此依赖。\n"
        "- 每个 description 要说明输入、处理和输出，不要只复述节点名。\n"
        "- 需要长上下文、推理、策略判断、代码或跨证据合并的节点标 complex；简单抽取、清洗、格式化标 simple。\n\n"
        "可执行性要求：\n"
        "- 如果用户要求“可运行”“生成文件”“清洗/整合数据”“渲染报告/预览”，不能只生成 LLM 文本节点；相应节点应使用 executor.type=python 写出真实文件。\n"
        "- Python executor 只能使用标准库，读取 os.environ['GRAPHYAGENT_INPUTS']，写入 os.environ['GRAPHYAGENT_OUTPUTS']；不得访问网络、启动子进程或写输出目录外的路径。\n"
        "- Python 节点必须声明 output_roles，并让下游 inputs 使用 `上游节点id:输出文件名` 引用真实文件。\n"
        "- 数据质量审计、synthetic/data_audit、CSV/JSON/JSONL 数据审计节点应优先使用 executor.type=audit，inputs 使用 dataset/metadata 初始别名，output_roles 至少包含 audit_report.json、audit_report.md、record_tags.jsonl、evidence.jsonl。\n"
        "- 初始文件别名（例如 dataset、metadata、node_file_xxx）是全图可用输入，不要把原始输入文件伪装成 `上游节点:原始文件名`；只有当上游节点真实声明该 output_roles 时，才能用 `上游节点:输出文件名`。\n"
        "- 如果用户要求生成小规模样例数据，可以由采集节点用 Python 生成样例 CSV/JSON；不要在 task_decompose 里套固定领域模板，代码必须服务于本次用户请求。\n"
        "- LLM 节点可以用于解释、判断或撰写，但不能声称生成了文件；凡需要文件落盘，必须用 python executor。\n\n"
        f"用户 workflow 描述：\n{prompt}"
    )
    try:
        completion = chat_completion(
            user_prompt,
            profile="complex",
            system=system,
            max_tokens=resolve_max_tokens(profile="complex", default=12000, prompt=user_prompt),
            temperature=0.1,
            timeout_seconds=150,
        )
    except LLMCallError as exc:
        raise ValueError(f"LLM workflow decomposition call failed: {exc}") from exc

    try:
        response_text = str(completion.get("text") or "")
        spec = _parse_llm_workflow_json(response_text)
        return _graph_from_llm_workflow_spec(graph, prompt, spec, completion)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        preview = str(completion.get("text") or "")[:1200]
        raise ValueError(f"LLM workflow decomposition returned invalid spec: {exc}; response={preview}") from exc


def _parse_llm_workflow_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM workflow response did not contain a JSON object")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM workflow response must be a JSON object")
    return data


def _graph_from_llm_workflow_spec(
    graph: dict[str, Any],
    prompt: str,
    spec: dict[str, Any],
    completion: dict[str, Any],
) -> dict[str, Any]:
    raw_nodes = spec.get("nodes")
    if not isinstance(raw_nodes, list) or len(raw_nodes) < 2:
        raise ValueError("LLM workflow graph requires at least two nodes")

    seen: set[str] = set()
    id_map: dict[str, str] = {}
    pending_deps: dict[str, list[str]] = {}
    pending_inputs: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for index, raw_node in enumerate(raw_nodes[:14]):
        if not isinstance(raw_node, dict):
            continue
        raw_id = _clean_llm_node_text(raw_node.get("id") or raw_node.get("name"), f"步骤{index + 1}", 34)
        node_id = _unique_llm_node_id(raw_id, seen)
        task_type = _clean_llm_node_text(raw_node.get("task_type"), "task", 24)
        description = _clean_llm_node_text(raw_node.get("description"), f"{node_id} 的执行任务。", 260)
        complexity = str(raw_node.get("complexity") or "").strip().lower()
        if complexity not in {"simple", "complex"}:
            complexity = "complex" if task_type in {"reasoning", "analysis", "planning"} else "simple"
        node = _workflow_node(node_id, task_type, description)
        executor = _llm_node_executor(raw_node, node_id, task_type, description)
        if executor:
            node["executor"] = executor
        output_roles = _llm_node_output_roles(raw_node, node["executor"])
        if output_roles:
            node["output_roles"] = output_roles
        gate_condition = _clean_llm_node_text(raw_node.get("gate_condition"), "", 220)
        if gate_condition:
            node["gate_condition"] = gate_condition
        node["routing"] = {"complexity": complexity}
        nodes.append(node)
        seen.add(node_id)
        id_map[str(raw_node.get("id") or raw_node.get("name") or raw_id).strip()] = node_id
        raw_deps = raw_node.get("depends_on") or raw_node.get("dependencies") or []
        pending_deps[node_id] = [str(dep).strip() for dep in raw_deps if str(dep).strip()] if isinstance(raw_deps, list) else []
        raw_inputs = raw_node.get("inputs")
        pending_inputs[node_id] = dict(raw_inputs) if isinstance(raw_inputs, dict) else {}

    if len(nodes) < 2:
        raise ValueError("LLM workflow graph did not yield enough valid nodes")

    valid_ids = {node["id"] for node in nodes}
    for node in nodes:
        deps: list[str] = []
        for dep in pending_deps.get(node["id"], []):
            dep_id = id_map.get(dep, dep)
            if dep_id in valid_ids and dep_id != node["id"] and dep_id not in deps:
                deps.append(dep_id)
        node["depends_on"] = deps
        inputs = _llm_node_inputs(pending_inputs.get(node["id"]) or {}, id_map, valid_ids)
        if inputs:
            node["inputs"] = inputs

    requested_outputs = spec.get("output_nodes") if isinstance(spec.get("output_nodes"), list) else []
    output_nodes = []
    for output in requested_outputs:
        output_id = id_map.get(str(output).strip(), str(output).strip())
        if output_id in valid_ids and output_id not in output_nodes:
            output_nodes.append(output_id)
    if not output_nodes:
        depended_on = {dep for node in nodes for dep in (node.get("depends_on") or [])}
        output_nodes = [node["id"] for node in nodes if node["id"] not in depended_on] or [nodes[-1]["id"]]

    new_graph = _strip_graph_view(deepcopy(graph))
    new_graph["nodes"] = nodes
    new_graph["output_nodes"] = output_nodes
    context = new_graph.setdefault("context", {})
    context["latest_workflow_prompt"] = prompt
    context["workflow_domain"] = "llm_decomposed_workflow"
    meta = new_graph.setdefault("metadata", {}).setdefault("graphyagent", {})
    meta["layout"] = {}
    meta["decomposition"] = {
        "source": "llm",
        "profile": completion.get("profile"),
        "model": completion.get("model"),
    }
    if spec.get("name") and not meta.get("name"):
        meta["name"] = _clean_llm_node_text(spec.get("name"), "Decomposed Task", 80)
    return new_graph


def _workflow_node(node_id: str, task_type: str, description: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "task_type": task_type,
        "executor": {
            "type": "llm",
            "output": "llm_result.md",
            "include_state": True,
            "input_char_limit": 60000,
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


def _llm_node_executor(
    raw_node: dict[str, Any],
    node_id: str,
    task_type: str,
    description: str,
) -> dict[str, Any] | None:
    raw_executor = raw_node.get("executor")
    if not isinstance(raw_executor, dict):
        return None
    executor_type = str(raw_executor.get("type") or "").strip().lower()
    if executor_type == "python":
        code = _clean_code_fence(str(raw_executor.get("code") or ""))
        if not code.strip():
            raise ValueError(f"LLM python executor for node {node_id} is missing code")
        code = _validate_llm_python_code(code, node_id)
        executor: dict[str, Any] = {
            "type": "python",
            "code": code,
            "timeout_seconds": _bounded_int(raw_executor.get("timeout_seconds"), default=120, minimum=5, maximum=600),
        }
        return executor
    if executor_type == "llm":
        output = _safe_relative_filename(str(raw_executor.get("output") or "llm_result.md"), default="llm_result.md")
        return {
            "type": "llm",
            "output": output,
            "include_state": bool(raw_executor.get("include_state", True)),
            "input_char_limit": _bounded_int(raw_executor.get("input_char_limit"), default=60000, minimum=1000, maximum=200000),
            "prompt": str(raw_executor.get("prompt") or _workflow_node(node_id, task_type, description)["executor"]["prompt"]),
            **({"profile": str(raw_executor.get("profile"))} if raw_executor.get("profile") else {}),
        }
    if executor_type == "audit":
        dataset_input = _safe_relative_filename(str(raw_executor.get("dataset_input") or "dataset"), default="dataset")
        metadata_input = _safe_relative_filename(str(raw_executor.get("metadata_input") or "metadata"), default="metadata")
        return {
            "type": "audit",
            "dataset_input": dataset_input,
            "metadata_input": metadata_input,
        }
    if executor_type == "noop":
        return {"type": "noop"}
    if executor_type:
        raise ValueError(f"unsupported LLM-proposed executor type for node {node_id}: {executor_type}")
    return None


def _llm_node_output_roles(raw_node: dict[str, Any], executor: dict[str, Any]) -> dict[str, str]:
    raw_roles = raw_node.get("output_roles") or raw_node.get("outputs")
    roles: dict[str, str] = {}
    if isinstance(raw_roles, dict):
        for raw_name, raw_role in raw_roles.items():
            name = _safe_relative_filename(str(raw_name), default="")
            if not name:
                continue
            role = _clean_llm_node_text(raw_role, "output", 40)
            roles[name] = role
    if roles:
        return roles
    if str(executor.get("type") or "").lower() == "audit":
        return {
            "audit_report.json": "audit_report",
            "audit_report.md": "audit_report",
            "record_tags.jsonl": "record_tags",
            "evidence.jsonl": "audit_evidence",
            "review_queue.jsonl": "review_queue",
            "quality_dimensions.json": "quality_dimensions",
            "risk_assessment.json": "risk_assessment",
            "detector_applicability.json": "detector_applicability",
            "llm_summary_input.json": "audit_summary_input",
        }
    if str(executor.get("type") or "").lower() == "llm":
        output = _safe_relative_filename(str(executor.get("output") or "llm_result.md"), default="llm_result.md")
        return {output: "节点结果", "llm_call.json": "llm_call"}
    return {}


def _llm_node_inputs(
    raw_inputs: dict[str, Any],
    id_map: dict[str, str],
    valid_ids: set[str],
) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for raw_name, raw_ref in raw_inputs.items():
        name = _safe_relative_filename(str(raw_name), default="")
        if not name:
            continue
        inputs[name] = _normalize_llm_input_reference(raw_ref, id_map, valid_ids)
    return inputs


def _normalize_llm_input_reference(
    raw_ref: Any,
    id_map: dict[str, str],
    valid_ids: set[str],
) -> Any:
    if isinstance(raw_ref, dict):
        ref = dict(raw_ref)
        if "from" in ref:
            ref["from"] = _normalize_llm_input_reference(ref["from"], id_map, valid_ids)
        if "artifact" in ref:
            ref["artifact"] = _normalize_llm_input_reference(ref["artifact"], id_map, valid_ids)
        if "alias" in ref:
            ref["alias"] = str(ref["alias"])
        return ref
    ref = str(raw_ref or "").strip()
    if ":" not in ref:
        return ref
    raw_node_id, output_name = ref.split(":", 1)
    node_id = id_map.get(raw_node_id.strip(), raw_node_id.strip())
    if node_id in valid_ids:
        return f"{node_id}:{output_name.strip()}"
    return ref


def _clean_code_fence(code: str) -> str:
    cleaned = code.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:python)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _validate_llm_python_code(code: str, node_id: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"LLM python executor for node {node_id} has invalid syntax: {exc}") from exc
    banned_import_roots = {
        "subprocess",
        "socket",
        "urllib",
        "http",
        "ftplib",
        "requests",
        "multiprocessing",
        "threading",
        "asyncio",
        "webbrowser",
    }
    banned_calls = {"eval", "exec", "compile", "__import__", "input"}
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            for alias in item.names:
                root = alias.name.split(".", 1)[0]
                if root in banned_import_roots:
                    raise ValueError(f"node {node_id}: banned python import `{alias.name}`")
        elif isinstance(item, ast.ImportFrom):
            root = (item.module or "").split(".", 1)[0]
            if root in banned_import_roots:
                raise ValueError(f"node {node_id}: banned python import `{item.module}`")
        elif isinstance(item, ast.Call):
            if isinstance(item.func, ast.Name) and item.func.id in banned_calls:
                raise ValueError(f"node {node_id}: banned python call `{item.func.id}`")
            if (
                isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id == "os"
                and item.func.attr in {"system", "popen", "spawnl", "spawnlp", "spawnv", "spawnvp"}
            ):
                raise ValueError(f"node {node_id}: banned python call `os.{item.func.attr}`")
    if "GRAPHYAGENT_OUTPUTS" not in code:
        raise ValueError(f"node {node_id}: python executor must write under GRAPHYAGENT_OUTPUTS")
    return code


def _safe_relative_filename(value: str, *, default: str) -> str:
    clean = str(value or "").replace("\\", "/").strip().strip("/")
    if not clean:
        return default
    parts = [part for part in clean.split("/") if part not in {"", ".", ".."}]
    if not parts:
        return default
    return "/".join(parts)[:160]


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clean_llm_node_text(value: Any, fallback: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = text.strip(" ，。:：")
    if not text:
        text = fallback
    return text[:max_len].strip() or fallback


def _unique_llm_node_id(node_id: str, seen: set[str]) -> str:
    clean = node_id
    suffix = 2
    while clean in seen:
        clean = f"{node_id}_{suffix}"
        suffix += 1
    return clean


def _strip_graph_view(graph: dict[str, Any]) -> dict[str, Any]:
    graph.pop("route_preview", None)
    graph.pop("edges", None)
    return graph
