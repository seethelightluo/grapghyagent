"""Local settings backed by a .env file."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


API_KEY_FIELDS = [
    ("OPENAI_API_KEY", "OpenAI API Key"),
    ("ANTHROPIC_API_KEY", "Anthropic API Key"),
    ("ANTHROPIC_AUTH_TOKEN", "Anthropic Auth Token"),
    ("GEMINI_API_KEY", "Gemini API Key"),
    ("DEEPSEEK_API_KEY", "DeepSeek API Key"),
    ("DASHSCOPE_API_KEY", "DashScope API Key"),
    ("MOONSHOT_API_KEY", "Moonshot API Key"),
    ("ZHIPU_API_KEY", "Zhipu API Key"),
    ("MINIMAX_API_KEY", "MiniMax API Key"),
    ("CUSTOM_API_KEY", "Custom API Key"),
    ("CUSTOM_BASE_URL", "Custom Base URL"),
    ("ANTHROPIC_BASE_URL", "Anthropic Base URL"),
    ("OLLAMA_BASE_URL", "Ollama Base URL"),
]

API_KEY_NAMES = {key for key, _ in API_KEY_FIELDS}
ROUTING_ENV_KEYS = {
    "simple_model_ref": "GRAPHYAGENT_SIMPLE_MODEL_REF",
    "complex_model_ref": "GRAPHYAGENT_COMPLEX_MODEL_REF",
    "default_model_ref": "GRAPHYAGENT_DEFAULT_MODEL_REF",
}
PROFILE_ENV_KEYS = {
    "simple": {
        "api_format": "GRAPHYAGENT_SIMPLE_API_FORMAT",
        "api_key": "GRAPHYAGENT_SIMPLE_API_KEY",
        "base_url": "GRAPHYAGENT_SIMPLE_BASE_URL",
        "model": "GRAPHYAGENT_SIMPLE_MODEL",
        "model_ref": "GRAPHYAGENT_SIMPLE_MODEL_REF",
    },
    "complex": {
        "api_format": "GRAPHYAGENT_COMPLEX_API_FORMAT",
        "api_key": "GRAPHYAGENT_COMPLEX_API_KEY",
        "base_url": "GRAPHYAGENT_COMPLEX_BASE_URL",
        "model": "GRAPHYAGENT_COMPLEX_MODEL",
        "model_ref": "GRAPHYAGENT_COMPLEX_MODEL_REF",
    },
}
PROFILE_FORMATS = {"openai", "anthropic"}


def default_env_path() -> Path:
    return Path.cwd() / ".env"


def load_env_file(path: str | Path | None = None, *, override: bool = False) -> Path:
    env_path = Path(path) if path else default_env_path()
    values = read_env_file(env_path)
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return env_path


def read_settings(path: str | Path | None = None) -> dict[str, Any]:
    env_path = Path(path) if path else default_env_path()
    values = read_env_file(env_path)
    api_keys = []
    for key, label in API_KEY_FIELDS:
        process_value = os.environ.get(key, "")
        file_value = values.get(key, "")
        configured = bool(process_value or file_value)
        if file_value:
            source = "env_file"
        elif process_value:
            source = "process"
        else:
            source = "missing"
        api_keys.append({
            "key": key,
            "label": label,
            "configured": configured,
            "source": source,
            "masked": mask_secret(file_value or process_value),
        })
    routing = {
        name: values.get(env_key) or os.environ.get(env_key, "")
        for name, env_key in ROUTING_ENV_KEYS.items()
    }
    return {
        "env_path": str(env_path.resolve()),
        "api_keys": api_keys,
        "profiles": _read_profiles(values),
        "routing": routing,
    }


def update_settings(payload: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    env_path = Path(path) if path else default_env_path()
    updates: dict[str, str] = {}
    removals: set[str] = set()

    api_keys = payload.get("api_keys") or {}
    if isinstance(api_keys, dict):
        for key, value in api_keys.items():
            if key in API_KEY_NAMES and value:
                updates[key] = str(value).strip()

    clear_keys = payload.get("clear_keys") or []
    if isinstance(clear_keys, list):
        for key in clear_keys:
            if key in API_KEY_NAMES:
                removals.add(str(key))

    routing = payload.get("routing") or {}
    if isinstance(routing, dict):
        for name, env_key in ROUTING_ENV_KEYS.items():
            if name not in routing:
                continue
            value = str(routing.get(name) or "").strip()
            if value:
                updates[env_key] = value
                removals.discard(env_key)
            else:
                removals.add(env_key)

    profiles = payload.get("profiles") or {}
    if isinstance(profiles, dict):
        _collect_profile_updates(profiles, updates, removals)

    write_env_file(env_path, updates, removals)
    for key, value in updates.items():
        os.environ[key] = value
    for key in removals:
        os.environ.pop(key, None)
    return read_settings(env_path)


def read_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed:
            key, value = parsed
            values[key] = value
    return values


def write_env_file(path: str | Path, updates: dict[str, str], removals: set[str]) -> None:
    env_path = Path(path)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        parsed = parse_env_line(line)
        if not parsed:
            next_lines.append(line)
            continue
        key, _ = parsed
        if key in removals:
            seen.add(key)
            continue
        if key in updates:
            next_lines.append(f"{key}={format_env_value(updates[key])}")
            seen.add(key)
        else:
            next_lines.append(line)
            seen.add(key)
    for key, value in updates.items():
        if key not in seen and key not in removals:
            next_lines.append(f"{key}={format_env_value(value)}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, unquote_env_value(value.strip())


def unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if "#" in value and not value.startswith(("sk-", "sk_")):
        value = value.split("#", 1)[0].rstrip()
    return value


def format_env_value(value: str) -> str:
    if not value:
        return ""
    if any(ch.isspace() or ch in {'"', "'", "#"} for ch in value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}...{value[-4:]}"


def _read_profiles(values: dict[str, str]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for name, keys in PROFILE_ENV_KEYS.items():
        api_key = values.get(keys["api_key"]) or os.environ.get(keys["api_key"], "")
        profiles[name] = {
            "label": "简单任务" if name == "simple" else "复杂任务",
            "api_format": values.get(keys["api_format"]) or os.environ.get(keys["api_format"], ""),
            "base_url": values.get(keys["base_url"]) or os.environ.get(keys["base_url"], ""),
            "model": values.get(keys["model"]) or os.environ.get(keys["model"], ""),
            "model_ref": values.get(keys["model_ref"]) or os.environ.get(keys["model_ref"], ""),
            "api_key_configured": bool(api_key),
            "api_key_masked": mask_secret(api_key),
        }
    return profiles


def _collect_profile_updates(
    profiles: dict[str, Any],
    updates: dict[str, str],
    removals: set[str],
) -> None:
    for profile_name, raw_profile in profiles.items():
        if profile_name not in PROFILE_ENV_KEYS or not isinstance(raw_profile, dict):
            continue
        keys = PROFILE_ENV_KEYS[profile_name]
        api_format = _clean_profile_format(raw_profile.get("api_format"))
        model = str(raw_profile.get("model") or "").strip()
        for field in ("api_format", "base_url", "model"):
            if field == "api_format":
                value = api_format
            else:
                value = str(raw_profile.get(field) or "").strip()
            env_key = keys[field]
            if value:
                updates[env_key] = value
                removals.discard(env_key)
            elif field in raw_profile:
                removals.add(env_key)
        api_key = str(raw_profile.get("api_key") or "").strip()
        if api_key:
            updates[keys["api_key"]] = api_key
            removals.discard(keys["api_key"])
        elif raw_profile.get("clear_api_key"):
            removals.add(keys["api_key"])
        if api_format and model:
            updates[keys["model_ref"]] = f"{api_format}:{model}"
            removals.discard(keys["model_ref"])
        elif "api_format" in raw_profile or "model" in raw_profile:
            removals.add(keys["model_ref"])


def _clean_profile_format(value: Any) -> str:
    api_format = str(value or "").strip().lower()
    if not api_format:
        return ""
    if api_format not in PROFILE_FORMATS:
        raise ValueError(f"unsupported API format: {api_format}")
    return api_format
