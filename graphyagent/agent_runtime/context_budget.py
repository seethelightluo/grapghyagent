"""Context and output-token budgeting helpers for agent/runtime calls."""
from __future__ import annotations

import json
import os
from typing import Any


_DEFAULT_CONTEXT_LIMIT = 128_000
_MODEL_CONTEXT_LIMITS = {
    "gpt-4o": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-5": 400_000,
    "gpt-5-mini": 400_000,
    "claude-3": 200_000,
    "claude-sonnet": 200_000,
    "claude-opus": 200_000,
    "glm-5": 128_000,
    "glm-5.1": 128_000,
    "mimo-v2.5": 128_000,
}


def estimate_tokens(value: Any) -> int:
    """Cheap mixed Chinese/English token estimate.

    It is intentionally conservative enough for budgeting, not a tokenizer.
    """
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value or "")
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, int(ascii_chars / 3.6 + non_ascii_chars / 1.8))


def get_context_limit(model: str | None = None) -> int:
    configured = _int_env("GRAPHYAGENT_CONTEXT_LIMIT")
    if configured:
        return configured
    normalized = str(model or "").lower()
    for name, limit in _MODEL_CONTEXT_LIMITS.items():
        if name in normalized:
            return limit
    return _DEFAULT_CONTEXT_LIMIT


def resolve_max_tokens(
    requested: Any = None,
    *,
    model: str | None = None,
    profile: str | None = None,
    default: int | None = None,
    prompt: Any | None = None,
) -> int:
    """Resolve a practical max_tokens value for LLM calls.

    The old runtime used 900-1200 token defaults in several hot paths. This
    helper keeps simple calls modest while giving complex graph/node agents
    enough room to finish real file-backed tasks.
    """
    requested_value = _positive_int(requested)
    profile_name = str(profile or "").lower()
    if requested_value:
        base = requested_value
    elif profile_name == "simple":
        base = _int_env("GRAPHYAGENT_SIMPLE_MAX_TOKENS") or default or 2_048
    else:
        base = _int_env("GRAPHYAGENT_COMPLEX_MAX_TOKENS") or default or 8_192
    global_cap = _int_env("GRAPHYAGENT_MAX_TOKENS")
    profile_cap = (
        _int_env("GRAPHYAGENT_SIMPLE_MAX_TOKENS_CAP")
        if profile_name == "simple"
        else _int_env("GRAPHYAGENT_COMPLEX_MAX_TOKENS_CAP")
    )
    cap = profile_cap or global_cap
    if cap:
        base = min(base, cap)
    context_limit = get_context_limit(model)
    prompt_tokens = estimate_tokens(prompt) if prompt is not None else 0
    remaining = max(512, context_limit - prompt_tokens - 1_024)
    return max(256, min(int(base), remaining))


def default_input_char_limit(profile: str | None = None) -> int:
    configured = _int_env("GRAPHYAGENT_NODE_INPUT_CHAR_LIMIT")
    if configured:
        return configured
    return 120_000 if str(profile or "").lower() == "complex" else 60_000


def clip_text(text: Any, max_chars: int, *, label: str | None = None) -> str:
    value = str(text or "")
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    prefix = f"{label} " if label else ""
    return value[:max_chars] + f"\n\n...[{prefix}content truncated, {len(value) - max_chars} chars omitted]..."


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _int_env(name: str) -> int | None:
    return _positive_int(os.environ.get(name))


__all__ = [
    "clip_text",
    "default_input_char_limit",
    "estimate_tokens",
    "get_context_limit",
    "resolve_max_tokens",
]
