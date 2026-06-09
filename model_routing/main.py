"""Main interface for model routing and local API settings."""
from __future__ import annotations

from typing import Any

from .llm_client import chat_completion, read_llm_profile
from .routing import route_model
from .settings import load_env_file, read_settings, update_settings


def load_environment() -> str:
    return str(load_env_file())


def settings() -> dict[str, Any]:
    return read_settings()


def update(payload: dict[str, Any]) -> dict[str, Any]:
    return update_settings(payload)


def chat(prompt: str, *, profile: str = "complex", **kwargs: Any) -> dict[str, Any]:
    return chat_completion(prompt, profile=profile, **kwargs)


def commands(target_type: str | None = None) -> list[dict[str, Any]]:
    from ..agent_runtime.module_registry import list_module_commands

    return list_module_commands("model_routing", target_type)


__all__ = [
    "chat",
    "chat_completion",
    "commands",
    "load_environment",
    "read_llm_profile",
    "route_model",
    "settings",
    "update",
]
