"""Run a task through the CheetahClaws agent framework.

This script gives a task to the agent and records the full working process.
Unlike generate_city_famous_tree.py, this uses the actual agent loop with
all registered tools (TaskCreate, TaskExecuteRecovery, etc.).

Usage:
    python scripts/run_agent_task.py "your task description"
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cc_config import load_config
from agent import AgentState, run, TextChunk, ThinkingChunk, ToolStart, ToolEnd, TurnDone, PermissionRequest
from context import build_system_prompt


OUTPUT_DIR = ROOT.parent / "example" / "example1"
LOG_DIR = OUTPUT_DIR / "log"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"").strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def main() -> int:
    task_desc = (
        "搜寻世界上前10城市的10个出名的事物共100个，用树结构可视化展现出来，"
        "同时对这100个的重要性排序，排序结果生成txt文件"
    )
    if len(sys.argv) > 1:
        task_desc = " ".join(sys.argv[1:]).strip()

    # Setup
    _load_dotenv(ROOT / ".env")
    config = load_config()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if api_key:
        config["anthropic_api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        config["anthropic_base_url"] = base_url

    # Auto-approve all operations for autonomous execution
    config["permission_mode"] = "accept-all"
    config["_session_id"] = "example1"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build system prompt using the framework's prompt system
    system_prompt = build_system_prompt(config)

    print("=" * 70)
    print("RUNNING TASK THROUGH AGENT FRAMEWORK")
    print("=" * 70)
    print(f"Task: {task_desc}")
    print(f"Model: {config['model']}")
    print(f"System prompt length: {len(system_prompt)} chars")
    print()

    # Create agent state
    state = AgentState()

    # Run the agent
    all_events: list[dict] = []
    text_output: list[str] = []
    tool_calls_log: list[dict] = []
    turn_count = 0
    t_start = time.time()

    for event in run(
        user_message=task_desc,
        state=state,
        config=config,
        system_prompt=system_prompt,
        depth=0,
    ):
        ts = datetime.now().isoformat()

        if isinstance(event, TextChunk):
            text_output.append(event.text)
            all_events.append({"type": "text", "text": event.text, "ts": ts})

        elif isinstance(event, ThinkingChunk):
            all_events.append({"type": "thinking", "text": event.text, "ts": ts})

        elif isinstance(event, ToolStart):
            tool_calls_log.append({
                "name": event.name,
                "inputs": event.inputs,
                "ts": ts,
            })
            all_events.append({
                "type": "tool_start",
                "name": event.name,
                "inputs": event.inputs,
                "ts": ts,
            })
            print(f"  [Tool] {event.name}({list(event.inputs.keys())[:3]})")

        elif isinstance(event, ToolEnd):
            all_events.append({
                "type": "tool_end",
                "name": event.name,
                "result": event.result[:2000],  # truncate for log
                "permitted": event.permitted,
                "ts": ts,
            })

        elif isinstance(event, TurnDone):
            turn_count += 1
            all_events.append({
                "type": "turn_done",
                "in_tokens": event.input_tokens,
                "out_tokens": event.output_tokens,
                "ts": ts,
            })
            print(f"  [Turn {turn_count}] in={event.input_tokens}, out={event.output_tokens}")

        elif isinstance(event, PermissionRequest):
            event.granted = True  # auto-approve
            all_events.append({
                "type": "permission",
                "description": event.description,
                "granted": True,
                "ts": ts,
            })

    duration = time.time() - t_start

    # ── Write logs ────────────────────────────────────────────────────────

    print(f"\nCompleted in {duration:.1f}s, {turn_count} turns")

    # Write full event log
    event_log_path = LOG_DIR / "agent_events.json"
    event_log_path.write_text(
        json.dumps(all_events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Event log: {event_log_path}")

    # Write tool calls summary
    tool_summary_path = LOG_DIR / "agent_tool_calls.json"
    tool_summary_path.write_text(
        json.dumps(tool_calls_log, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Tool calls: {tool_summary_path}")

    # Write agent's text output
    full_text = "".join(text_output)
    text_output_path = LOG_DIR / "agent_text_output.md"
    text_output_path.write_text(
        f"# Agent Text Output\n\n"
        f"Task: {task_desc}\n"
        f"Model: {config['model']}\n"
        f"Duration: {duration:.1f}s\n"
        f"Turns: {turn_count}\n\n"
        f"---\n\n{full_text}",
        encoding="utf-8",
    )
    print(f"  Text output: {text_output_path}")

    # Write result.txt
    result_lines = []
    result_lines.append("=" * 70)
    result_lines.append("AGENT FRAMEWORK EXECUTION — RESULT")
    result_lines.append("=" * 70)
    result_lines.append("")
    result_lines.append(f"Task: {task_desc}")
    result_lines.append(f"Model: {config['model']}")
    result_lines.append(f"Timestamp: {datetime.now().isoformat()}")
    result_lines.append(f"Duration: {duration:.1f}s")
    result_lines.append(f"Turns: {turn_count}")
    result_lines.append(f"Total events: {len(all_events)}")
    result_lines.append(f"Tool calls: {len(tool_calls_log)}")
    result_lines.append("")

    result_lines.append("-" * 70)
    result_lines.append("1. TOOL CALLS SUMMARY")
    result_lines.append("-" * 70)
    result_lines.append("")
    for i, tc in enumerate(tool_calls_log, 1):
        result_lines.append(f"  {i}. {tc['name']}")
        if tc.get("inputs"):
            for k, v in tc["inputs"].items():
                val_str = json.dumps(v, ensure_ascii=False)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                result_lines.append(f"     {k}: {val_str}")
    result_lines.append("")

    result_lines.append("-" * 70)
    result_lines.append("2. AGENT TEXT OUTPUT")
    result_lines.append("-" * 70)
    result_lines.append("")
    result_lines.append(full_text[:10000])
    if len(full_text) > 10000:
        result_lines.append(f"\n... ({len(full_text)} chars total, truncated)")
    result_lines.append("")

    result_lines.append("-" * 70)
    result_lines.append("3. FILE MANIFEST")
    result_lines.append("-" * 70)
    result_lines.append("")
    result_lines.append("  result.txt — this file")
    result_lines.append("  log/agent_events.json — full event log (all events)")
    result_lines.append("  log/agent_tool_calls.json — tool calls summary")
    result_lines.append("  log/agent_text_output.md — agent's text output")
    result_lines.append("")

    result_path = OUTPUT_DIR / "result.txt"
    result_path.write_text("\n".join(result_lines), encoding="utf-8")
    print(f"  Result: {result_path}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
