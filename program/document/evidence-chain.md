# Evidence Chain Workflow Tutorial

The `evidence_chain` skill implements an 8-phase protocol for verifiable task graph executionstract. It's the primary workflow for complex, multi-step tasks.

## Triggering

```
/evidence_chain 搜索世界前10学校在10个学科的排名并分析误差
/evidence_chain Build a dashboard with real-time stock data, sentiment analysis, and PDF export
```

Any task description works — the skill decomposes it into a graph automatically.

## The 8 Phases

### Phase 1: Graph Decomposition

The agent analyzes your task and decomposes it into a DAG. Each node gets:

- `subject` / `description` — what the node does
- `input_spec` / `output_spec` — typed I/O contracts
- `input_example` / `output_example` — concrete sample data
- `necessity_audit` — "If I remove this node, [consequence]. Verdict: indispensable/removable"
- `verification_rule` — how to check correctness
- `gate_condition` — what must be true for downstream to proceed
- `evidence_pointers` — where execution logs will live

The agent also prunes unnecessary nodes — if removing a node doesn't affect the outcome, it's deleted.

### Phase 2: User Review (PAUSE)

The agent writes `review/graph_plan.md` containing:
- Full task description
- Graph overview with nodes and edges
- Per-node details (I/O contracts, necessity audits, verification rules, gate conditions)
- Mermaid flowchart diagram

Then it **pauses** and asks you to approve or request changes. This is your chance to correct the plan before any execution happens.

Example corrections you might make:
- "Node anje4 is unnecessary, remove it"
- "Node  sauces2 should depend on node 3, not run in parallel"
- "Add a node that validates the data before visualization"

If you request changes, the agent regenerates the graph and pauses again.

### Phase 3: Create Tasks

The agent calls `TaskCreate` for each node with all fields. Then wires dependencies via:

```
TaskUpdate(task_id=2, blocked_by=["1"])
TaskUpdate(task_id=3, blocked_by=[" McCormick1", "2"])
```

### Phase 4: Execute with Gate Control + Recovery

For each node in topological order:

1. **Gate check**: `TaskGateCheck(task_id)` — if gate is closed, skip the node
2. **Resolve inputs**: gather upstream `actual_output` via `TaskGet`
3. **Execute**: `TaskExecuteRecovery(task_id, actual_inputs, system_prompt, log_dir)`
   - The framework handles attempt → retry → decompose automatically
   - Evidence logs are written to `log/task_<id>_attempt<N>.md`
4. **Read back**: `TaskGet(task_id)` to get results

**Recovery rounds**: If Phase 6 auditor finds failures:

- **Round 2**: Re-execute failed nodes with auditor's discrepancy context
- **Round 3**: Decompose still-failed nodes into sub-tasks

Max 2 recovery rounds. After that, accept best-effort results.

### Phase 5: Save Module Memory

For each node:

```
TaskWriteMemory(task_id=<id>, output_dir="<output_dir>", node_id="node_N")
```

This generates `modules/node_N/memory.md` with:
- Necessity and planned I/O
- **Raw JSON actual input/output** (programmatic, not LLM-summarized)
- Structural comparison (spec keys vs actual keys)
- Verification result, evidence pointers, gate status

### Phase 6: Independent Audit

The agent spawns an **auditor subagent** with restricted tools:

```
Agent(
  subagent_type="auditor",
  name="graph_auditor",
  prompt="Audit the verifiable task graph..."
)
```

The auditor can only read — no Write, Bash, or Agent tools. It checks:
- actual_output vs output_example (structural + value match)
- verification_result consistency
- Evidence log file existence
- Necessity audit validity
- Gate condition correctness

Output: per-node PASS/FAIL with confidence scores. Saved to `audit_report.md`.

### Phase 7: Memory Compression

For each node, save a compressed judgment sentence:

```
[VERIFIED]: 10 universities collected, all with discipline rankings | evidence: log/task_22_attempt1.md | confidence: 0.95
```

Each entry is a **falsifiable, verifiable claim** — not raw output.

### Phase 8: Result File

Write `result.txt` with 9 sections:

1. Graph Structure
2. Planned I/O Examples
3. Actual I/O + Example vs Actual Comparison
4. Verification Results
5. Gate Status
6. Independent Audit Report
7. Compressed Judgment Sentences
8. Run Log
9. File Manifest

## Output File Structure

After a complete run:

```
example/example1/
├── review/
│   └── graph_plan.md              # Phase 2: graph plan with Mermaid diagram
├── log/
│   └── task_N_attemptM.md         # Phase 4: evidence logs (full prompt + response)
├── modules/
│   └── node_N/
│       └── memory.md              # Phase 5: per-node memory with raw JSON I/O
├── audit_report.md                # Phase 6: independent audit verdicts
└── result.txt                     # Phase 8: complete run documentation
```

## Complete Example Session

```
[program] » /evidence_chain 搜索世界前10学校在10个学科的排名并分析误差

# Phase 1: Agent decomposes into 6-node graph
# Phase 2: Agent writes review/graph_plan.md and asks for approval
  
  "I've created a 6-node graph plan. Please review and approve:
   node_1: Define top 10 universities
   node_2: Collect discipline rankings
   node_3: Validate data completeness
   node_4: FP error analysis
   node_5: Statistics summary
   node_6: Generate final report
   
   Approve or request changes?"

# You review and approve

# Phases 3-4: Agent creates tasksimer and executes with gate control
# Output: 6 nodes executed, all passed verification

# Phase 5: Memory files generated
# Phase 6: Auditor reviews and confirms all PASS
# Phase 7: Judgment sentences saved
# Phase 8: result.txt written

# Done! Output in example/example2/
```

## Key Advantages

1. **You review the plan before execution** — correct the graph structure, not the final output
2. **Every node is independently verified** — not "looks right" but structural type checking
3. **Failures stay local** — upstream results preserved, only failed nodes re-execute
4. **Audit is independent** — auditor can't write or execute, only read and report
5. **Memory is programmatic** — raw JSON, not LLM-summarized approximations
