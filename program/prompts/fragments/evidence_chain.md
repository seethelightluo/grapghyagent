# Evidence Chain Workflow — Verifiable Task Graph Protocol

You build **verifiable task graphs**. Every decomposition must produce auditable, gate-controlled nodes with evidence chains.

**CRITICAL**: NEVER fabricate actual_input or actual_output. Always read them from `TaskGet` after execution. Copying from output_example is cheating.

## Phase 1: Graph Decomposition

When decomposing a complex task:
1. Call `TaskCreate` for each node with:
   - `input_spec` / `output_spec`: typed I/O contracts
   - `input_example` / `output_example`: concrete sample data (real data, not descriptions)
   - `necessity_claim`: why this node is indispensable
   - `necessity_audit`: counterfactual — "if removed, what breaks? **Verdict: indispensable/removable**"
   - `verification_rule`: how to verify the output
   - `gate_condition`: what must be true before downstream nodes execute
   - `evidence_pointers`: where evidence will be stored (e.g. `["log/task_7_attempt1.md"]`)
2. Link nodes with `TaskUpdate(task_id, blocked_by=[...])`.
3. **Prune ruthlessly**: if removing a node still achieves the goal, delete it.

## Phase 2: Graph Review — PAUSE FOR USER APPROVAL

1. Write `review/graph_plan.md` with per-node details, edges, and a Mermaid flowchart.
2. **Pause** with `AskUserQuestion` — approve or request changes.
3. If changes requested: back to Phase 1, regenerate, pause again.

## Phase 3: Create Tasks

Call `TaskCreate` for each node with ALL fields. Wire edges with `TaskUpdate`.

## Phase 4: Execute with Gate Control + Recovery (Loop)

For each node in topological order:
1. `TaskGateCheck(task_id)` — if BLOCKED, skip.
2. Resolve inputs from upstream `TaskGet`.
3. `TaskExecuteRecovery(task_id, actual_inputs, log_dir="<output_dir>/log/")` — framework handles attempt→retry→decompose, writes evidence logs.
4. `TaskGet(task_id)` — read back actual_input, actual_output, verification_result, gate_status.

**Recovery loop** (up to 2 rounds):
- If Phase 6 audit FAILS: re-execute failed nodes with audit discrepancies injected into system_prompt.
- If still FAILS: use `TaskDecompose` to break into sub-tasks.
- Max 2 recovery rounds, then accept best-effort.

## Phase 5: Save Module Memory

For each node, call `TaskWriteMemory(task_id=<id>, output_dir="<output_dir>", node_id="node_N")`.

This programmatically generates `modules/node_N/memory.md` with raw JSON actual I/O — no LLM summarization. The tool reads task data directly and writes verbatim JSON, not natural language descriptions.

Do NOT judge pass/fail — the auditor judges.

## Phase 6: Independent Audit

Spawn `Agent(subagent_type="auditor")` to verify each node:
- actual_output vs output_example match
- verification_result confirmation
- evidence_pointers resolve to real files
- necessity_audit counterfactual validity
- gate_status correctness

Save to `audit_report.md`. **If any node FAILS → return to Phase 4 retry loop.**

## Phase 7: Memory Compression

`MemorySave` with format: `[STATUS]: claim | evidence: pointer | confidence: 0.0-1.0`

## Phase 8: Result File

Generate `result.txt` with: graph structure, planned I/O, actual I/O + comparison, verification, gate status, audit report, judgment sentences, run log, file manifest.
