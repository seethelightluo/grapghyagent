"""GraphyAgent-scoped sub-agent definitions.

This is intentionally smaller than the old external multi-agent runtime. The
graph agent only needs named worker profiles that can be selected by graph/node
commands; process/thread orchestration belongs in the command queue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str = ""
    system_prompt: str = ""
    model: str = ""
    tools: list[str] = field(default_factory=list)
    source: str = "built-in"


_BUILTIN_AGENTS: dict[str, AgentDefinition] = {
    "general-purpose": AgentDefinition(
        name="general-purpose",
        description="General GraphyAgent worker for graph planning, node review, and project operations.",
    ),
    "planner": AgentDefinition(
        name="planner",
        description="Builds or revises a graph workflow from natural-language goals.",
        system_prompt=(
            "You are a GraphyAgent planning worker. Produce compact DAG plans with "
            "clear node tasks, inputs, outputs, gates, and evidence requirements."
        ),
        tools=["chat_graph", "save_graph", "audit_node_necessity", "decompose_node"],
    ),
    "node-runner": AgentDefinition(
        name="node-runner",
        description="Runs one node with its upstream context and records outputs, evidence, and memory.",
        system_prompt=(
            "You are a node execution worker. Resolve node inputs, run only the "
            "required node scope, and record structured output and memory."
        ),
        tools=["run_node", "write_memory", "read_memory", "audit_dataset"],
    ),
    "data-auditor": AgentDefinition(
        name="data-auditor",
        description="Audits datasets for quality issues and synthetic-data evidence.",
        system_prompt=(
            "You are a data quality auditor. Use local detector evidence first, "
            "avoid unsupported narrative claims, and return actionable gates."
        ),
        tools=["audit_dataset", "write_memory"],
    ),
    "reviewer": AgentDefinition(
        name="reviewer",
        description="Reviews graph nodes for necessity, missing gates, weak evidence, and unsafe dependencies.",
        system_prompt=(
            "You are a graph review worker. Verify node necessity, dependency "
            "direction, evidence pointers, gates, and user-facing output quality."
        ),
        tools=["audit_node_necessity", "read_memory", "write_memory"],
    ),
}


def load_agent_definitions(search_root: str | Path | None = None) -> dict[str, AgentDefinition]:
    """Load built-in plus optional project-local agent definitions.

    Project-local definitions live under ``<search_root>/.graphyagent/agents``
    or ``cwd/.graphyagent/agents``. A markdown file may start with simple
    frontmatter keys: description, model, tools.
    """
    definitions = dict(_BUILTIN_AGENTS)
    root = Path(search_root).expanduser().resolve() if search_root else Path.cwd()
    for directory, source in (
        (Path.home() / ".graphyagent" / "agents", "user"),
        (root / ".graphyagent" / "agents", "project"),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                definition = _parse_agent_markdown(path, source)
            except OSError:
                continue
            definitions[definition.name] = definition
    return definitions


def get_agent_definition(name: str, search_root: str | Path | None = None) -> AgentDefinition | None:
    return load_agent_definitions(search_root).get(name)


def _parse_agent_markdown(path: Path, source: str) -> AgentDefinition:
    content = path.read_text(encoding="utf-8")
    metadata: dict[str, Any] = {}
    body = content.strip()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            frontmatter = content[3:end].strip()
            body = content[end + 3 :].strip()
            metadata = _parse_simple_frontmatter(frontmatter)
    tools = metadata.get("tools") or []
    if isinstance(tools, str):
        tools = [item.strip() for item in tools.strip("[]").split(",") if item.strip()]
    return AgentDefinition(
        name=path.stem,
        description=str(metadata.get("description") or ""),
        system_prompt=body,
        model=str(metadata.get("model") or ""),
        tools=[str(item) for item in tools],
        source=source,
    )


def _parse_simple_frontmatter(text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip().strip("'\"")
    return values
