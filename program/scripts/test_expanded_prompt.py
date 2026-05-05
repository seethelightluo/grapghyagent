"""Test: run the expanded prompt through the agent to verify full workflow execution.

This script invokes the agent with the expanded prompt that specifies each step
using the full framework features (TaskCreate, TaskExecuteRecovery, TaskGateCheck,
Agent for audit, MemorySave, etc.).

Usage:
    python scripts/test_expanded_prompt.py
"""
from __future__ import annotations

import json
import os
import sys
import io
from datetime import datetime
from pathlib import Path

# Fix Windows encoding for stdout
if sys.platform == "win32" and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cc_config import load_config
import agent as _agent

OUTPUT_DIR = ROOT.parent / "example" / "example1"


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
    _load_dotenv(ROOT / ".env")
    config = load_config()

    # Set model from env
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if "/" not in model:
        model = f"anthropic/{model}"
    config["model"] = model

    # Set API credentials
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if api_key:
        config["anthropic_api_key"] = api_key
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        config["anthropic_base_url"] = base_url

    # Auto-approve all tool calls for testing
    config["permission_mode"] = "accept-all"

    # Auto-approve AskUserQuestion (return "1" = first option = approve)
    import tools.interaction as _interaction
    _original_ask = _interaction.ask_input_interactive
    def _auto_approve(prompt, config, menu_text=None):
        # Auto-select first option for approval questions
        return "1"
    _interaction.ask_input_interactive = _auto_approve

    # Clear task store from previous runs
    tasks_file = ROOT / ".cheetahclaws" / "tasks.json"
    if tasks_file.exists():
        tasks_file.unlink()
        print("Cleared old task store")

    # Clear old test artifacts in example1
    import shutil
    for subdir in ["review", "log", "modules"]:
        d = OUTPUT_DIR / subdir
        if d.exists():
            shutil.rmtree(d)
            print(f"Cleared {d}")

    # Clear old output files that would confuse the auditor
    for old_file in OUTPUT_DIR.glob("*.txt"):
        old_file.unlink()
        print(f"Cleared {old_file}")
    # Clear old audit report (keep expanded_prompt.md)
    audit_file = OUTPUT_DIR / "audit_report.md"
    if audit_file.exists():
        audit_file.unlink()
        print(f"Cleared {audit_file}")

    # Load the expanded prompt
    prompt_path = OUTPUT_DIR / "expanded_prompt.md"
    if not prompt_path.exists():
        print(f"ERROR: Expanded prompt not found at {prompt_path}")
        return 1

    expanded_prompt = prompt_path.read_text(encoding="utf-8")

    # Load system prompt with evidence chain fragment
    fragment_path = ROOT / "prompts" / "fragments" / "evidence_chain.md"
    fragment = fragment_path.read_text(encoding="utf-8") if fragment_path.exists() else ""
    system_prompt = (
        "You are a precise task execution assistant that follows instructions exactly. "
        "You use the framework tools (TaskCreate, TaskExecuteRecovery, TaskGateCheck, "
        "Agent, MemorySave, Write, Read) to complete complex workflows. "
        "Never hardcode data — always use real LLM calls via the tools.\n\n"
        + fragment
    )

    # Run the agent
    print("=" * 70)
    print("TEST: Expanded Prompt → Agent Execution")
    print("=" * 70)
    print(f"Model: {config.get('model', '')}")
    print(f"Prompt length: {len(expanded_prompt)} chars")
    print()

    state = _agent.AgentState()
    event_count = 0
    tool_calls = []
    text_output = []

    t0 = datetime.now()

    for event in _agent.run(expanded_prompt, state, config, system_prompt):
        event_count += 1

        if isinstance(event, _agent.TextChunk):
            text_output.append(event.text)
            # Print progress
            if len(text_output) % 5 == 0:
                print(f"  [text chunk #{len(text_output)}]")

        elif isinstance(event, _agent.ToolStart):
            tool_calls.append({"name": event.name, "inputs": event.inputs})
            print(f"  [TOOL CALL] {event.name}")
            # Print first 200 chars of inputs
            inputs_str = json.dumps(event.inputs, ensure_ascii=False)[:200]
            print(f"    inputs: {inputs_str}")

        elif isinstance(event, _agent.ToolEnd):
            print(f"  [TOOL END] {event.name} (permitted={event.permitted})")
            result_preview = event.result[:200] if event.result else "(empty)"
            print(f"    result: {result_preview}")

        elif isinstance(event, _agent.TurnDone):
            print(f"  [TURN DONE] in={event.input_tokens}, out={event.output_tokens}")

        elif isinstance(event, _agent.PermissionRequest):
            print(f"  [PERMISSION] {event.description}")

    elapsed = (datetime.now() - t0).total_seconds()

    print(f"\n{'=' * 70}")
    print(f"SUMMARY")
    print(f"{'=' * 70}")
    print(f"Events: {event_count}")
    print(f"Tool calls: {len(tool_calls)}")
    print(f"Text chunks: {len(text_output)}")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Total input tokens: {state.total_input_tokens}")
    print(f"Total output tokens: {state.total_output_tokens}")

    # Print tool call summary
    if tool_calls:
        print(f"\nTool calls made:")
        for i, tc in enumerate(tool_calls, 1):
            print(f"  {i}. {tc['name']}")

    # Save full output
    output_log = {
        "timestamp": datetime.now().isoformat(),
        "model": config.get("model", ""),
        "elapsed_s": elapsed,
        "events": event_count,
        "tool_calls": [tc["name"] for tc in tool_calls],
        "text_length": sum(len(t) for t in text_output),
        "full_text": "".join(text_output)[:10000],
    }
    log_path = OUTPUT_DIR / "log" / "test_expanded_prompt.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(output_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nLog saved to: {log_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
