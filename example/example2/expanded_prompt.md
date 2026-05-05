# Task: World Top 10 University Rankings Across 10 Disciplines

**Goal**: Search for the world's top 10 universities, collect their rankings in 10 fixed academic disciplines, calculate each university's average discipline ranking, compare it with their overall ranking using floating-point error analysis, and output the results to a text file.

**Output directory**: `e:/graphyagent/example/example2/`

**CRITICAL**: Do NOT use Research, WebSearch, or WebFetch tools. All data generation happens inside `TaskExecuteRecovery` — the framework calls the LLM to generate data. You only orchestrate the workflow using TaskCreate, TaskUpdate, TaskGateCheck, TaskExecuteRecovery, TaskGet, TaskWriteMemory, Agent, and Write.

---

## Step 1: Create Directories

```
mkdir -p e:/graphyagent/example/example2/review
mkdir -p e:/graphyagent/example/example2/log
mkdir -p e:/graphyagent/example/example2/modules
```

---

## Step 2: Graph Plan

Write `e:/graphyagent/example/example2/review/graph_plan.md` with:

### Graph Structure

```
node_1 → node_2 → node_3 → node_4 → node_6
                       ↘ node_5 ↗
```

### Node Details

**node_1: Define Universities & Disciplines**
- Input: none
- Output: `{"universities": ["MIT", "Stanford", ...], "disciplines": ["Computer Science", "Engineering", ...]}`
- Gate: 10 universities + 10 disciplines returned
- Necessity: Foundation — without this, no scope definition

**node_2: Collect Rankings Data**
- Input: universities + disciplines from node_1
- Output: `{"rankings": [{"university": "MIT", "overall_rank": 1, "disciplines": {"Computer Science": 1, "Engineering": 2, ...}}, ...]}`
- Gate: 10 universities, each with 10 discipline rankings + 1 overall rank
- Necessity: Core data collection

**node_3: Validate Data**
- Input: raw rankings from node_2
- Output: `{"validation_status": true, "total_universities": 10, "disciplines_count": 10, "duplicates_found": 0, "validated_data": [...]}`
- Gate: validation_status == true
- Necessity: Ensures data integrity before analysis

**node_4: Calculate Floating-Point Error Analysis**
- Input: validated data from node_3
- Output: `{"analysis": [{"university": "MIT", "overall_rank": 1, "avg_discipline_rank": 2.3, "error": +1.3, "error_pct": 130.0}, ...]}`
- Gate: 10 universities with error calculations
- Necessity: Core analytical computation

**node_5: Generate Statistics Summary**
- Input: validated data from node_3
- Output: `{"stats": {"mean_error": ..., "std_error": ..., "max_positive_error": ..., "max_negative_error": ..., "universities_overestimated": ..., "universities_underestimated": ...}}`
- Gate: all stat fields present
- Necessity: Statistical context for the error analysis

**node_6: Generate TXT Output**
- Input: tree visualization + ranking from node_4 and node_5
- Output: `{"txt_content": "..."}`
- Gate: non-empty txt with all sections
- Necessity: Final deliverable

---

## Step 3: Ask User Approval

Use `AskUserQuestion` to ask: "Approve this 6-node graph plan?"

---

## Step 4: Create Tasks

For each node, use `TaskCreate` with ALL fields:
- subject, description
- input_spec, output_spec (typed I/O contracts)
- input_example, output_example (concrete sample data)
- necessity_claim, necessity_audit (counterfactual)
- verification_rule, gate_condition
- evidence_pointers (e.g. `["log/task_1_attempt1.md"]`)

Then wire edges with `TaskUpdate(task_id, blocked_by=[...])`.

---

## Step 5: Execute with Evidence Logging

For each node in topological order:

1. `TaskGateCheck(task_id)` — verify upstream gates are open
2. Resolve inputs from upstream `TaskGet`
3. `TaskExecuteRecovery(task_id, actual_inputs, system_prompt="You are a data expert. Return JSON only.", log_dir="e:/graphyagent/example/example2/log/")`
4. `TaskGet(task_id)` — read back actual_input, actual_output, verification_result, gate_status

Execute order: node_1 → node_2 → node_3 → node_4, node_5 (parallel) → node_6

---

## Step 6: Save Module Memory

For each completed node, use the `TaskWriteMemory` tool:

```
TaskWriteMemory(task_id=<id>, output_dir="e:/graphyagent/example/example2", node_id="node_N")
```

This programmatically generates `modules/node_N/memory.md` with raw JSON actual I/O — no LLM summarization. The tool reads task data directly and writes verbatim JSON.

**Do NOT write memory files manually. Do NOT use TaskGet + Write. Use TaskWriteMemory only.**

---

## Step 7: Independent Audit

Spawn an auditor agent:

```
Agent(
  prompt="Audit the verifiable task graph in e:/graphyagent/example/example2/. For each node: 1. Read modules/node_N/memory.md 2. Check actual_output vs output_example: structural and value match 3. Check verification_result 4. Check evidence_pointers: do log files exist? 5. Check necessity_audit counterfactual 6. Check gate_status. Output per node: PASS/FAIL, confidence 0.0-1.0, discrepancies, recommendations. Save to audit_report.md.",
  subagent_type="auditor",
  name="graph_auditor"
)
```

Save the auditor's output to `e:/graphyagent/example/example2/audit_report.md`.

---

## Step 8: Memory Compression

For each node, use `MemorySave` to store a compressed judgment sentence:

```
MemorySave(content="[STATUS]: claim | evidence: pointer | confidence: 0.0-1.0", category="task_graph")
```

---

## Step 9: Write Result File

Write `e:/graphyagent/example/example2/result.txt` with all sections:

1. GRAPH STRUCTURE
2. PLANNED I/O EXAMPLES
3. ACTUAL I/O + EXAMPLE VS ACTUAL COMPARISON
4. VERIFICATION RESULTS
5. GATE STATUS
6. INDEPENDENT AUDIT REPORT
7. COMPRESSED JUDGMENT SENTENCES
8. RUN LOG
9. FILE MANIFEST
