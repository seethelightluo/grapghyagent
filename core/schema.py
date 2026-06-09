"""JSON schema for GraphyAgent graph configuration files."""
from __future__ import annotations

from typing import Any


GRAPH_CONFIG_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://graphyagent.local/schemas/graphyagent.graph.schema.json",
    "title": "GraphyAgent Graph Config",
    "type": "object",
    "required": ["graph_id", "nodes"],
    "additionalProperties": True,
    "properties": {
        "graph_id": {"type": "string"},
        "context": {"type": "object"},
        "experiment": {"type": "object"},
        "initial_artifacts": {
            "type": "object",
            "additionalProperties": {
                "oneOf": [
                    {"type": "string"},
                    {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string"},
                            "type": {"type": "string"},
                            "metadata": {"type": "object"},
                        },
                    },
                ]
            },
        },
        "providers": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["provider_id"],
                "properties": {
                    "provider_id": {"type": "string"},
                    "config": {"type": "object"},
                    "models": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "required": ["model_id"],
                                    "properties": {
                                        "model_id": {"type": "string"},
                                        "capabilities": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "tier": {
                                            "type": "string",
                                            "enum": ["cheap", "standard", "expensive"],
                                        },
                                        "metadata": {"type": "object"},
                                    },
                                },
                            ]
                        },
                    },
                },
            },
        },
        "router": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["static", "simple_vs_complex", "complexity", "task_type_based"],
                },
                "default_model_ref": {"type": "string"},
                "cost_preference": {
                    "type": "string",
                    "enum": ["cheap", "balanced", "quality"],
                },
                "max_tier": {
                    "type": "string",
                    "enum": ["cheap", "standard", "expensive"],
                },
                "routes": {"type": "object"},
            },
        },
        "nodes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "executor"],
                "properties": {
                    "id": {"type": "string"},
                    "depends_on": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "inputs": {"type": "object"},
                    "output_roles": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "interface": {
                        "type": "object",
                        "properties": {
                            "inputs": {
                                "oneOf": [
                                    {"type": "object"},
                                    {"type": "array", "items": {"type": "string"}},
                                ]
                            },
                            "outputs": {
                                "oneOf": [
                                    {"type": "object"},
                                    {"type": "array", "items": {"type": "string"}},
                                ]
                            },
                            "required_inputs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "required_outputs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "additionalProperties": True,
                    },
                    "input_spec": {"oneOf": [{"type": "object"}, {"type": "array"}, {"type": "string"}]},
                    "output_spec": {"oneOf": [{"type": "object"}, {"type": "array"}, {"type": "string"}]},
                    "input_example": {},
                    "output_example": {},
                    "verification_rule": {"type": "string"},
                    "gate_condition": {"type": "string"},
                    "gate_status": {"type": "string"},
                    "gate": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "condition": {"type": "string"},
                                    "required_inputs": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "required_outputs": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "additionalProperties": True,
                            },
                        ]
                    },
                    "evidence_pointers": {
                        "type": "array",
                        "items": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                    },
                    "model_ref": {"type": "string"},
                    "task_type": {"type": "string"},
                    "routing": {"type": "object"},
                    "executor": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["noop", "python", "shell", "audit", "llm", "subgraph", "http", "sqlite", "db_query"],
                            },
                            "code": {"type": "string"},
                            "script": {"type": "string"},
                            "command": {
                                "oneOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}},
                                ]
                            },
                            "url": {"type": "string"},
                            "method": {"type": "string"},
                            "headers": {"type": "object"},
                            "params": {"type": "object"},
                            "body": {},
                            "json": {},
                            "database": {"type": "string"},
                            "database_path": {"type": "string"},
                            "database_input": {"type": "string"},
                            "query": {"type": "string"},
                            "parameters": {
                                "oneOf": [
                                    {"type": "object"},
                                    {"type": "array"},
                                ]
                            },
                            "read_only": {"type": "boolean"},
                            "output": {"type": "string"},
                            "timeout_seconds": {"type": "number"},
                        },
                    },
                    "metadata": {"type": "object"},
                },
            },
        },
        "output_nodes": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
    },
}
