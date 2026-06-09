"""Module-local skills used by the GraphyAgent runtime planner."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .module_registry import agent_module_names


def list_module_skills(module: str | None = None) -> list[dict[str, Any]]:
    modules = [module] if module else agent_module_names()
    skills = []
    for module_name in modules:
        path = _skill_path(module_name)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        skills.append({
            "module": module_name,
            "path": str(path),
            "summary": _first_paragraph(text),
            "recommended_next_modules": _recommended_modules(text),
            "text": text,
        })
    return skills


def read_module_skill(module: str) -> dict[str, Any]:
    skills = list_module_skills(module)
    if not skills:
        raise FileNotFoundError(f"module skill not found: {module}")
    return skills[0]


def recommend_next_modules(
    module: str,
    *,
    event: str = "",
    error: str = "",
) -> dict[str, Any]:
    skill = read_module_skill(module)
    text = skill["text"]
    candidates = list(skill["recommended_next_modules"])
    lowered = f"{event}\n{error}".lower()
    if "fail" in lowered or "error" in lowered or "失败" in lowered:
        failure_section = _section(text, "失败处理")
        candidates = _ordered_unique(_recommended_modules(failure_section) + candidates)
    if "save" in lowered or "保存" in lowered or "version" in lowered:
        candidates = _ordered_unique(["graph_saver"] + candidates)
    if "audit" in lowered or "审计" in lowered or "dataset" in lowered:
        candidates = _ordered_unique(["data_audit"] + candidates)
    return {
        "module": module,
        "event": event,
        "error": error,
        "next_modules": candidates,
        "skill_path": skill["path"],
    }


def _skill_path(module: str) -> Path:
    package_root = Path(__file__).resolve().parents[1]
    return package_root / module / "skill.md"


def _first_paragraph(text: str) -> str:
    lines = []
    in_heading = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            in_heading = True
            continue
        if not line:
            if lines:
                break
            continue
        if in_heading:
            lines.append(line)
    return " ".join(lines)


def _recommended_modules(text: str) -> list[str]:
    known = set(agent_module_names())
    matches = []
    for token in re.findall(r"`([a-z_]+)(?:\.[a-z_]+)?`|(?:^|[\s，。、])([a-z_]{3,})(?:[\s，。、]|$)", text):
        value = token[0] or token[1]
        if value in known:
            matches.append(value)
    return _ordered_unique(matches)


def _section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end]


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["list_module_skills", "read_module_skill", "recommend_next_modules"]
