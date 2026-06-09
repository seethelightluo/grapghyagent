"""Multi-agent tool adapters for the GraphyAgent command architecture."""
from __future__ import annotations

import uuid
from typing import Any


def _agent_tool(params: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a sub-agent task descriptor.

    The source project spawned threads directly. GraphyAgent routes work
    through project/graph command records, so this adapter returns an explicit
    task descriptor that the runtime can enqueue, inspect, or hand to a graph
    layer planner.
    """
    cfg = config or {}
    prompt = str(params.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Agent tool requires params.prompt")
    subagent_type = str(params.get("subagent_type") or params.get("agent_type") or "node-runner")
    name = str(params.get("name") or f"{subagent_type}-{uuid.uuid4().hex[:6]}")
    command = params.get("command") if isinstance(params.get("command"), dict) else {}
    descriptor = {
        "task_id": f"agent-{uuid.uuid4().hex[:12]}",
        "name": name,
        "subagent_type": subagent_type,
        "prompt": prompt,
        "wait": bool(params.get("wait", True)),
        "status": "planned",
        "command": command,
        "context": {
            "project_id": params.get("project_id") or cfg.get("project_id"),
            "graph_id": params.get("graph_id") or cfg.get("graph_id"),
            "node_id": params.get("node_id") or cfg.get("node_id"),
        },
    }
    return descriptor


def plan_parallel_node_agents(
    graph: dict[str, Any],
    *,
    project_id: str | None = None,
    graph_id: str | None = None,
    target_layer: int | None = None,
) -> dict[str, Any]:
    """Recommend sub-agent tasks for DAG layers with parallel nodes."""
    layers = _topological_layers(graph)
    parallel_layers = [
        (index, layer)
        for index, layer in enumerate(layers)
        if len(layer) > 1 and (target_layer is None or target_layer == index)
    ]
    tasks: list[dict[str, Any]] = []
    for layer_index, layer in parallel_layers:
        for node in layer:
            node_id = str(node.get("id") or "")
            task = _agent_tool(
                {
                    "name": f"node-runner-{node_id}",
                    "subagent_type": "node-runner",
                    "project_id": project_id,
                    "graph_id": graph_id or graph.get("graph_id"),
                    "node_id": node_id,
                    "prompt": _node_agent_prompt(graph, node, layer_index),
                    "command": {
                        "module": "graph_runner",
                        "command": "run_node",
                        "target_type": "node",
                        "project_id": project_id,
                        "graph_id": graph_id or graph.get("graph_id"),
                        "node_id": node_id,
                        "payload": {"node_id": node_id},
                    },
                },
                {"project_id": project_id, "graph_id": graph_id or graph.get("graph_id")},
            )
            tasks.append(task)
    return {
        "parallel_layer_count": len(parallel_layers),
        "agent_task_count": len(tasks),
        "tasks": tasks,
        "recommendation": (
            "存在可并行 DAG layer，建议用 multi_agent.tools._agent_tool 创建 node-runner 子 agent 并行完成节点任务。"
            if tasks
            else "当前图没有多个节点共享同一可并行 layer。"
        ),
    }


def _topological_layers(graph: dict[str, Any]) -> list[list[dict[str, Any]]]:
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    by_id = {str(node.get("id") or ""): node for node in nodes}
    indegree = {node_id: 0 for node_id in by_id}
    children = {node_id: [] for node_id in by_id}
    order = {str(node.get("id") or ""): index for index, node in enumerate(nodes)}
    for node_id, node in by_id.items():
        for dep in node.get("depends_on") or []:
            dep_id = str(dep)
            if dep_id in by_id:
                indegree[node_id] += 1
                children[dep_id].append(node_id)
    ready = [node_id for node_id, count in indegree.items() if count == 0]
    layers: list[list[dict[str, Any]]] = []
    visited = 0
    while ready:
        ready.sort(key=lambda item: order[item])
        layer = ready
        layers.append([by_id[node_id] for node_id in layer])
        visited += len(layer)
        next_ready: list[str] = []
        for node_id in layer:
            for child in children[node_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    next_ready.append(child)
        ready = next_ready
    if visited != len(nodes):
        return []
    return layers


def _node_agent_prompt(graph: dict[str, Any], node: dict[str, Any], layer_index: int) -> str:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    return (
        "你是 GraphyAgent node-runner 子 agent。请并行处理 DAG layer "
        f"{layer_index} 中的节点 `{node.get('id')}`。\n"
        f"图：{graph.get('graph_id')}\n"
        f"任务类型：{node.get('task_type')}\n"
        f"依赖：{node.get('depends_on') or []}\n"
        f"输入：{node.get('inputs') or {}}\n"
        f"输出：{node.get('output_roles') or {}}\n"
        f"任务说明：{metadata.get('description') or (node.get('executor') or {}).get('prompt') or ''}\n"
        "执行前读取相关 memory/context，检查 gate 条件，完成后写入节点输出和节点 memory。"
    )


__all__ = ["_agent_tool", "plan_parallel_node_agents"]
