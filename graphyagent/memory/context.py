"""Relevant memory lookup for graph/node prompt injection."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..agent_runtime.context_budget import clip_text


MAX_MEMORY_CHARS = 20_000


@dataclass(frozen=True)
class MemoryEntry:
    scope: str
    name: str
    content: str
    file_path: str
    mtime: float
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "name": self.name,
            "content": self.content,
            "file_path": self.file_path,
            "mtime": self.mtime,
            "score": self.score,
        }


def find_relevant_memories(
    query: str,
    *,
    workspace_root: str | Path,
    graph: dict[str, Any] | None = None,
    node_id: str | None = None,
    max_results: int = 6,
    max_chars_per_memory: int = 3_000,
) -> list[dict[str, Any]]:
    """Find project/graph/node memories relevant to a query.

    This is a GraphyAgent-native adapter of the old memory.context function:
    it scans the existing ``projects/*/memory`` and ``graphs/*/memory``
    layout instead of the old ``.cheetahclaws`` folders.
    """
    root = Path(workspace_root).expanduser().resolve()
    terms = _query_terms(_memory_query(query, graph, node_id))
    candidates = _scan_memory_files(root, graph=graph, node_id=node_id)
    scored: list[MemoryEntry] = []
    for entry in candidates:
        score = _memory_score(entry, terms, graph, node_id)
        if score <= 0 and terms:
            continue
        scored.append(MemoryEntry(
            scope=entry.scope,
            name=entry.name,
            content=clip_text(entry.content, max_chars_per_memory, label=entry.name),
            file_path=entry.file_path,
            mtime=entry.mtime,
            score=score,
        ))
    scored.sort(key=lambda item: (item.score, item.mtime), reverse=True)
    return [item.to_dict() for item in scored[: max(1, max_results)]]


def get_memory_context(
    *,
    workspace_root: str | Path,
    graph: dict[str, Any] | None = None,
    node_id: str | None = None,
    query: str = "",
    max_results: int = 6,
    max_chars: int = MAX_MEMORY_CHARS,
) -> str:
    memories = find_relevant_memories(
        query,
        workspace_root=workspace_root,
        graph=graph,
        node_id=node_id,
        max_results=max_results,
        max_chars_per_memory=max(800, max_chars // max(1, max_results)),
    )
    if not memories:
        return ""
    lines = [
        "## 相关长期记忆",
        "以下内容来自 GraphyAgent project/graph/node memory，用于补充当前节点的输入、输出、上游依赖和历史执行信息。",
        "",
    ]
    for item in memories:
        lines.append(f"### {item['scope']} / {item['name']}")
        lines.append(f"source: {item['file_path']}")
        lines.append("")
        lines.append(str(item["content"]).strip())
        lines.append("")
    return clip_text("\n".join(lines).strip(), max_chars, label="memory_context")


def _memory_query(query: str, graph: dict[str, Any] | None, node_id: str | None) -> str:
    parts = [query or "", node_id or ""]
    graph_data = graph or {}
    nodes = graph_data.get("nodes") or []
    by_id = {str(node.get("id") or ""): node for node in nodes}
    node = by_id.get(str(node_id or ""))
    if node:
        parts.append(str(node.get("task_type") or ""))
        metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
        parts.append(str(metadata.get("description") or ""))
        for dep in node.get("depends_on") or []:
            parts.append(str(dep))
            dep_node = by_id.get(str(dep))
            if dep_node:
                parts.append(str((dep_node.get("metadata") or {}).get("description") or ""))
    for output_node in graph_data.get("output_nodes") or []:
        parts.append(str(output_node))
    return "\n".join(part for part in parts if part)


def _scan_memory_files(
    workspace_root: Path,
    *,
    graph: dict[str, Any] | None,
    node_id: str | None,
) -> list[MemoryEntry]:
    projects_root = workspace_root / "projects"
    if not projects_root.exists():
        return []
    graph_id = str((graph or {}).get("graph_id") or "")
    entries: list[MemoryEntry] = []
    for project_dir in sorted(path for path in projects_root.iterdir() if path.is_dir()):
        entries.extend(_memory_file_entries(project_dir / "memory", "project"))
        graphs_root = project_dir / "graphs"
        if not graphs_root.is_dir():
            continue
        for graph_dir in sorted(path for path in graphs_root.iterdir() if path.is_dir()):
            if graph_id and graph_dir.name != _slug(graph_id):
                continue
            entries.extend(_memory_file_entries(graph_dir / "memory", "graph"))
            node_memory_dir = graph_dir / "memory" / "nodes"
            if node_memory_dir.is_dir():
                for path in sorted(node_memory_dir.glob("*.md")):
                    scope = "node"
                    if node_id and path.stem == _node_asset_name(node_id):
                        scope = "current_node"
                    entries.append(_entry_from_file(path, scope))
    return entries


def _memory_file_entries(directory: Path, scope: str) -> list[MemoryEntry]:
    if not directory.is_dir():
        return []
    return [_entry_from_file(path, scope) for path in sorted(directory.glob("*.md"))]


def _entry_from_file(path: Path, scope: str) -> MemoryEntry:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        content = ""
    return MemoryEntry(
        scope=scope,
        name=path.stem,
        content=content,
        file_path=str(path),
        mtime=path.stat().st_mtime if path.exists() else 0,
    )


def _memory_score(
    entry: MemoryEntry,
    terms: set[str],
    graph: dict[str, Any] | None,
    node_id: str | None,
) -> float:
    haystack = f"{entry.name}\n{entry.content}".lower()
    score = 0.0
    for term in terms:
        if term and term in haystack:
            score += 1.0 + min(2.0, haystack.count(term) * 0.1)
    if entry.scope == "current_node":
        score += 4.0
    elif entry.scope == "graph":
        score += 2.0
    elif entry.scope == "project":
        score += 1.0
    if graph and str(graph.get("graph_id") or "").lower() in haystack:
        score += 1.5
    if node_id and str(node_id).lower() in haystack:
        score += 2.0
    return score


def _query_terms(text: str) -> set[str]:
    lowered = str(text or "").lower()
    raw_terms = re.findall(r"[a-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", lowered)
    stop = {"graphyagent", "node", "task", "output", "input", "current", "memory"}
    return {term for term in raw_terms if term not in stop}


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+", "-", str(value).strip())
    return text.strip("-").lower() or "graph"


def _node_asset_name(value: str) -> str:
    return _slug(value).replace("-", "_")


__all__ = ["MemoryEntry", "find_relevant_memories", "get_memory_context"]
