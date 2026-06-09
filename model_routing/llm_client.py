"""Minimal LLM client for GraphyAgent runtime profiles."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .settings import load_env_file


class LLMCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMProfile:
    name: str
    api_format: str
    api_key: str
    base_url: str
    model: str


def chat_completion(
    prompt: str,
    *,
    profile: str = "complex",
    system: str | None = None,
    fallback_profiles: list[str] | None = None,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Call an LLM using a named local profile.

    ``profile='simple'`` is intended for node-level memory and low-cost node
    execution. Callers can pass ``fallback_profiles=['complex']`` to retry with
    the stronger profile when the simple API fails.
    """
    load_env_file()
    profiles = [profile, *(fallback_profiles or [])]
    errors: list[str] = []
    for profile_name in profiles:
        try:
            resolved = read_llm_profile(profile_name)
            text, raw = _call_profile(
                resolved,
                prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
            return {
                "text": text,
                "profile": resolved.name,
                "api_format": resolved.api_format,
                "model": resolved.model,
                "base_url": resolved.base_url,
                "raw": raw,
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{profile_name}: {exc}")
    raise LLMCallError("LLM call failed: " + " | ".join(errors))


def tool_chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    profile: str = "complex",
    system: str | None = None,
    fallback_profiles: list[str] | None = None,
    max_tokens: int = 4000,
    temperature: float = 0.2,
    timeout_seconds: float | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an LLM with Anthropic-style client tools.

    The runtime-facing shape is intentionally Anthropic-like even when the
    backing provider is OpenAI-compatible:
    assistant messages may contain ``tool_use`` blocks and user messages may
    return matching ``tool_result`` blocks.
    """
    load_env_file()
    profiles = [profile, *(fallback_profiles or [])]
    errors: list[str] = []
    for profile_name in profiles:
        try:
            resolved = read_llm_profile(profile_name)
            content, raw = _call_profile_with_tools(
                resolved,
                messages,
                tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                tool_choice=tool_choice,
            )
            text, tool_uses = _anthropic_content_text_and_tools(content)
            return {
                "text": text,
                "content": content,
                "tool_uses": tool_uses,
                "stop_reason": raw.get("stop_reason") or raw.get("finish_reason"),
                "profile": resolved.name,
                "api_format": resolved.api_format,
                "model": resolved.model,
                "base_url": resolved.base_url,
                "raw": raw,
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{profile_name}: {exc}")
    raise LLMCallError("LLM tool call failed: " + " | ".join(errors))


def read_llm_profile(profile: str) -> LLMProfile:
    load_env_file()
    name = "complex" if profile == "graph" else profile
    prefix = f"GRAPHYAGENT_{name.upper()}_"
    api_format = os.environ.get(prefix + "API_FORMAT", "").strip().lower()
    api_key = os.environ.get(prefix + "API_KEY", "").strip()
    base_url = os.environ.get(prefix + "BASE_URL", "").strip()
    model = os.environ.get(prefix + "MODEL", "").strip()

    if not api_format and name == "complex":
        api_format = "anthropic" if os.environ.get("ANTHROPIC_AUTH_TOKEN") else ""
        api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        model = os.environ.get("ANTHROPIC_MODEL", "")
    if not api_format and name == "simple" and os.environ.get("OPENAI_API_KEY"):
        api_format = "openai"
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_BASE_URL", "")
        model = os.environ.get("OPENAI_MODEL", "")

    if api_format not in {"openai", "anthropic"}:
        raise LLMCallError(f"profile {profile}: API format must be openai or anthropic")
    if not api_key:
        raise LLMCallError(f"profile {profile}: missing API key")
    if not model:
        raise LLMCallError(f"profile {profile}: missing model name")
    return LLMProfile(
        name=name,
        api_format=api_format,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def _call_profile(
    profile: LLMProfile,
    prompt: str,
    *,
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: float | None,
) -> tuple[str, dict[str, Any]]:
    if profile.api_format == "anthropic":
        return _call_anthropic(profile, prompt, system, max_tokens, temperature, timeout_seconds)
    if profile.api_format == "openai":
        return _call_openai(profile, prompt, system, max_tokens, temperature, timeout_seconds)
    raise LLMCallError(f"unsupported API format: {profile.api_format}")


def _call_profile_with_tools(
    profile: LLMProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: float | None,
    tool_choice: str | dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if profile.api_format == "anthropic":
        return _call_anthropic_tools(
            profile,
            messages,
            tools,
            system,
            max_tokens,
            temperature,
            timeout_seconds,
            tool_choice,
        )
    if profile.api_format == "openai":
        return _call_openai_tools(
            profile,
            messages,
            tools,
            system,
            max_tokens,
            temperature,
            timeout_seconds,
            tool_choice,
        )
    raise LLMCallError(f"unsupported API format: {profile.api_format}")


def _call_anthropic(
    profile: LLMProfile,
    prompt: str,
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: float | None,
) -> tuple[str, dict[str, Any]]:
    url = _join_endpoint(
        profile.base_url or "https://api.anthropic.com",
        "/v1/messages",
        terminal="/messages",
    )
    payload: dict[str, Any] = {
        "model": profile.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": profile.api_key,
    }
    if "anthropic.com" not in url:
        headers["Authorization"] = f"Bearer {profile.api_key}"
    raw = _post_json(url, payload, headers, timeout_seconds)
    content = raw.get("content") or []
    if isinstance(content, list):
        text_parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") in {None, "text"}
        ]
        if not any(part.strip() for part in text_parts):
            text_parts = [
                str(item.get("thinking") or item.get("content") or "")
                for item in content
                if isinstance(item, dict)
            ]
        text = "\n".join(text_parts).strip()
    else:
        text = str(content).strip()
    return text or json.dumps(raw, ensure_ascii=False), raw


def _call_anthropic_tools(
    profile: LLMProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: float | None,
    tool_choice: str | dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = _join_endpoint(
        profile.base_url or "https://api.anthropic.com",
        "/v1/messages",
        terminal="/messages",
    )
    payload: dict[str, Any] = {
        "model": profile.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": _normalize_anthropic_messages(messages),
        "tools": _normalize_anthropic_tools(tools),
    }
    if system:
        payload["system"] = system
    if tool_choice:
        payload["tool_choice"] = _anthropic_tool_choice(tool_choice)
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": profile.api_key,
    }
    if "anthropic.com" not in url:
        headers["Authorization"] = f"Bearer {profile.api_key}"
    raw = _post_json(url, payload, headers, timeout_seconds)
    content = raw.get("content") or []
    if not isinstance(content, list):
        content = [{"type": "text", "text": str(content)}]
    return [block for block in content if isinstance(block, dict)], raw


def _call_openai(
    profile: LLMProfile,
    prompt: str,
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: float | None,
) -> tuple[str, dict[str, Any]]:
    url = _join_endpoint(
        profile.base_url or "https://api.openai.com/v1",
        "/chat/completions",
        terminal="/chat/completions",
    )
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": profile.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {profile.api_key}",
    }
    raw = _post_json(url, payload, headers, timeout_seconds)
    choices = raw.get("choices") or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict) and message.get("content"):
            return str(message["content"]).strip(), raw
        if choices[0].get("text"):
            return str(choices[0]["text"]).strip(), raw
        if isinstance(message, dict):
            finish_reason = choices[0].get("finish_reason")
            raise LLMCallError(f"empty chat content from model; finish_reason={finish_reason}")
    return json.dumps(raw, ensure_ascii=False), raw


def _call_openai_tools(
    profile: LLMProfile,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str | None,
    max_tokens: int,
    temperature: float,
    timeout_seconds: float | None,
    tool_choice: str | dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = _join_endpoint(
        profile.base_url or "https://api.openai.com/v1",
        "/chat/completions",
        terminal="/chat/completions",
    )
    openai_messages = _anthropic_messages_to_openai(messages, system)
    payload: dict[str, Any] = {
        "model": profile.model,
        "messages": openai_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "tools": _anthropic_tools_to_openai(tools),
    }
    normalized_choice = _openai_tool_choice(tool_choice)
    if normalized_choice is not None:
        payload["tool_choice"] = normalized_choice
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {profile.api_key}",
    }
    raw = _post_json(url, payload, headers, timeout_seconds)
    choices = raw.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return [{"type": "text", "text": json.dumps(raw, ensure_ascii=False)}], raw
    choice = choices[0]
    message = choice.get("message") or {}
    if not isinstance(message, dict):
        return [{"type": "text", "text": json.dumps(raw, ensure_ascii=False)}], raw
    content: list[dict[str, Any]] = []
    if message.get("content"):
        content.append({"type": "text", "text": str(message["content"])})
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        if not isinstance(function, dict):
            continue
        content.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"toolu_{len(content) + 1}"),
                "name": str(function.get("name") or ""),
                "input": _json_or_empty_object(function.get("arguments")),
            }
        )
    raw["finish_reason"] = choice.get("finish_reason")
    return content or [{"type": "text", "text": ""}], raw


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float | None,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    timeout = timeout_seconds if timeout_seconds is not None else _default_timeout_seconds()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMCallError(f"HTTP {exc.code}: {body[-1200:]}") from exc
    except urllib.error.URLError as exc:
        raise LLMCallError(str(exc.reason)) from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMCallError(f"invalid JSON response: {body[:500]}") from exc
    if not isinstance(parsed, dict):
        raise LLMCallError("response JSON is not an object")
    return parsed


def _join_endpoint(base_url: str, endpoint: str, *, terminal: str) -> str:
    clean = base_url.rstrip("/")
    if clean.endswith(terminal):
        return clean
    return clean + endpoint


def _default_timeout_seconds() -> float:
    raw = os.environ.get("API_TIMEOUT_MS") or os.environ.get("GRAPHYAGENT_API_TIMEOUT_MS")
    if not raw:
        return 90.0
    try:
        value = float(raw)
    except ValueError:
        return 90.0
    if value > 1000:
        value = value / 1000.0
    return max(1.0, value)


def _normalize_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role not in {"user", "assistant"}:
            role = "user"
        normalized.append({"role": role, "content": _normalize_anthropic_content(message.get("content"))})
    return normalized


def _normalize_anthropic_content(content: Any) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for block in content:
            if isinstance(block, dict):
                blocks.append(dict(block))
            else:
                blocks.append({"type": "text", "text": str(block)})
        return blocks
    return str(content or "")


def _normalize_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        schema = tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}}
        normalized.append(
            {
                "name": name,
                "description": str(tool.get("description") or ""),
                "input_schema": schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
            }
        )
    return normalized


def _anthropic_tool_choice(tool_choice: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(tool_choice, dict):
        return dict(tool_choice)
    value = str(tool_choice or "").strip()
    if value in {"auto", "any", "none"}:
        return {"type": value}
    if value:
        return {"type": "tool", "name": value}
    return {"type": "auto"}


def _anthropic_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in _normalize_anthropic_tools(tools):
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description") or "",
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
        )
    return converted


def _anthropic_messages_to_openai(
    messages: list[dict[str, Any]],
    system: str | None,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    if system:
        converted.append({"role": "system", "content": system})
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if isinstance(content, str):
            converted.append({"role": role if role in {"user", "assistant"} else "user", "content": content})
            continue
        if not isinstance(content, list):
            converted.append({"role": "user", "content": str(content or "")})
            continue
        if role == "assistant":
            text_parts = [
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            tool_calls = []
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tool_calls.append(
                    {
                        "id": str(block.get("id") or f"toolu_{len(tool_calls) + 1}"),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    }
                )
            msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts).strip() or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            converted.append(msg)
            continue
        pending_text = []
        for block in content:
            if not isinstance(block, dict):
                pending_text.append(str(block))
                continue
            if block.get("type") == "tool_result":
                if pending_text:
                    converted.append({"role": "user", "content": "\n".join(pending_text)})
                    pending_text = []
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id") or ""),
                        "content": _openai_tool_result_content(block.get("content")),
                    }
                )
            elif block.get("type") == "text":
                pending_text.append(str(block.get("text") or ""))
        if pending_text:
            converted.append({"role": "user", "content": "\n".join(pending_text)})
    return converted


def _openai_tool_choice(tool_choice: str | dict[str, Any] | None) -> str | dict[str, Any] | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "tool" and tool_choice.get("name"):
            return {"type": "function", "function": {"name": str(tool_choice["name"])}}
        if tool_choice.get("type") in {"auto", "none", "required"}:
            return str(tool_choice["type"])
        return dict(tool_choice)
    value = str(tool_choice or "").strip()
    if value in {"auto", "none", "required"}:
        return value
    if value == "any":
        return "required"
    if value:
        return {"type": "function", "function": {"name": value}}
    return None


def _anthropic_content_text_and_tools(content: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    text_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            tool_uses.append(
                {
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "input": block.get("input") if isinstance(block.get("input"), dict) else {},
                }
            )
        elif block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
    return "\n".join(part for part in text_parts if part).strip(), tool_uses


def _json_or_empty_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _openai_tool_result_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
