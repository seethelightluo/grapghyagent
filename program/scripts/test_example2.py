"""Test: run example2 expanded prompt through the agent to verify full evidence_chain skill.

Tests: TaskExecuteRecovery (Fix 1), auditor tool filtering (Fix 2),
TaskWriteMemory raw JSON (Fix 3), and all 8 skill phases.

Usage:
    python scripts/test_example2.py
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

OUTPUT_DIR = ROOT.parent / "example" / "example2"


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

    # Restrict tools to evidence_chain skill tools (no Research/WebSearch/WebFetch)
    # This tests Fix 2 tool filtering for the main agent too
    config["_allowed_tools"] = [
        "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskGateCheck",
        "TaskRetry", "TaskDecompose", "TaskExecuteRecovery", "TaskWriteMemory",
        "MemorySave", "MemorySearch", "MemoryList",
        "Agent", "Write", "Read", "Bash", "Glob", "Grep",
        "AskUserQuestion", "SendMessage", "CheckAgentResult", "ListAgentTasks",
    ]

    # Auto-approve AskUserQuestion (return "1" = first option = approve)
    import tools.interaction as _interaction
    _original_ask = _interaction.ask_input_interactive
    def _auto_approve(prompt, config, menu_text=None):
        return "1"
    _interaction.ask_input_interactive = _auto_approve

    # Clear task store from previous runs
    tasks_file = ROOT / ".cheetahclaws" / "tasks.json"
    if tasks_file.exists():
        tasks_file.unlink()
        print("Cleared old task store")

    # Clear old test artifacts in example2
    import shutil
    for subdir in ["review", "log", "modules"]:
        d = OUTPUT_DIR / subdir
        if d.exists():
            shutil.rmtree(d)
            print(f"Cleared {d}")

    # Clear old output files
    for old_file in OUTPUT_DIR.glob("*.txt"):
        old_file.unlink()
        print(f"Cleared {old_file}")
    audit_file = OUTPUT_DIR / "audit_report.md"
    if audit_file.exists():
        audit_file.unlink()
        print(f"Cleared {audit_file}")

    # Ensure directories exist
    for subdir in ["review", "log", "modules"]:
        (OUTPUT_DIR / subdir).mkdir(parents=True, exist_ok=True)

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
        "TaskWriteMemory, Agent, MemorySave, Write, Read) to complete complex workflows. "
        "Never hardcode data — always use real LLM calls via the tools.\n\n"
        + fragment
    )

    # Run the agent
    print("=" * 70)
    print("TEST: Example2 — University Rankings Evidence Chain")
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

        elif isinstance(event, _agent.ToolStart):
            tool_calls.append({"name": event.name, "inputs": event.inputs})
            print(f"  [TOOL] {event.name}")
            inputs_str = json.dumps(event.inputs, ensure_ascii=False)[:150]
            print(f"    in: {inputs_str}")

        elif isinstance(event, _agent.ToolEnd):
            result_preview = event.result[:200] if event.result else "(empty)"
            print(f"  [END]  {event.name} → {result_preview}")

        elif isinstance(event, _agent.TurnDone):
            print(f"  [TURN] in={event.input_tokens}, out={event.output_tokens}")

        elif isinstance(event, _agent.PermissionRequest):
            print(f"  [PERM] {event.description}")

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

    # ── Post-test verification ──
    print(f"\n{'=' * 70}")
    print(f"POST-TEST VERIFICATION")
    print(f"{'=' * 70}")

    checks_passed = 0
    checks_failed = 0

    # Check 1: TaskExecuteRecovery was used (not bypassed via Agent)
    ter_calls = [tc for tc in tool_calls if tc["name"] == "TaskExecuteRecovery"]
    if ter_calls:
        print(f"  [PASS] TaskExecuteRecovery used {len(ter_calls)} times (Fix 1 working)")
        checks_passed += 1
    else:
        print(f"  [FAIL] TaskExecuteRecovery never called — recovery path not tested")
        checks_failed += 1

    # Check 2: TaskWriteMemory was used (not TaskGet + Write for memory)
    twm_calls = [tc for tc in tool_calls if tc["name"] == "TaskWriteMemory"]
    if twm_calls:
        print(f"  [PASS] TaskWriteMemory used {len(twm_calls)} times (Fix 3 working)")
        checks_passed += 1
    else:
        print(f"  [FAIL] TaskWriteMemory never called — memory files may have LLM summaries")
        checks_failed += 1

    # Check 3: Auditor agent was spawned
    agent_calls = [tc for tc in tool_calls if tc["name"] == "Agent"]
    if agent_calls:
        print(f"  [PASS] Agent tool used {len(agent_calls)} times (audit agent spawned)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Agent tool never called — auditor not spawned")
        checks_failed += 1

    # Check 4: Memory files contain raw JSON
    modules_dir = OUTPUT_DIR / "modules"
    if modules_dir.exists():
        memory_files = list(modules_dir.glob("*/memory.md"))
        if memory_files:
            json_count = 0
            for mf in memory_files:
                content = mf.read_text(encoding="utf-8")
                if "```json" in content:
                    json_count += 1
            if json_count == len(memory_files):
                print(f"  [PASS] All {len(memory_files)} memory files contain raw JSON code blocks")
                checks_passed += 1
            else:
                print(f"  [FAIL] Only {json_count}/{len(memory_files)} memory files have JSON blocks")
                checks_failed += 1
        else:
            print(f"  [FAIL] No memory files found in modules/")
            checks_failed += 1
    else:
        print(f"  [FAIL] modules/ directory does not exist")
        checks_failed += 1

    # Check 5: Audit report exists
    audit_report = OUTPUT_DIR / "audit_report.md"
    if audit_report.exists():
        content = audit_report.read_text(encoding="utf-8")
        if "PASS" in content or "FAIL" in content:
            print(f"  [PASS] audit_report.md exists with PASS/FAIL verdicts")
            checks_passed += 1
        else:
            print(f"  [WARN] audit_report.md exists but no PASS/FAIL verdicts found")
            checks_failed += 1
    else:
        print(f"  [FAIL] audit_report.md not found")
        checks_failed += 1

    # Check 6: Result file exists
    result_file = OUTPUT_DIR / "result.txt"
    if result_file.exists():
        content = result_file.read_text(encoding="utf-8")
        sections = ["GRAPH STRUCTURE", "VERIFICATION", "GATE STATUS", "AUDIT", "JUDGMENT"]
        found = sum(1 for s in sections if s.upper() in content.upper())
        if found >= 3:
            print(f"  [PASS] result.txt exists with {found}/{len(sections)} expected sections")
            checks_passed += 1
        else:
            print(f"  [FAIL] result.txt missing sections ({found}/{len(sections)})")
            checks_failed += 1
    else:
        print(f"  [FAIL] result.txt not found")
        checks_failed += 1

    # Check 7: Evidence logs exist
    log_dir = OUTPUT_DIR / "log"
    if log_dir.exists():
        log_files = list(log_dir.glob("*.md"))
        if log_files:
            print(f"  [PASS] {len(log_files)} evidence log files found")
            checks_passed += 1
        else:
            print(f"  [FAIL] No evidence log files in log/")
            checks_failed += 1
    else:
        print(f"  [FAIL] log/ directory does not exist")
        checks_failed += 1

    print(f"\nResult: {checks_passed}/{checks_passed + checks_failed} checks passed")

    # Save full output
    output_log = {
        "timestamp": datetime.now().isoformat(),
        "model": config.get("model", ""),
        "elapsed_s": elapsed,
        "events": event_count,
        "tool_calls": [tc["name"] for tc in tool_calls],
        "text_length": sum(len(t) for t in text_output),
        "full_text": "".join(text_output)[:10000],
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
    }
    log_path = OUTPUT_DIR / "log" / "test_example2.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(output_log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nLog saved to: {log_path}")

    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
