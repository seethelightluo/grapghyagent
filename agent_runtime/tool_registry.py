"""Tool registry for backend graph/node agents."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .common_tools import (
    glob_files,
    grep_files,
    read_file,
    read_file_content,
    read_image_ocr,
    read_pdf,
    read_table_file,
)


ToolFunc = Callable[..., Any]


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    target_types: tuple[str, ...]
    category: str
    handler: ToolFunc
    cacheable: bool = True

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": deepcopy(self.input_schema),
            "target_types": list(self.target_types),
            "category": self.category,
        }


_TOOLS: dict[str, ToolDef] = {}
_CACHE: dict[str, Any] = {}


def register_tool(tool: ToolDef) -> ToolDef:
    _TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> ToolDef:
    tool_name = str(name or "")
    if tool_name not in _TOOLS:
        raise KeyError(f"unknown tool: {name}")
    return _TOOLS[tool_name]


def get_all_tools() -> list[ToolDef]:
    return [tool for _, tool in sorted(_TOOLS.items())]


def get_tool_schemas(target_type: str | None = None) -> list[dict[str, Any]]:
    return [
        tool.schema()
        for tool in get_all_tools()
        if not target_type or target_type in tool.target_types
    ]


def execute_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    workspace_root: str | None = None,
    allow_outside_workspace: bool = True,
    use_cache: bool = True,
) -> dict[str, Any]:
    tool = get_tool(name)
    args = dict(arguments or {})
    args.setdefault("workspace_root", workspace_root)
    args.setdefault("allow_outside_workspace", allow_outside_workspace)
    cache_key = _cache_key(tool.name, args)
    if use_cache and tool.cacheable and cache_key in _CACHE:
        return {"tool": tool.name, "cached": True, "result": deepcopy(_CACHE[cache_key])}
    result = tool.handler(**args)
    if use_cache and tool.cacheable:
        _CACHE[cache_key] = deepcopy(result)
    return {"tool": tool.name, "cached": False, "result": result}


def clear_tool_cache() -> None:
    _CACHE.clear()


def _cache_key(name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps({"name": name, "arguments": arguments}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _register_default_tools() -> None:
    register_tool(
        ToolDef(
            name="ReadFile",
            description="读取文本或可自动识别的文件内容，支持 txt/md/json/csv/pdf/excel/image 降级解析。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 120000},
                    "page_range": {"type": "string"},
                    "sheet": {"type": "string"},
                },
                "required": ["file_path"],
            },
            target_types=("project", "graph", "node", "file"),
            category="file_context",
            handler=read_file_content,
        )
    )
    register_tool(
        ToolDef(
            name="ReadText",
            description="按文本读取文件，适合代码、markdown、json、日志等。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 120000},
                    "offset": {"type": "integer", "default": 0},
                },
                "required": ["file_path"],
            },
            target_types=("project", "graph", "node", "file"),
            category="file_context",
            handler=read_file,
        )
    )
    register_tool(
        ToolDef(
            name="ReadTable",
            description="读取 CSV/TSV/Excel 的前若干行并格式化为文本表格。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "sheet": {"type": "string"},
                    "max_rows": {"type": "integer", "default": 80},
                    "max_chars": {"type": "integer", "default": 120000},
                },
                "required": ["file_path"],
            },
            target_types=("project", "graph", "node", "file", "data"),
            category="file_context",
            handler=read_table_file,
        )
    )
    register_tool(
        ToolDef(
            name="ReadPdf",
            description="读取 PDF 文本，可指定页码范围，例如 1-3,5。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "page_range": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 120000},
                },
                "required": ["file_path"],
            },
            target_types=("project", "graph", "node", "file"),
            category="file_context",
            handler=read_pdf,
        )
    )
    register_tool(
        ToolDef(
            name="ReadImageOCR",
            description="对图片尝试 OCR；环境缺 OCR 依赖时返回图片元数据和缺依赖说明。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "max_chars": {"type": "integer", "default": 60000},
                },
                "required": ["file_path"],
            },
            target_types=("project", "graph", "node", "file"),
            category="file_context",
            handler=read_image_ocr,
        )
    )
    register_tool(
        ToolDef(
            name="Glob",
            description="在工作区内按 glob pattern 查找文件。",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer", "default": 200},
                },
                "required": ["pattern"],
            },
            target_types=("project", "graph", "node", "file"),
            category="search",
            handler=glob_files,
        )
    )
    register_tool(
        ToolDef(
            name="Grep",
            description="在工作区文件中搜索文本内容，优先使用 rg，缺失时使用 Python fallback。",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "case_insensitive": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "default": 200},
                },
                "required": ["pattern"],
            },
            target_types=("project", "graph", "node", "file"),
            category="search",
            handler=grep_files,
        )
    )
    register_tool(
        ToolDef(
            name="Agent",
            description="创建 GraphyAgent 子 agent 任务描述，用于并行节点任务、审查或专项执行。",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "subagent_type": {"type": "string", "default": "node-runner"},
                    "name": {"type": "string"},
                    "project_id": {"type": "string"},
                    "graph_id": {"type": "string"},
                    "node_id": {"type": "string"},
                    "command": {"type": "object"},
                },
                "required": ["prompt"],
            },
            target_types=("project", "graph", "node"),
            category="multi_agent",
            handler=_agent_tool_handler,
            cacheable=False,
        )
    )
    register_tool(
        ToolDef(
            name="PlanParallelNodeAgents",
            description="分析图的可并行 DAG layer，并为每个并行节点生成 node-runner 子 agent 计划。",
            input_schema={
                "type": "object",
                "properties": {
                    "graph": {"type": "object"},
                    "project_id": {"type": "string"},
                    "graph_id": {"type": "string"},
                    "target_layer": {"type": "integer"},
                },
                "required": ["graph"],
            },
            target_types=("graph",),
            category="multi_agent",
            handler=_plan_parallel_agents_handler,
            cacheable=False,
        )
    )
    register_tool(
        ToolDef(
            name="RenderReport",
            description="把结构化 brief 或 graph/node outputs 渲染为 Markdown/HTML 报告，并返回可预览路径。",
            input_schema={
                "type": "object",
                "properties": {
                    "brief": {"type": "object"},
                    "outputs": {},
                    "topic": {"type": "string"},
                    "output_dir": {"type": "string"},
                    "basename": {"type": "string"},
                    "include_html": {"type": "boolean", "default": True},
                },
            },
            target_types=("project", "graph", "node", "file", "data"),
            category="report_rendering",
            handler=_render_report_handler,
            cacheable=False,
        )
    )
    register_tool(
        ToolDef(
            name="RenderCitations",
            description="把 brief/results 渲染为编号引用列表 Markdown。",
            input_schema={
                "type": "object",
                "properties": {
                    "brief": {"type": "object"},
                    "results": {"type": "array"},
                },
            },
            target_types=("project", "graph", "node", "file", "data"),
            category="report_rendering",
            handler=_render_citations_handler,
        )
    )


def _agent_tool_handler(**kwargs: Any) -> dict[str, Any]:
    from ..multi_agent.tools import _agent_tool

    config = {
        "project_id": kwargs.pop("project_id", None),
        "graph_id": kwargs.pop("graph_id", None),
        "node_id": kwargs.pop("node_id", None),
    }
    kwargs.pop("workspace_root", None)
    kwargs.pop("allow_outside_workspace", None)
    return _agent_tool(kwargs, config)


def _plan_parallel_agents_handler(**kwargs: Any) -> dict[str, Any]:
    from ..multi_agent.tools import plan_parallel_node_agents

    graph = kwargs.get("graph")
    if not isinstance(graph, dict):
        raise ValueError("PlanParallelNodeAgents requires graph object")
    return plan_parallel_node_agents(
        graph,
        project_id=kwargs.get("project_id"),
        graph_id=kwargs.get("graph_id"),
        target_layer=kwargs.get("target_layer"),
    )


def _render_report_handler(**kwargs: Any) -> dict[str, Any]:
    from ..research.synthesizer import brief_from_outputs, render_report_files

    workspace_root = Path(str(kwargs.get("workspace_root") or ".")).expanduser().resolve()
    output_dir = _workspace_output_dir(workspace_root, kwargs.get("output_dir"))
    brief = kwargs.get("brief")
    if not isinstance(brief, dict):
        brief = brief_from_outputs(
            topic=str(kwargs.get("topic") or "GraphyAgent Report"),
            outputs=kwargs.get("outputs") or {},
        )
    result = render_report_files(
        brief,
        output_dir=output_dir,
        basename=str(kwargs.get("basename") or "report"),
        include_html=bool(kwargs.get("include_html", True)),
    )
    preview_path = str(result.get("preview_path") or "")
    result["preview_url"] = f"/api/files/open?path={quote(preview_path)}" if preview_path else None
    return result


def _render_citations_handler(**kwargs: Any) -> dict[str, Any]:
    from ..research.synthesizer import render_citations

    brief = kwargs.get("brief")
    if not isinstance(brief, dict):
        brief = {"topic": "GraphyAgent Citations", "results": kwargs.get("results") or []}
    return {"citations": render_citations(brief)}


def _workspace_output_dir(workspace_root: Path, output_dir: Any) -> Path:
    if not output_dir:
        return workspace_root / "reports"
    candidate = Path(str(output_dir)).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(workspace_root)
        return candidate
    except ValueError:
        return workspace_root / "reports" / candidate.name


_register_default_tools()


__all__ = [
    "ToolDef",
    "clear_tool_cache",
    "execute_tool",
    "get_all_tools",
    "get_tool",
    "get_tool_schemas",
    "register_tool",
]
