# GraphyAgent: Verifiable Task Graph Execution on CheetahClaws

GraphyAgent extends [CheetahClaws](https://github.com/SafeRL-Lab/cheetahclaws) with a **verifiable task graph protocol** — a structured workflow that decomposes complex tasks into a DAG of nodes, enforces I/O contracts, runs automatic recovery on failure, and produces auditable evidence chains.

Built on top of CheetahClaws's agent loop, tool system, and multi-agent architecture.

---

## Why GraphyAgent

Standard LLM agents suffer from three systemic problems:

1. **Unverifiable output** — the agent says "done" but you can't check if the output actually matches the spec
2. **Brittle failure recovery** — one bad node kills the entire task; no structured retry or decomposition
3. **No audit trail** — you see the final answer but not how it was produced, what data flowed where, or what was verified

GraphyAgent solves all three with a protocol that treats every sub-task as a **contract** with typed I/O, verification rules, gate conditions, and evidence pointers.

---

## Innovation

### 1. I/O Contracts with Structural Verification

Every task node declares `input_spec` and `output_spec` — not free-text descriptions, but **typed key schemas** that the framework checks programmatically:

```python
output_spec = {
    "universities": "array of 10 strings",
    "disciplines": "array of 10 strings"
}
```

After execution, `verify_output()` compares actual output keys against the spec. Missing keys, wrong types, or structural mismatches are caught automatically — no LLM self-judgment needed.

### 2. Three-Level Automatic Recovery Pipeline

When a node fails verification, `TaskExecuteRecovery` runs a **three-level cascade** without human intervention:

```
Attempt → Retry (with failure context) → Decompose (into sub-tasks)
```

- **Attempt**: Execute the node, verify output against spec
- **Retry**: If verification fails, re-execute with the failure reason injected into the system prompt
- **Decompose**: If retry still fails, break the node into 2-3 smaller sub-tasks and execute each independently

Recovery operates at the **node level** — upstream results are preserved. A failure in node 5 does not rebuild nodes 1-4.

### 3. Gate-Controlled Execution

Each node has a `gate_condition` — a programmatic predicate that must be satisfied before downstream nodes can execute:

```python
gate_condition = "rankings.length == 10 AND each has overall_rank"
```

`TaskGateCheck` evaluates the condition against actual output. If the gate is **closed**, downstream nodes are blocked. This prevents invalid data from propagating through the pipeline.

### 4. Necessity Audits (Counterfactual Analysis)

Every node must justify its existence with a **necessity audit** — a counterfactual that answers: "If I remove this node, what breaks?"

```
necessity_audit = "If removed, no ranking data exists for validation or analysis.
                   The pipeline has nothing to process. Verdict: indispensable."
```

Nodes that fail the necessity audit are pruned. This keeps the graph minimal.

### 5. Evidence Chains

Every execution produces **evidence pointers** — concrete file paths to logs that prove what happened:

```
evidence_pointers = ["log/task_22_attempt1.md"]
```

The evidence log records the full LLM prompt and response, making the execution traceable and reproducible.

### 6. Independent Auditor Agent

After all nodes execute, an **independent auditor subagent** (with restricted read-only tools) reviews the entire graph:

- Reads each node's memory.md
- Checks actual output vs output example (structural + value match)
- Verifies evidence log files exist
- Validates necessity audits and gate conditions
- Produces a per-node PASS/FAIL verdict with confidence scores

The auditor cannot write or execute — it can only read and report.

### 7. Programmatic Memory Generation (TaskWriteMemory)

Memory files are generated **programmatically** via `TaskWriteMemory`, not by the LLM. This eliminates summarization bias — actual I/O is written as raw `json.dumps()` output, not LLM-described approximations.

---

## Architecture

```
program/
├── task/
│   ├── types.py          # Task dataclass with verifiable graph extensions
│   ├── store.py          # Task persistence (tasks.json)
│   ├── tools.py          # TaskCreate, TaskUpdate, TaskGet, TaskList,
│   │                     # TaskGateCheck, TaskRetry, TaskDecompose,
│   │                     # TaskExecuteRecovery, TaskWriteMemory
│   └── recovery.py       # Three-level recovery pipeline (attempt→retry→decompose)
├── tool_registry.py      # Tool registration + filtered schema getter
├── agent.py              # Core agent loop (yields TextChunk, ToolStart, ToolEnd)
├── multi_agent/
│   └── subagent.py       # SubAgentManager + AgentDefinition (tool filtering)
├── memory/
│   └── tools.py          # MemorySave, MemorySearch, MemoryList
├── .cheetahclaws/
│   └── skills/
│       └── evidence_chain/
│           └── SKILL.md  # The 8-phase verifiable graph protocol
└── prompts/
    └── fragments/
        └── evidence_chain.md  # Prompt fragment for the protocol
```

### Key Components

| Component | File | Role |
|-----------|------|------|
| **Task dataclass** | `task/types.py` | Extends base Task with `input_spec`, `output_spec`, `actual_input`, `actual_output`, `verification_rule`, `gate_condition`, `gate_status`, `necessity_audit`, `evidence_pointers`, `run_log` |
| **Recovery pipeline** | `task/recovery.py` | `execute_with_recovery()` — attempt → retry → decompose cascade with `verify_output()` structural check |
| **Tool filtering** | `tool_registry.py` | `get_tool_schemas_filtered(allowed_tools)` — restricts which tools a subagent can see |
| **Auditor spawn** | `multi_agent/subagent.py` | `spawn()` passes `agent_def.tools` as `_allowed_tools` config, enforcing read-only access |
| **TaskWriteMemory** | `task/tools.py` | Programmatic memory.md generation with raw JSON actual I/O |
| **Evidence chain skill** | `.cheetahclaws/skills/evidence_chain/SKILL.md` | 8-phase protocol definition |

---

## The Evidence Chain Workflow (8 Phases)

The `evidence_chain` skill defines an 8-phase protocol for verifiable task graph execution:

### Phase 1: Graph Decomposition

Decompose the user's task into a DAG. For each node define:
- `subject` / `description` — what the node does
- `input_spec` / `output_spec` — typed I/O contracts
- `input_example` / `output_example` — concrete sample data
- `necessity_claim` — why this node exists
- `necessity_audit` — counterfactual: "If I remove this node, [consequence]. Verdict: indispensable/removable"
- `verification_rule` — how to check correctness
- `gate_condition` — downstream-blocking condition
- `evidence_pointers` — where proof will live

### Phase 2: User Review

Write `review/graph_plan.md` with the full plan (nodes, edges, Mermaid flowchart). **Pause for user approval** via `AskUserQuestion`. Only proceed after approval.

### Phase 3: Create Tasks

Call `TaskCreate` for each node with ALL fields. Wire dependencies via `TaskUpdate(task_id, blocked_by=[...])`.

### Phase 4: Execute with Gate Control + Recovery

For each node in topological order:
1. `TaskGateCheck(task_id)` — skip if blocked
2. Resolve inputs from upstream `TaskGet`
3. `TaskExecuteRecovery(task_id, actual_inputs, system_prompt, log_dir)` — framework handles attempt→retry→decompose automatically
4. `TaskGet(task_id)` — read back actual_input, actual_output, verification_result, gate_status

If Phase 6 audit returns FAIL, re-execute failed nodes with audit context (Round 2). If still failing, decompose (Round 3). Max 2 recovery rounds.

### Phase 5: Save Module Memory

For each node: `TaskWriteMemory(task_id, output_dir, node_id)` — programmatically generates `modules/node_N/memory.md` with raw JSON actual I/O.

### Phase 6: Independent Audit

Spawn an auditor subagent with restricted tools (Read, Glob, Grep, TaskGet, TaskList, TaskGateCheck only). The auditor reads memory files, checks output vs example, verifies evidence, and produces PASS/FAIL per node.

### Phase 7: Memory Compression

For each node, save a compressed judgment sentence:
```
[VERIFIED]: 10 universities collected, all with 10 discipline rankings | evidence: log/task_22_attempt1.md | confidence: 0.95
```

### Phase 8: Result File

Write `result.txt` with 9 sections: Graph Structure, Planned I/O, Actual I/O + Comparison, Verification Results, Gate Status, Audit Report, Compressed Judgments, Run Log, File Manifest.

---

## Examples

### Example 1: World Top 10 Cities × 10 Famous Things

**Task**: 搜寻世界上前10城市的10个出名的事物共100个，用树结构可视化展现出来，同时对这100个的重要性排序，排序结果生成txt文件

**Graph** (6 nodes):
```
node_1 (Define Cities) → node_2 (Collect Famous Things) → node_3 (Validate Data)
                                                           ├→ node_4 (Tree Visualization) ─┐
                                                           └→ node_5 (Rank by Importance) ─┤
                                                                                           └→ node_6 (Generate TXT)
```

**Key results**:
- 10 cities, 10 things each, 100 items total
- Tree visualization with hierarchical structure
- Importance ranking with 100 unique ranks
- All 6 nodes passed verification
- Recovery rounds used: 0 (clean execution)

**Output files**: `example/example1/` — result.txt, audit_report.md, graph_plan.md, 6 memory files, 6 evidence logs

### Example 2: World Top 10 Universities × 10 Disciplines Rankings

**Task**: 搜索世界前10学校在10个固定学科的排名，并计算学科平均排名和总排名的差别（按照浮点数的正负误差）

**Graph** (6 nodes):
```
node_1 (Define Universities) → node_2 (Collect Rankings) → node_3 (Validate Data)
                                                             ├→ node_4 (FP Error Analysis) ─┐
                                                             └→ node_5 (Statistics Summary) ─┤
                                                                                             └→ node_6 (Generate TXT)
```

**Key results**:
- 10 universities (MIT, Stanford, Harvard, Caltech, Oxford, Cambridge, ETH Zurich, UCL, Imperial, Chicago)
- 10 disciplines (CS, Engineering, Natural Sciences, Math, Physics, Chemistry, Biology, Medicine, Economics, Law)
- Cambridge has largest negative error (-3.0) — disciplines outperform overall ranking
- Caltech has largest positive error (+2.5) — overall rank better than average discipline performance
- Mean error: -0.01 (no systematic bias), Std dev: 1.89 (high variability)
- All 6 nodes passed verification and independent audit (confidence: 0.94)

**Recovery history**: The agent went through 3 generations of task graphs:
- Graph 1 (tasks 1-6): Triggered decompose recovery for node 1 — demonstrated the three-level pipeline
- Graph 2 (tasks 12-17): Failed due to output_spec format mismatch (JSON Schema vs flat keys) — agent diagnosed and fixed
- Graph 3 (tasks 21-26): All passed cleanly — 0 recovery rounds needed

**Output files**: `example/example2/` — result.txt, university_rankings_report.txt, audit_report.md, graph_plan.md, 6 memory files, 6 evidence logs

---

## Running the Examples

### Prerequisites

```bash
cd program
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

### Run Example 1

```bash
cd program
python scripts/test_example1.py
```

### Run Example 2

```bash
cd program
python scripts/test_example2.py
```

Or for the completion script (phases 5-8):

```bash
python scripts/complete_example2.py
```

### Using the Skill Directly

In the CheetahClaws REPL:

```
/evidence_chain 搜索世界前10学校在10个学科的排名并分析误差
```

The skill triggers the full 8-phase protocol automatically.

---

## File Manifest

After a complete run, the output directory contains:

```
example/exampleN/
├── review/
│   └── graph_plan.md              # Phase 2: graph plan with Mermaid diagram
├── log/
│   └── task_N_attemptM.md         # Phase 4: evidence logs (prompt + response)
├── modules/
│   └── node_N/
│       └── memory.md              # Phase 5: per-node memory with raw JSON I/O
├── audit_report.md                # Phase 6: independent audit verdicts
├── result.txt                     # Phase 8: complete run documentation
└── university_rankings_report.txt # (example2 only) final deliverable
```

---

## Citation

```bibtex
@article{graphyagent2026,
  title={GraphyAgent: Verifiable Task Graph Execution with Evidence Chains},
  author={GraphyAgent Team},
  journal={github},
  year={2026}
}
```
