# Verifiable Task Graph Concepts

## Overview

GraphyAgent's core innovation is the **verifiable task graph** — a DAG where every node carries typed I/O contracts, verification rules, gate conditions, and evidence pointers. This makes agent execution auditable, recoverable, and correctable.

## Node Anatomy

Every node in the graph has these fields:

| Field | Type | Purpose |
|-------|------|---------|
| `subject` | string | Short name for the node |
| `description` | string | What this node does |
| `input_spec` | dict | Typed keys this node expects as input |
| `output_spec` | dict | Typed keys this node must deliver |
| `input_example` | dict | Concrete sample input data |
| `output_example` | dict | Concrete sample output data |
| `necessity_audit` | string | Counterfactual: "If removed, what breaks? Verdict: indispensable/removable" |
| `verification_rule` | string | How to programmatically check correctness |
| `gate_condition` | string | Condition that must hold before downstream nodes run |
| `evidence_pointers` | list | File paths to execution logs |
| `blocked_by` | list | Upstream node IDs this node depends on |

## I/O Contracts

Unlike free-text descriptions, `input_spec` and `output_spec` define **typed key schemas**:

```python
output_spec = {
    "universities": "array of 10 strings",
    "disciplines": "array of 10 strings",
    "rankings": "array of objects with university, discipline, rank fields"
}
```

After execution, `verify_output()` checks:
- All specified keys exist in the output
- Types match (array, string, object, etc.)
- Structure is correct

This is **programmatic verification**, not LLM self-judgment. The model can't just say "looks right."

## Three-Level Recovery Pipeline

When a node's output fails verification, `TaskExecuteRecovery` runs automatically:

```
Level 1: Attempt — execute the node normally
    ↓ (if verify_output fails)
Level 2: Retry — re-execute with failure context injected into system prompt
    ↓ (if retry still fails)
Level 3: Decompose — break node into 2-3 sub-nodes as a sub-graph
```

**Key properties:**
- Upstream results are preserved — a failure in node 5 doesn't rebuild nodes 1-4
- Sub-graphs are true DAGs with their own edges and I/O specs
- Depth is configurable via `max_depth` (default: 2)
- Each sub-node gets its own independent memory.mdenis

## Gate-Controlled Execution

Gates prevent invalid data from propagating:

```python
gate_condition = "rankings.length == 10 AND each has overall_rank field"
```

Before a node executes, `TaskGateCheck` evaluates the condition against upstream output:
- **OPEN**: condition satisfied, node can run
- **CLOSED**: condition not satisfied, node is blocked

This means you don't discover downstream that upstream was wrong — execution stops at the gate.

## Necessity Audits

Every node must justify its existence:

```
necessity_audit = "If removed, no ranking data exists for downstream nodes.
                   The pipeline has nothing to process. Verdict: indispensable."
```

If a node's removal wouldn't affect the outcome, it gets **pruned**. This keeps the graph minimal.

## Evidence Chains

Every execution logs the full LLM prompt and response to `log/task_<id>_attempt<N>.md`. The `evidence_pointers` field tracks these:

```python
evidence_pointers = ["log/task_22_attempt1.md", "log/task_22_attempt2.md"]
```

This makes the entire execution traceable — you can audit what the model was toldscr and what it produced.

## Independent Auditor

The auditor is a **subagent with restricted tools** (Read, Glob, Grep, TaskGet, TaskList, TaskGateCheck — no Write, no Bash, no Agent). It:

1. Reads each node's `memory.md`
2. Checks `actual_output` against `output_example` (structural + value match)
3. Verifies evidence log files exist
4. Validates necessity audits and gate conditions
5. Produces per-node PASS/FAIL with confidence scores

Audit and execution are **separated** — the same model can't judge its own work.

## TaskWriteMemory

Memory files are generated **programmatically**, not by the LLM:

```python
# In task/tools.py
def _task_write_memory(task_id, output_dir, node_id):
    task = get_task(task_id)
    # ... builds memory.md with:
    # - json.dumps(task.actual_input, indent=2)
    # - json.dumps(task.actual_output, indent=2)
    # - verification_result, evidence_pointers, gate_status
```

This eliminates summarization bias — actual I/O is raw JSON, not LLM-described approximations.

## Depth Control

Decomposition depth is configurable:

```
TaskExecuteRecovery(task_id=..., max_depth=2)  # allow up to 2 levels of decomposition
TaskExecuteRecovery(task_id=..., max_depth=0)  # no decomposition — fail immediately
```

Default is 2. Each decomposition level creates a true sub-graph with independent node memory.

## Why This Matters

Standard agents rely on conversation context and LLM self-evaluation. When tasks get long:

- Context compresses, precision drops
- The model says "done" but can't prove it did the right thing
- One bad step poisons the entire pipeline
- There's no way to audit what happened

The verifiable graph addresses all of these by making execution **structured, checkable, and recoverable** at every node.
