"""Recovery prompts and graph-style task decomposition helpers."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from .builder import build_workflow_graph


def build_retry_prompt(
    *,
    task: str,
    error: str | None = None,
    inputs: dict[str, Any] | None = None,
    output_spec: dict[str, Any] | None = None,
) -> str:
    return (
        "你是 GraphyAgent 节点恢复智能体。请在不改变工作流拓扑的前提下重试当前节点任务。\n"
        "要求：\n"
        "- 先说明失败原因假设，再给出可执行修正步骤。\n"
        "- 必须基于输入文件和上游输出，不要编造未提供的数据。\n"
        "- 如果输出仍无法生成，明确列出缺失证据和需要人工补充的材料。\n\n"
        f"当前任务：\n{task}\n\n"
        f"失败错误：\n{error or '无'}\n\n"
        f"输入摘要 JSON：\n{json.dumps(inputs or {}, ensure_ascii=False, indent=2)}\n\n"
        f"输出要求 JSON：\n{json.dumps(output_spec or {}, ensure_ascii=False, indent=2)}"
    )


def build_decompose_prompt(
    *,
    task: str,
    error: str | None = None,
    failed_node_id: str | None = None,
    inputs: dict[str, Any] | None = None,
    output_spec: dict[str, Any] | None = None,
) -> str:
    return (
        "请把下面任务拆解成 GraphyAgent 可执行 DAG 工作流。\n"
        "这是 task.recovery 触发的恢复拆解，但输出必须保持 task_decompose 现有图式节点语义。\n\n"
        "拆解原则：\n"
        "- 每个节点必须是可执行子任务，包含输入、处理、输出。\n"
        "- 可以并行完成的子任务必须并行：它们应共享同一个最早有效上游，不能人为串成链。\n"
        "- 只有当 B 真实消费 A 的输出时，才生成 A -> B 依赖。\n"
        "- 需要长上下文、多文件分析、代码执行、跨证据推理的节点标 complex；简单抽取、清洗、格式化标 simple。\n"
        "- 保留清晰的最终汇总/验证节点，用于合并并行分支结果。\n"
        "- 节点名短、清楚、可放入画布；不要输出样例领域模板。\n\n"
        f"失败节点：{failed_node_id or '无'}\n"
        f"原始任务：\n{task}\n\n"
        f"失败错误：\n{error or '无'}\n\n"
        f"可用输入 JSON：\n{json.dumps(inputs or {}, ensure_ascii=False, indent=2)}\n\n"
        f"目标输出 JSON：\n{json.dumps(output_spec or {}, ensure_ascii=False, indent=2)}"
    )


def decompose_task(
    graph: dict[str, Any],
    *,
    task: str,
    error: str | None = None,
    failed_node_id: str | None = None,
    inputs: dict[str, Any] | None = None,
    output_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt = build_decompose_prompt(
        task=task,
        error=error,
        failed_node_id=failed_node_id,
        inputs=inputs,
        output_spec=output_spec,
    )
    new_graph = build_workflow_graph(deepcopy(graph), prompt)
    new_graph.setdefault("metadata", {}).setdefault("graphyagent", {}).setdefault("recovery", []).append(
        {
            "source": "task.recovery.decompose_task",
            "failed_node_id": failed_node_id,
            "error": error,
        }
    )
    return {
        "prompt": prompt,
        "graph": new_graph,
        "summary": _graph_summary(new_graph),
    }


def verify_output(output: Any, output_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(output or "").strip()
    issues: list[str] = []
    if not text:
        issues.append("输出为空。")
    spec = output_spec or {}
    required_terms = spec.get("required_terms") if isinstance(spec.get("required_terms"), list) else []
    for term in required_terms:
        if str(term) not in text:
            issues.append(f"缺少必需内容：{term}")
    min_chars = _positive_int(spec.get("min_chars")) if isinstance(spec, dict) else None
    if min_chars and len(text) < min_chars:
        issues.append(f"输出长度不足：{len(text)} < {min_chars}")
    return {
        "ok": not issues,
        "issues": issues,
        "length": len(text),
    }


def merge_sub_outputs(sub_outputs: dict[str, Any], output_spec: dict[str, Any] | None = None) -> dict[str, Any]:
    sections = []
    for node_id, output in sub_outputs.items():
        sections.append(f"## {node_id}\n{str(output).strip()}")
    merged = "\n\n".join(sections)
    return {
        "text": merged,
        "verification": verify_output(merged, output_spec),
        "source_node_count": len(sub_outputs),
    }


def extract_json(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("text does not contain a JSON object")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON value is not an object")
    return data


def _graph_summary(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") or []
    return {
        "node_count": len(nodes),
        "nodes": [
            {
                "id": node.get("id"),
                "depends_on": node.get("depends_on") or [],
                "complexity": (node.get("routing") or {}).get("complexity"),
            }
            for node in nodes
        ],
        "output_nodes": graph.get("output_nodes") or [],
    }


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


__all__ = [
    "build_decompose_prompt",
    "build_retry_prompt",
    "decompose_task",
    "extract_json",
    "merge_sub_outputs",
    "verify_output",
]
