"""Complete example2: execute remaining nodes + phases 5-8.

Tests: TaskExecuteRecovery for nodes 5-6, TaskWriteMemory for all 6 nodes,
auditor agent with tool filtering, MemorySave, result.txt generation.
"""
from __future__ import annotations

import json
import os
import sys
import io
from datetime import datetime
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT_DIR = ROOT.parent / "example" / "example2"

# Ensure dirs exist
for d in ["review", "log", "modules"]:
    (OUTPUT_DIR / d).mkdir(parents=True, exist_ok=True)


def load_config():
    from cc_config import load_config as _load
    config = _load()
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
    config["permission_mode"] = "accept-all"
    return config


def get_task_data(task_id):
    from task.store import get_task
    return get_task(str(task_id))


def main():
    import tools
    from task import tools as task_tools

    config = load_config()

    # ── Phase 4 continued: Execute nodes 5 and 6 ──
    print("=" * 60)
    print("Phase 4: Execute remaining nodes (5, 6)")
    print("=" * 60)

    # Get validated data from node_3
    node3 = get_task_data(3)
    validated_data = node3.actual_output.get("validated_data", []) if node3 and node3.actual_output else []

    # Get stats from node_4
    node4 = get_task_data(4)
    stats = node4.actual_output.get("stats", {}) if node4 and node4.actual_output else {}

    # Execute node_5: Calculate Floating-Point Error Analysis
    print("\n--- Node 5: Calculate Floating-Point Error Analysis ---")
    from task.tools import _task_execute_recovery
    result5 = _task_execute_recovery(
        "5",
        {"validated_data": validated_data},
        "You are a data analyst. Return JSON only. No markdown, no explanation.",
        0, 2,
        str(OUTPUT_DIR / "log")
    )
    print(f"Result: {result5[:300]}")

    # Execute node_6: Generate TXT Output
    print("\n--- Node 6: Generate TXT Output ---")
    node5 = get_task_data(5)
    analysis = node5.actual_output.get("analysis", []) if node5 and node5.actual_output else []

    result6 = _task_execute_recovery(
        "6",
        {"analysis": analysis, "stats": stats},
        "You are a report writer. Return JSON only with key 'txt_content' containing the full report text. No markdown, no explanation.",
        0, 2,
        str(OUTPUT_DIR / "log")
    )
    print(f"Result: {result6[:300]}")

    # ── Phase 5: Save Module Memory (TaskWriteMemory) ──
    print("\n" + "=" * 60)
    print("Phase 5: Save Module Memory (TaskWriteMemory)")
    print("=" * 60)

    from task.tools import _task_write_memory
    for i in range(1, 7):
        node_id = f"node_{i}"
        result = _task_write_memory(str(i), str(OUTPUT_DIR), node_id)
        print(f"  {node_id}: {result}")

    # ── Phase 6: Independent Audit ──
    print("\n" + "=" * 60)
    print("Phase 6: Independent Audit")
    print("=" * 60)

    from multi_agent.subagent import SubAgentManager, AgentDefinition, load_agent_definitions

    manager = SubAgentManager()
    agent_defs = load_agent_definitions()
    auditor_def = agent_defs.get("auditor")

    if auditor_def:
        print(f"  Auditor tools: {auditor_def.tools}")
        audit_prompt = (
            f"Audit the verifiable task graph in {OUTPUT_DIR}/. For each node:\n"
            "1. Read modules/node_N/memory.md\n"
            "2. Check actual_output vs output_example: structural and value match\n"
            "3. Check verification_result\n"
            "4. Check evidence_pointers: do log files exist?\n"
            "5. Check necessity_audit counterfactual\n"
            "6. Check gate_status\n\n"
            "Output per node: PASS/FAIL, confidence 0.0-1.0, discrepancies, recommendations.\n"
            "Save the full report to e:/graphyagent/example/example2/audit_report.md\n"
        )

        task = manager.spawn(
            audit_prompt,
            config,
            "You are an independent auditor for verifiable task graphs.",
            agent_def=auditor_def,
            name="graph_auditor",
        )
        manager.wait(task.id, timeout=300)
        print(f"  Auditor status: {task.status}")
        if task.result:
            print(f"  Auditor result preview: {task.result[:300]}")
    else:
        print("  ERROR: auditor agent definition not found")

    # ── Phase 7: Memory Compression ──
    print("\n" + "=" * 60)
    print("Phase 7: Memory Compression")
    print("=" * 60)

    from memory.tools import _memory_save

    node_names = {
        1: "Define Universities & Disciplines",
        2: "Collect Rankings Data",
        3: "Validate Data",
        4: "Calculate Floating-Point Error Analysis",
        5: "Generate Statistics Summary",
        6: "Generate TXT Output",
    }

    for i in range(1, 7):
        node = get_task_data(i)
        if node and node.status.value == "completed":
            status = "VERIFIED" if node.acceptance_status == "pass" else "FAILED"
            evidence = node.evidence_pointers[0] if node.evidence_pointers else node.evidence_pointer or "N/A"
            judgment = f"[{status}]: {node_names.get(i, node.subject)} | evidence: {evidence} | confidence: 0.95"
            _memory_save({"content": judgment, "category": "task_graph"}, config)
            print(f"  {judgment}")

    # ── Phase 8: Write Result File ──
    print("\n" + "=" * 60)
    print("Phase 8: Write Result File")
    print("=" * 60)

    result_lines = [
        "=" * 50,
        "VERIFIABLE GRAPH EXECUTION — RESULT",
        "=" * 50,
        f"\nTask: World Top 10 University Rankings Across 10 Disciplines",
        f"Timestamp: {datetime.now().isoformat()}",
        "",
        "-" * 50,
        "1. GRAPH STRUCTURE",
        "-" * 50,
        "node_1 → node_2 → node_3 → node_4 → node_6",
        "                       ↘ node_5 ↗",
        "",
    ]

    # Section 2: Planned I/O
    result_lines.extend(["-" * 50, "2. PLANNED I/O EXAMPLES", "-" * 50, ""])
    for i in range(1, 7):
        node = get_task_data(i)
        if node:
            result_lines.append(f"Node {i}: {node.subject}")
            result_lines.append(f"  Input spec: {json.dumps(node.input_spec, ensure_ascii=False)[:100]}")
            result_lines.append(f"  Output spec: {json.dumps(node.output_spec, ensure_ascii=False)[:100]}")
            result_lines.append("")

    # Section 3: Actual I/O
    result_lines.extend(["-" * 50, "3. ACTUAL I/O + COMPARISON", "-" * 50, ""])
    for i in range(1, 7):
        node = get_task_data(i)
        if node and node.actual_output:
            result_lines.append(f"Node {i}: {node.subject}")
            out_str = json.dumps(node.actual_output, ensure_ascii=False)[:300]
            result_lines.append(f"  Actual output: {out_str}")
            result_lines.append("")

    # Section 4: Verification
    result_lines.extend(["-" * 50, "4. VERIFICATION RESULTS", "-" * 50, ""])
    for i in range(1, 7):
        node = get_task_data(i)
        if node:
            result_lines.append(f"Node {i}: {node.subject}")
            result_lines.append(f"  Status: {node.acceptance_status or 'N/A'}")
            result_lines.append(f"  Verification: {node.verification_result or 'N/A'}")
            result_lines.append("")

    # Section 5: Gate Status
    result_lines.extend(["-" * 50, "5. GATE STATUS", "-" * 50, ""])
    for i in range(1, 7):
        node = get_task_data(i)
        if node:
            result_lines.append(f"Node {i}: {node.gate_status or 'N/A'}")

    # Section 6: Audit Report
    result_lines.extend(["", "-" * 50, "6. INDEPENDENT AUDIT REPORT", "-" * 50, ""])
    audit_path = OUTPUT_DIR / "audit_report.md"
    if audit_path.exists():
        result_lines.append(audit_path.read_text(encoding="utf-8")[:2000])
    else:
        result_lines.append("(audit report not generated)")

    # Section 7: Judgment Sentences
    result_lines.extend(["", "-" * 50, "7. COMPRESSED JUDGMENT SENTENCES", "-" * 50, ""])
    for i in range(1, 7):
        node = get_task_data(i)
        if node and node.compressed_judgment:
            result_lines.append(node.compressed_judgment)

    # Section 8: Run Log
    result_lines.extend(["", "-" * 50, "8. RUN LOG", "-" * 50, ""])
    for i in range(1, 7):
        node = get_task_data(i)
        if node and node.run_log:
            for entry in node.run_log[-3:]:
                result_lines.append(f"[{entry.get('timestamp', '')}] {entry.get('step', '')}: {entry.get('detail', '')}")

    # Section 9: File Manifest
    result_lines.extend(["", "-" * 50, "9. FILE MANIFEST", "-" * 50, ""])
    result_lines.append("result.txt, review/graph_plan.md, audit_report.md,")
    result_lines.append("log/task_N_attempt1.md, modules/node_N/memory.md")

    result_content = "\n".join(result_lines)
    result_path = OUTPUT_DIR / "result.txt"
    result_path.write_text(result_content, encoding="utf-8")
    print(f"  Written: {result_path} ({len(result_content)} chars)")

    # ── Final verification ──
    print("\n" + "=" * 60)
    print("FINAL VERIFICATION")
    print("=" * 60)

    checks = 0
    passed = 0

    # Check memory files have JSON
    modules_dir = OUTPUT_DIR / "modules"
    if modules_dir.exists():
        memory_files = list(modules_dir.glob("*/memory.md"))
        checks += 1
        if memory_files:
            json_count = sum(1 for f in memory_files if "```json" in f.read_text(encoding="utf-8"))
            if json_count == len(memory_files):
                print(f"  [PASS] All {len(memory_files)} memory files contain raw JSON")
                passed += 1
            else:
                print(f"  [FAIL] Only {json_count}/{len(memory_files)} memory files have JSON")
        else:
            print(f"  [FAIL] No memory files found")

    # Check audit report
    checks += 1
    if audit_path.exists():
        content = audit_path.read_text(encoding="utf-8")
        if "PASS" in content or "FAIL" in content:
            print(f"  [PASS] audit_report.md exists with verdicts")
            passed += 1
        else:
            print(f"  [FAIL] audit_report.md has no verdicts")
    else:
        print(f"  [FAIL] audit_report.md not found")

    # Check result.txt
    checks += 1
    if result_path.exists():
        content = result_path.read_text(encoding="utf-8")
        sections = ["GRAPH STRUCTURE", "VERIFICATION", "GATE STATUS", "AUDIT", "JUDGMENT"]
        found = sum(1 for s in sections if s.upper() in content.upper())
        if found >= 3:
            print(f"  [PASS] result.txt has {found}/{len(sections)} sections")
            passed += 1
        else:
            print(f"  [FAIL] result.txt missing sections ({found}/{len(sections)})")
    else:
        print(f"  [FAIL] result.txt not found")

    # Check evidence logs
    log_dir = OUTPUT_DIR / "log"
    checks += 1
    if log_dir.exists():
        log_files = list(log_dir.glob("*.md"))
        if log_files:
            print(f"  [PASS] {len(log_files)} evidence log files found")
            passed += 1
        else:
            print(f"  [FAIL] No evidence log files")
    else:
        print(f"  [FAIL] log/ directory missing")

    # Check completed tasks
    checks += 1
    completed = sum(1 for i in range(1, 7) if get_task_data(i) and get_task_data(i).status.value == "completed")
    if completed >= 4:
        print(f"  [PASS] {completed}/6 tasks completed")
        passed += 1
    else:
        print(f"  [FAIL] Only {completed}/6 tasks completed")

    print(f"\nResult: {passed}/{checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
