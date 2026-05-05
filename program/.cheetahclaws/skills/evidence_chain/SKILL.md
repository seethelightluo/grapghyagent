---
name: evidence_chain
description: Build a verifiable task graph with IO contracts, necessity audits, gate conditions, evidence chains, user review, and independent audit.
triggers: [/evidence_chain, evidence chain, audit workflow, verifiable graph]
allowed-tools: [TaskCreate, TaskUpdate, TaskGet, TaskList, TaskGateCheck, TaskRetry, TaskDecompose, TaskExecuteRecovery, TaskWriteMemory, MemorySave, MemorySearch, MemoryList, Agent, Write, Read, Bash, AskUserQuestion]
when_to_use: Use for complex tasks that need recursive decomposition, IO contracts, gate-controlled execution, and evidence tracking.
argument-hint: "[task description]"
user-invocable: true
context: inline
---
# Verifiable Task Graph Protocol

You are building a **trustworthy, auditable task graph**. Follow these phases strictly.

**CRITICAL RULE**: NEVER fabricate data. All `actual_input` and `actual_output` values MUST come from `TaskGet` after execution. Do NOT copy from `output_example`.

---

## Phase 1: Graph Decomposition

**Tool: internal reasoning**

Decompose the user's task into a DAG. For each node define:
- `subject` / `description`
- `input_spec` / `output_spec`: typed I/O contracts
- `input_example` / `output_example`: **concrete sample data** (real data, not descriptions)
- `necessity_claim`: why this node exists
- `necessity_audit`: counterfactual — "If I remove this node, [consequence]. **Verdict: indispensable / removable**"
- `verification_rule`: how to check correctness
- `gate_condition`: downstream-blocking condition
- `evidence_pointers`: where proof will live (e.g. `["log/task_7_attempt1.md"]`)

**Prune ruthlessly**: if removing a node still achieves the goal, delete it.

---

## Phase 2: Graph Review — PAUSE FOR USER APPROVAL

**Tools: `Write`, `AskUserQuestion`**

1. Write `<output_dir>/review/graph_plan.md` with: task description, graph overview, per-node details (I/O contract, examples, necessity audit, verification rule, gate), edges, Mermaid flowchart.
2. **PAUSE**: `AskUserQuestion` — approve or request changes.
3. If changes requested: back to Phase 1, regenerate, pause again.
4. Only after approval: proceed.

---

## Phase 3: Create Tasks

**Tools: `TaskCreate`, `TaskUpdate`**

For each node, call `TaskCreate` with ALL fields (subject, description, input_spec, output_spec, input_example, output_example, necessity_claim, necessity_audit, verification_rule, gate_condition, evidence_pointers).

Wire dependencies: `TaskUpdate(task_id, blocked_by=[...])`.

---

## Phase 4: Execute with Gate Control + Recovery (Loop)

**Tools: `TaskGateCheck`, `TaskExecuteRecovery`, `TaskGet`**

This phase has an **internal loop** with up to 2 rounds:

### Round 1: Direct Execution

For each node in topological order:

1. **Gate check**: `TaskGateCheck(task_id)` — if BLOCKED, skip.
2. **Resolve inputs**: gather actual_output from upstream via `TaskGet`.
3. **Execute**:
   ```
   TaskExecuteRecovery(
     task_id=<id>,
     actual_inputs=<resolved inputs>,
     system_prompt="You are a data expert. Return JSON only.",
     log_dir="<output_dir>/log/"
   )
   ```
   The framework automatically: calls LLM → verifies → retries if failed → decomposes if retry failed → writes evidence logs.

4. **Read back**: `TaskGet(task_id)` — get actual_input, actual_output, verification_result, gate_status, acceptance_status.

### Round 2: Retry Failed Nodes (if auditor finds issues in Phase 5)

If Phase 5 audit returns FAIL for any node:

1. For each failed node, extract the auditor's **discrepancies** and **recommendations**.
2. Re-execute ONLY the failed nodes with audit failure context injected:
   ```
   TaskExecuteRecovery(
     task_id=<failed_id>,
     actual_inputs=<same inputs>,
     system_prompt="You are a data expert. The previous output failed audit. Issues: <auditor discrepancies>. Fix ALL issues. Return JSON only.",
     log_dir="<output_dir>/log/"
   )
   ```
3. Read back updated results via `TaskGet`.
4. Go to Phase 4b (re-save memory) → Phase 5 (re-audit).

### Round 3: Decompose Failed Nodes (if Round 2 still fails)

If Phase 5 audit STILL returns FAIL after Round 2:

1. For each still-failed node, use `TaskDecompose` to break it into sub-tasks:
   ```
   TaskDecompose(
     task_id=<failed_id>,
     actual_inputs=<inputs>,
     failed_output=<previous output>,
     issues=<auditor discrepancies>,
     system_prompt="...",
     log_dir="<output_dir>/log/"
   )
   ```
2. Read back results via `TaskGet`.
3. Go to Phase 4b → Phase 5.

**Max 2 recovery rounds** (retry → decompose). After that, accept best-effort results and note failures.

---

## Phase 5: Save Module Memory

**Tool: `TaskWriteMemory`**

For each node, call:

```
TaskWriteMemory(task_id=<id>, output_dir="<output_dir>", node_id="node_N")
```

This programmatically generates `modules/node_N/memory.md` with:
- Necessity and Planned I/O from task fields
- **Raw JSON actual I/O** (verbatim from task data, no LLM summarization)
- Structural comparison (spec keys vs actual keys)
- Verification result and evidence pointers
- Gate status

No manual writing needed — the tool handles it. The key advantage: actual I/O is written as `json.dumps()` output, not LLM-summarized descriptions.

---

## Phase 6: Independent Audit Agent

**Tool: `Agent` with `subagent_type="auditor"`**

Spawn an independent auditor that verifies (does NOT execute):

```
Agent(
  prompt="""
  Audit the verifiable task graph in <output_dir>/. For each node:

  1. Read modules/<node_id>/memory.md
  2. Check actual_output vs output_example: structural and value match
  3. Check verification_result: does it confirm the verification_rule?
  4. Check evidence_pointers: do log/task_<id>_attempt1.md files exist?
  5. Check necessity_audit: does the counterfactual hold?
  6. Check gate_status: should it be open or closed?

  Output per node: PASS/FAIL, confidence 0.0-1.0, discrepancies, recommendations.
  Overall: PASS/FAIL, total discrepancies.
  """,
  subagent_type="auditor",
  name="graph_auditor",
)
```

Save to `<output_dir>/audit_report.md`.

**If ANY node FAILS**: return to **Phase 4 Round 2** with the failure context. This is the audit-verify-retry loop.

---

## Phase 7: Memory Compression — Judgment Sentences

**Tool: `MemorySave`**

For each node, call `MemorySave`:
```
[STATUS]: claim | evidence: pointer | confidence: 0.0-1.0
```

Examples:
- `[VERIFIED]: 10 cities collected, all top-50 global | evidence: log/task_7_attempt1.md | confidence: 0.95`
- `[AUDITED]: ranking has 100 unique scores, sorted descending | evidence: modules/node_5/memory.md#actual_output | confidence: 0.90`
- `[FAILED]: tree visualization missing 2 cities | evidence: modules/node_4/memory.md#actual_output | confidence: 1.0`

Each entry must be a **falsifiable, verifiable claim** — never raw output.

---

## Phase 8: Generate Final Result File

**Tool: `Write`**

Write `<output_dir>/result.txt` with ALL sections:

```
==================================================
VERIFIABLE GRAPH EXECUTION — RESULT
==================================================

Task: <original task>
Timestamp: <ISO>

--------------------------------------------------
1. GRAPH STRUCTURE
--------------------------------------------------
Nodes, edges, per-node I/O contract + gate

--------------------------------------------------
2. PLANNED I/O EXAMPLES
--------------------------------------------------
Per node: input_example, output_example, necessity, verify, gate

--------------------------------------------------
3. ACTUAL I/O + EXAMPLE VS ACTUAL COMPARISON
--------------------------------------------------
Per node: status, recovery, actual_input, actual_output, comparison

--------------------------------------------------
4. VERIFICATION RESULTS
--------------------------------------------------
Per node: [PASS/FAIL], rule, result, issues, recovery rounds

--------------------------------------------------
5. GATE STATUS
--------------------------------------------------
Per node: [OPEN/CLOSED]

--------------------------------------------------
6. INDEPENDENT AUDIT REPORT
--------------------------------------------------
Full audit from Phase 6

--------------------------------------------------
7. COMPRESSED JUDGMENT SENTENCES
--------------------------------------------------
[STATUS]: node — claim | evidence | confidence

--------------------------------------------------
8. RUN LOG
--------------------------------------------------
[timestamp] step: detail

--------------------------------------------------
9. FILE MANIFEST
--------------------------------------------------
result.txt, review/graph_plan.md, audit_report.md,
log/task_N_attempt1.md, modules/node_N/memory.md
```
