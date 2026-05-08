"""Test decompose depth and sub-graph display — no real LLM needed.

Tests:
  1. max_depth=0 prevents decomposition
  2. max_depth=2 allows one level of decompose
  3. Sub-node memory.md files generated with correct paths
  4. Parent task's sub_graph field populated
  5. TaskWriteMemory includes Sub-Graph section
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from task.recovery import execute_with_recovery, verify_output
from task.store import create_task, get_task, update_task, clear_all_tasks
from task.tools import _task_write_memory


# ── Fake LLM responses ─────────────────────────────────────────────────────

def make_decompose_response(sub_tasks):
    """Build a realistic decompose LLM response with edge chain."""
    clean_edges = []
    for s in sub_tasks:
        blocked = s.get("blocked_by", [])
        for b in blocked:
            for prev in sub_tasks:
                if prev["id"] == b:
                    port = list(s.get("input_spec", {}).keys())[0] if s.get("input_spec") else "data"
                    clean_edges.append({"from": b, "to": s["id"], "port": port})
    return json.dumps({"sub_tasks": sub_tasks, "edges": clean_edges})


def _make_sub_def(id_, name, blocked_by=None, in_spec=None, out_spec=None):
    return {
        "id": id_, "name": name,
        "description": f"Do {name}",
        "input_spec": in_spec or {"data": {"type": "array"}},
        "output_spec": out_spec or {"output": {"type": "string"}},
        "input_example": {"data": [1, 2]},
        "output_example": {"output": "result"},
        "necessity_audit": f"If removed, {name} not done. Verdict: indispensable.",
        "verification_rule": "output must be a non-empty string",
        "gate_condition": "output exists",
        "blocked_by": blocked_by or [],
    }


# ── Test helper ────────────────────────────────────────────────────────────

def create_test_task(suffix=""):
    return create_task(
        f"Test task {suffix}",
        f"Description for test {suffix}",
        input_spec={"data": "array"},
        output_spec={"result": "string"},
        output_example={"result": "sample"},
        verification_rule="result must be a non-empty string",
        gate_condition="result exists",
        necessity_audit="Indispensable. Verdict: indispensable.",
    )


# ── Test 1: max_depth=0 prevents decomposition ─────────────────────────────

def test_max_depth_zero():
    print("\n-- Test 1: max_depth=0 prevents decomposition --")
    clear_all_tasks()
    task = create_test_task("depth0")

    call_count = [0]

    def fake_call_llm(system, prompt, config):
        call_count[0] += 1
        # First call (attempt): fail. Should not reach deeper calls.
        return json.dumps({"wrong_key": "bad"}), {"model": "test"}

    with patch("task.recovery.call_llm", fake_call_llm):
        result = execute_with_recovery(
            task_id=task.id,
            actual_inputs={"data": [1, 2, 3]},
            system_prompt="You are a tester.",
            config={"model": "test"},
            depth=0,
            max_depth=0,
        )

    print(f"  Recovery: {result.get('recovery')}, LLM calls: {call_count[0]}")
    # With max_depth=0, attempt fails, retry fails (same bad output), then
    # decompose is blocked by depth guard. Recovery should be 'max_depth'.
    assert result.get("recovery") in (
        "max_depth", "retry_failed"
    ), f"Unexpected recovery: {result.get('recovery')}"
    print("  PASS: max_depth=0 prevents decomposition")
    clear_all_tasks()


# ── Test 2: max_depth=2 decompose generates sub-graph + memorieir ──────────

def test_max_depth_two():
    print("\n-- Test 2: max_depth=2 decompose generates sub-graph + memories --")
    clear_all_tasks()
    task = create_test_task("depth2")

    sub_defs = [
        _make_sub_def("sub_1", "Sub task 1"),
        _make_sub_def("sub_2", "Sub task 2", blocked_by=["sub_1"],
                      in_spec={"partial": {"type": "array"}},
                      out_spec={"result": {"type": "string"}}),
    ]

    # Response sequence:
    #   [0] attempt: fail
    #   [1] retry: fail
    #   [2] decompose: LLM returns sub-graph
    #   [3] sub_1 execute: pass
    #   [4] sub_2 execute: pass
    llm_responses = [
        json.dumps({"wrong_key": "bad"}),
        json.dumps({"wrong_key": "still bad"}),
        make_decompose_response(sub_defs),
        json.dumps({"output": "part one done"}),
        json.dumps({"result": "merged output"}),
    ]
    call_idx = [0]

    def sequential_llm(system, prompt, config):
        i = call_idx[0]
        call_idx[0] += 1
        idx = min(i, len(llm_responses) - 1)
        return llm_responses[idx], {"model": "test", "duration_s": 0.1}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = tmpdir

        with patch("task.recovery.call_llm", sequential_llm):
            result = execute_with_recovery(
                task_id=task.id,
                actual_inputs={"data": [1, 2, 3]},
                system_prompt="You are a tester.",
                config={"model": "test"},
                depth=0,
                max_depth=2,
                output_dir=output_dir,
            )

        print(f"  Recovery: {result.get('recovery')}, LLM calls: {call_idx[0]}")
        print(f"  Sub-tasks: {len(result.get('sub_tasks', []))}")

        # Check parent sub_graphur
        parent = get_task(task.id)
        assert parent.sub_graph, "parent.sub_graph should be populated"
        assert "sub_tasks" in parent.sub_graph
        assert len(parent.sub_graph["sub_tasks"]) == 2
        print(f"  Parent sub_graph: {len(parent.sub_graph['sub_tasks'])} nodes, "
              f"{len(parent.sub_graph.get('edges', []))} edges")

        # Check sub-node memory filesorn
        modules_dir = Path(output_dir) / "modules"
        sub_memories = list(modules_dir.glob("node_*/sub_graph/*/memory.md"))
        print(f"  Sub-node memories: {len(sub_memories)}")
        for sm in sub_memories:
            content = sm.read_text(encoding="utf-8")
            hase_actual = "Actual I/O" in content
            hase_sub = "Sub-Node Memory" in content
            print(f"    {sm.name} @ {sm.parent.name}: "
                  f"Sub-Node header={'Y' if hase_sub else 'N'}, "
                  f"Actual I/O={'Y' if hase_actual else 'N'} "
                  f"({len(content)} chars)")
            assert hase_sub, "Missing 'Sub-Node Memory' header"
            assert hase_actual, "Missing 'Actual I/O' section"

        assert len(sub_memories) == 2, f"Expected 2, got {len(sub_memories)}"
        print("  PASS: max_depth=2 decompose creates sub-graph + sub-memories")

    clear_all_tasks()


# ── Test 3: TaskWriteMemory includes Sub-Graph section ─────────────────────

def test_task_write_memory_with_sub_graph():
    print("\n-- Test 3: TaskWriteMemory includes Sub-Graph section --")
    clear_all_tasks()
    task = create_test_task("memory")

    sub_graph = {
        "sub_tasks": [
            {"id": "sub_1", "name": "Step A", "description": "First half"},
            {"id": "sub_2", "name": "Step B", "description": "Second half"},
        ],
        "edges": [{"from": "sub_1", "to": "sub_2", "port": "data"}],
    }
    update_task(
        task.id, sub_graph=sub_graph,
        actual_output={"result": "final"},
        verification_result="all checks passed",
        acceptance_status="pass", gate_status="open",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        result = _task_write_memory(task.id, tmpdir, "node_1")
        print(f"  {result}")

        mem_path = Path(tmpdir) / "modules" / "node_1" / "memory.md"
        content = mem_path.read_text(encoding="utf-8")

        assert "Sub-Graph" in content, "Missing Sub-Graph section"
        assert "sub_1" in content
        assert "Step A" in content
        # Check the sub-graph JSON block exists
        assert "```json" in content, "Missing JSON code block"
        print(f"  memory.md: {len(content)} chars, Sub-Graph section present")
        print("  PASS: memory.md Sub-Graph section renders correctly")

    clear_all_tasks()


# ── Test 4: verify_output string-valued spec (Fix 1 regression) ────────────

def test_verify_output_string_spec():
    print("\n-- Test 4: verify_output with string-valued output_spec --")

    result = verify_output(
        {"universities": ["MIT", "Stanford"], "disciplines": ["CS", "Math"]},
        {"universities": "array of strings", "disciplines": "array of strings"},
        {},
        "must have universities and disciplines",
    )
    assert result["passed"], f"Expected pass: {result}"
    print(f"  Pass: {result['verification_result']}")

    result2 = verify_output(
        {"universities": ["MIT"]},
        {"universities": "array", "disciplines": "array"},
        {},
        "must have both",
    )
    assert not result2["passed"]
    assert "disciplines" in result2["verification_result"]
    print(f"  Missing key detected: {result2['verification_result']}")
    print("  PASS: string-valued spec works (Fix 1 verified)")


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("DECOMPOSE DEPTH + SUB-GRAPH DISPLAY TESTS")
    print("=" * 60)

    test_max_depth_zero()
    test_max_depth_two()
    test_task_write_memory_with_sub_graph()
    test_verify_output_string_spec()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
