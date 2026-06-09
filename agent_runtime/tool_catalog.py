"""Unified GraphyAgent tool catalog.

The runtime exposes only graph/task/data-management commands that belong to the
root ``graphyagent`` package. External agent-product utilities are intentionally
kept out of the default GraphyAgent command surface.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    target_types: tuple[str, ...]
    category: str
    source: str
    description: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target_types": list(self.target_types),
            "category": self.category,
            "source": self.source,
            "description": self.description,
            "payload": self.payload,
        }


AGENT_TOOL_CATALOG: tuple[AgentToolSpec, ...] = (
    AgentToolSpec(
        name="create_project",
        target_types=("project",),
        category="workspace",
        source="graphyagent_v2_web_entry",
        description="Create a project workspace for graphs, files, modules, and memory.",
        payload={"name": "required project name"},
    ),
    AgentToolSpec(
        name="select_project",
        target_types=("project",),
        category="workspace",
        source="graphyagent_v2_web_entry",
        description="Switch the active project.",
        payload={"project_id": "required project id when record.project_id is absent"},
    ),
    AgentToolSpec(
        name="delete_project",
        target_types=("project",),
        category="workspace",
        source="graphyagent_v2_web_entry",
        description="Delete a project and its managed graphs/files inside the workspace.",
        payload={"project_id": "required project id when record.project_id is absent"},
    ),
    AgentToolSpec(
        name="create_graph",
        target_types=("project", "graph"),
        category="graph_management",
        source="graphyagent_v2_web_entry",
        description="Create a graph in the current project.",
        payload={"name": "required graph name", "graph": "optional graph snapshot"},
    ),
    AgentToolSpec(
        name="select_graph",
        target_types=("graph",),
        category="graph_management",
        source="graphyagent_v2_web_entry",
        description="Switch the active graph in a project.",
        payload={"graph_id": "required graph id when record.graph_id is absent"},
    ),
    AgentToolSpec(
        name="delete_graph",
        target_types=("graph",),
        category="graph_management",
        source="graphyagent_v2_web_entry",
        description="Delete a graph and its graph-scoped files/modules/memory.",
        payload={"graph_id": "required graph id when record.graph_id is absent"},
    ),
    AgentToolSpec(
        name="save_graph",
        target_types=("graph",),
        category="graph_management",
        source="graphyagent_v2_web_entry",
        description="Persist a graph snapshot, correct dependency rules, and refresh modules.",
        payload={"graph": "required graph snapshot"},
    ),
    AgentToolSpec(
        name="update_node_task",
        target_types=("node",),
        category="task_graph",
        source="graphyagent_v1_core",
        description="Update a node's task name/description and write the change to node memory.",
        payload={"name": "optional new task name/id", "description": "optional task description"},
    ),
    AgentToolSpec(
        name="run_graph",
        target_types=("graph",),
        category="execution",
        source="graphyagent_v2_runtime",
        description="Run the current graph and persist GraphRun, node outputs, modules, and memory.",
        payload={"graph": "optional graph snapshot"},
    ),
    AgentToolSpec(
        name="run_node",
        target_types=("node",),
        category="execution",
        source="graphyagent_v1_core",
        description="Run a node-scoped graph containing the node and its upstream dependencies.",
        payload={"graph": "optional graph snapshot", "node_id": "optional node id override"},
    ),
    AgentToolSpec(
        name="chat_graph",
        target_types=("project", "graph", "node", "file"),
        category="memory_chat",
        source="graphyagent_v2_web_entry",
        description="Send a natural-language memory or graph-edit prompt to the backend agent.",
        payload={"prompt": "required user prompt"},
    ),
    AgentToolSpec(
        name="write_memory",
        target_types=("project", "graph", "node", "file"),
        category="memory",
        source="graphyagent_v1_core",
        description="Append a structured memory entry to project, graph, node, or file memory.",
        payload={"text": "required memory text", "role": "optional role, default user"},
    ),
    AgentToolSpec(
        name="read_memory",
        target_types=("project", "graph", "node", "file"),
        category="memory",
        source="graphyagent_v1_core",
        description="Read project, graph, node, or file memory without invoking an LLM.",
        payload={"target": "optional explicit target descriptor"},
    ),
    AgentToolSpec(
        name="audit_node_necessity",
        target_types=("node",),
        category="task_graph",
        source="graphyagent_v1_core",
        description="Audit whether a node is required, risky, or removable.",
        payload={},
    ),
    AgentToolSpec(
        name="decompose_node",
        target_types=("node",),
        category="task_graph",
        source="graphyagent_v1_core",
        description="Split a node into a smaller subgraph and preserve node files where possible.",
        payload={"child_names": "optional list of child node names"},
    ),
    AgentToolSpec(
        name="import_file",
        target_types=("project", "graph", "node"),
        category="data_management",
        source="graphyagent_v2_web_entry",
        description="Import a local or browser-uploaded file into project/graph/node file management.",
        payload={
            "scope": "project_unclassified | graph_unclassified | node",
            "path": "optional local path",
            "contentBase64": "optional browser upload",
            "name": "optional file name",
        },
    ),
    AgentToolSpec(
        name="move_file",
        target_types=("project", "graph", "node"),
        category="data_management",
        source="graphyagent_v2_web_entry",
        description="Move a managed file between project, graph, and node scopes.",
        payload={
            "file_id": "required file id",
            "target_scope": "project_unclassified | graph_unclassified | node",
            "node_id": "required when target_scope=node",
        },
    ),
    AgentToolSpec(
        name="delete_file",
        target_types=("project", "graph", "node"),
        category="data_management",
        source="graphyagent_v2_web_entry",
        description="Remove a managed file and unsync node inputs/evidence pointers.",
        payload={"file_id": "required file id"},
    ),
    AgentToolSpec(
        name="audit_dataset",
        target_types=("data", "file", "node"),
        category="data_audit",
        source="data_quality_audit",
        description="Run the local synthetic-data/data-quality audit on CSV/JSON/JSONL data.",
        payload={
            "dataset": "required dataset path",
            "metadata": "optional metadata path",
            "output_dir": "optional output directory for audit artifacts",
        },
    ),
    AgentToolSpec(
        name="list_subagent_types",
        target_types=("project", "graph", "node"),
        category="subagent",
        source="graphyagent_agent_runtime",
        description="List graph/node scoped worker profiles available to the agent runtime.",
        payload={},
    ),
)


EXCLUDED_LEGACY_TOOL_NAMES: tuple[str, ...] = (
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "WebBrowse",
    "ReadEmails",
    "SendEmail",
    "NotebookEdit",
    "TmuxNewSession",
    "TmuxSendKeys",
    "TradingBacktest",
    "VoiceTranscribe",
    "VideoGenerate",
    "Telegram",
    "Wechat",
    "Slack",
)


MODULE_INTEGRATION_INVENTORY: tuple[dict[str, Any], ...] = (
    {
        "path": "graphyagent/core",
        "classification": "core_integrated",
        "reason": "Graph config, schema, and shared runtime types.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/graph_runner",
        "classification": "core_integrated",
        "reason": "Graph/node execution and local artifact-producing runtime.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/data_manager",
        "classification": "core_integrated",
        "reason": "Projects, graphs, files, modules, and project/graph/node memory.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/graph_saver",
        "classification": "core_integrated",
        "reason": "Workflow persistence, graph version snapshots, restore, import, and export.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/knowledge_graph",
        "classification": "core_integrated",
        "reason": "Project Knowledge Graph, node-conditioned views, and feedback weights.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/node_memory",
        "classification": "core_integrated",
        "reason": "Bounded Node Memory Packet assembly and context usage logging.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/execution_lineage",
        "classification": "core_integrated",
        "reason": "Deterministic execution lineage, checkpoint verifier, and replay planning.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/reflection",
        "classification": "core_integrated",
        "reason": "Online NodeRun reflection labels without direct graph mutation.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/graph_optimizer",
        "classification": "core_integrated",
        "reason": "Offline edge utility scoring, subgraph mining, and graph version suggestions.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/evaluation",
        "classification": "core_integrated",
        "reason": "Graph version regression metrics and promotion reports.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/playbooks",
        "classification": "core_integrated",
        "reason": "Reusable subgraph motif serialization and matching.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/data_audit",
        "classification": "core_integrated",
        "reason": "Evidence-first data quality and synthetic-data audit pipeline.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/model_routing",
        "classification": "core_integrated",
        "reason": "Simple/complex API profiles, .env settings, LLM fallback, and routing decisions.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/agent_runtime",
        "classification": "core_integrated",
        "reason": "Graph/node command runtime, scoped tool catalog, and worker profile definitions.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/front_bridge",
        "classification": "core_integrated",
        "reason": "CLI/Web/API bridge and persistent command queue for UI and autonomous execution.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/node_audit",
        "classification": "core_integrated",
        "reason": "Node necessity audit module entrypoint backed by project graph state.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/task_decompose",
        "classification": "core_integrated",
        "reason": "Node-to-subgraph decomposition module entrypoint.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/memory",
        "classification": "core_integrated",
        "reason": "Relevant project/graph/node long-term memory lookup and prompt context rendering.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/multi_agent",
        "classification": "core_integrated",
        "reason": "Queue-compatible sub-agent task descriptors and parallel node-agent planning.",
        "action": "root_core_module",
    },
    {
        "path": "graphyagent/research",
        "classification": "core_integrated",
        "reason": "Deterministic citation and report rendering with previewable artifacts.",
        "action": "root_core_module",
    },
)


def list_agent_tools(target_type: str | None = None) -> list[dict[str, Any]]:
    tools = [
        item
        for item in AGENT_TOOL_CATALOG
        if not target_type or target_type in item.target_types
    ]
    return [item.to_dict() for item in tools]


def agent_command_names() -> list[str]:
    return [item.name for item in AGENT_TOOL_CATALOG]


def agent_target_types() -> list[str]:
    values = sorted({target for item in AGENT_TOOL_CATALOG for target in item.target_types})
    return values


def list_module_inventory(classification: str | None = None) -> list[dict[str, Any]]:
    if classification:
        return [
            dict(item)
            for item in MODULE_INTEGRATION_INVENTORY
            if item.get("classification") == classification
        ]
    return [dict(item) for item in MODULE_INTEGRATION_INVENTORY]


def format_agent_tools_markdown(target_type: str | None = None) -> str:
    tools = list_agent_tools(target_type)
    lines = ["# GraphyAgent Agent Tools", ""]
    for tool in tools:
        targets = ", ".join(tool.get("target_types", []))
        payload = json.dumps(tool.get("payload") or {}, ensure_ascii=False)
        lines.append(
            f"- `{tool['name']}` [{targets}] "
            f"({tool['category']} / {tool['source']}) - {tool['description']}"
        )
        lines.append(f"  payload: `{payload}`")
    return "\n".join(lines)
