"""Small programmatic API for GraphyAgent graph configs and runs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import load_graph_config
from ..core.types import GraphConfig, GraphState
from ..graph_runner.executor import GraphExecutor
from ..graph_runner.history import (
    list_graph_runs as _list_graph_runs,
    read_graph_run as _read_graph_run,
    read_node_runs as _read_node_runs,
)
from ..model_routing.routing import route_model


def inspect_graph_config(config_path: str | Path) -> dict[str, Any]:
    config = load_graph_config(config_path)
    state = GraphState(context=config.context, experiment=config.experiment)
    data = config.to_dict()
    data["route_preview"] = {
        node.node_id: route_model(config, node, state).to_dict()
        for node in config.nodes
    }
    return data


def run_graph_config(config_path: str | Path, workspace: str | Path) -> dict[str, Any]:
    config = load_graph_config(config_path)
    graph_run = GraphExecutor(workspace).run_graph(config)
    return graph_run.to_dict()


def run_graph(config: GraphConfig, workspace: str | Path) -> dict[str, Any]:
    graph_run = GraphExecutor(workspace).run_graph(config)
    return graph_run.to_dict()


def list_graph_runs(workspace: str | Path) -> list[dict[str, Any]]:
    return _list_graph_runs(workspace)


def read_graph_run(workspace: str | Path, graph_run_id: str) -> dict[str, Any]:
    return _read_graph_run(workspace, graph_run_id)


def read_node_runs(workspace: str | Path, graph_run_id: str) -> list[dict[str, Any]]:
    return _read_node_runs(workspace, graph_run_id)
