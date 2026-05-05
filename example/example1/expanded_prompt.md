# Task: Verifiable Graph Workflow

Execute this task using the Verifiable Task Graph Protocol.

CRITICAL RULES:
- After each tool call, IMMEDIATELY make the next tool call. Do NOT stop to explain.
- NEVER fabricate actual_input or actual_output. Always read from TaskGet after execution.
- Use log_dir in TaskExecuteRecovery to generate evidence files.

## Task Description

搜寻世界上前10城市的10个出名的事物共100个，用树结构可视化展现出来，同时对这100个的重要性排序，排序结果生成txt文件

## Output Directory

All files go to: `e:/graphyagent/example/example1/`

## Step 1: Create Directories

```bash
mkdir -p e:/graphyagent/example/example1/{review,log,modules/node_{1,2,3,4,5,6}}
```

## Step 2: Write Graph Plan

Write `e:/graphyagent/example/example1/review/graph_plan.md` with 6 nodes:

| Node | Name | Input | Output | Gate |
|------|------|-------|--------|------|
| node_1 | Define City List & Criteria | none | cities_list[10], criteria | 10 unique cities |
| node_2 | Collect Famous Things | cities_list, criteria | raw_data[10 cities x 10 things] | 100 items |
| node_3 | Validate Data | raw_data | validated_data, validation_status=true | status=true |
| node_4 | Tree Visualization | validated_data | tree_visualization (string) | non-empty |
| node_5 | Rank by Importance | validated_data | ranked_list[100 items with rank,item,city] | 100 unique ranks |
| node_6 | Generate TXT | ranked_list, tree_visualization | txt_file_content (string) | non-empty |

Edges: node_1 -> node_2 -> node_3 -> {node_4, node_5} -> node_6

Include per-node: necessity_claim, necessity_audit (counterfactual), verification_rule, input_example (concrete), output_example (concrete), evidence_pointers (use `log/task_<N>_attempt1.md`).

Include a Mermaid flowchart.

## Step 3: Ask User Approval

Use `AskUserQuestion` to approve or request changes.

## Step 4: Create Tasks

Create ALL 6 tasks with `TaskCreate` (ALL fields). Wire edges with `TaskUpdate(task_id, blocked_by=[...])`.

## Step 5: Execute with Evidence Logging

For each node in topological order (node_1 -> node_2 -> node_3 -> {node_4, node_5 parallel} -> node_6):

1. `TaskGateCheck(task_id)` — if BLOCKED, skip
2. Resolve inputs from upstream `TaskGet`
3. Execute:
```
TaskExecuteRecovery(
  task_id=<id>,
  actual_inputs=<resolved inputs>,
  system_prompt="You are a geographic/cultural data expert. Return valid JSON only.",
  log_dir="e:/graphyagent/example/example1/log/"
)
```
4. `TaskGet(task_id)` — read actual_input, actual_output, verification_result, gate_status

## Step 6: Write Module Memory Files

For each node, `TaskGet(task_id)` first, then write `e:/graphyagent/example/example1/modules/node_N/memory.md`:
- Necessity, Planned I/O, Actual I/O (from TaskGet, NOT fabricated), Comparison, Verification, Evidence Pointers, Gate.

Do NOT judge pass/fail.

## Step 7: Audit + Retry Loop

### Round 1: Initial Audit
```
Agent(
  prompt="Audit the verifiable task graph in e:/graphyagent/example/example1/. For each of 6 nodes: read modules/node_N/memory.md, check actual_output vs output_example, check verification_result, check evidence_pointers exist in log/, check necessity_audit. Output per-node PASS/FAIL with confidence and discrepancies.",
  subagent_type="auditor",
  name="graph_auditor"
)
```
Save to `e:/graphyagent/example/example1/audit_report.md`.

### Round 2: Retry Failed Nodes (if any FAIL)
For each failed node, re-execute with audit failure context:
```
TaskExecuteRecovery(
  task_id=<failed_id>,
  actual_inputs=<same inputs>,
  system_prompt="Previous output failed audit. Issues: <discrepancies>. Fix ALL issues. Return JSON only.",
  log_dir="e:/graphyagent/example/example1/log/"
)
```
Re-save memory files for retried nodes. Re-run audit.

### Round 3: Decompose (if Round 2 still fails)
For still-failed nodes:
```
TaskDecompose(
  task_id=<failed_id>,
  actual_inputs=<inputs>,
  failed_output=<previous output>,
  issues=<auditor discrepancies>
)
```
Re-save memory. Re-audit. Max 2 recovery rounds.

## Step 8: Memory Compression

For each node, `MemorySave` with: `[STATUS]: claim | evidence: pointer | confidence`

## Step 9: Write result.txt

Write `e:/graphyagent/example/example1/result.txt` with sections:
1. Graph Structure
2. Planned I/O Examples
3. Actual I/O + Comparison (from TaskGet)
4. Verification Results
5. Gate Status
6. Independent Audit Report
7. Compressed Judgment Sentences
8. Run Log (include recovery rounds)
9. File Manifest
