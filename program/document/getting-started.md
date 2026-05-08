# Getting Started with GraphyAgent

## Prerequisites

- Python 3.10+
- An API key from one of the supported providers (Anthropic, OpenAI, Ollama, etc.)

## Installation

```bash
cd program
pip install -r requirements.txt
```

## Set Your API Key

```bash
# Anthropic (recommended)
export ANTHROPIC_API_KEY=sk-ant-...

# Or OpenAI
export OPENAI_API_KEY=sk-...

# Or use a local Ollama server — no key needed
```

## First Run

```bash
cd program
python cheetahclaws.py
```

You'll see the Cheetah banner and a REPL prompt:

```
[program] » _
```

Type a message and press Enter. The agent will respond.

## Basic Usage

### Ask a question

```
[program] » What does the task/store.py module do?
```

### Run a task with the evidence chain workflow

```
[program] » /evidence_chain 搜索世界前10城市和10个出名的事物，用树结构可视化
```

This triggers the full 8-phase verifiable graph protocol: decompose → review → create → execute → memory → audit → compress → result.

### Switch models

```
[program] » /model claude-sonnet-4-6
[program] » /model gpt-4o
[program] » /model llama3.2
```

### Check status

```
[program] » /status        # model, tokens, cost, mode
[program] » /context       # token usage vs limit
[program] » /cost          # estimated API cost
```

### Save and resume

```
[program] » /save my-session
[program] » /resume        # resume last auto-saved session
[program] » /load my-session
```

## Key Concepts

GraphyAgent extends CheetahClaws with a **verifiable task graph protocol**. The core idea:

1. **Decompose first** — break complex tasks into a DAG of nodes before executing
2. **Every node has a contract** — typed `input_spec`/`output_spec`, verification rules, gate conditions
3. **Automatic recovery** — failed nodes retry, then decompose into sub-graphs
4. **Independent audit** — a read-only auditor subagent reviews all results
5. **Programmatic memory** — node-level memory.md files with raw JSON, not LLM summaries

## Where to Go Next

- [Slash Commands Reference](commands.md) — every `/` command with usage
- [Evidence Chain Tutorial](evidence-chain.md) — step-by-step verifiable graph workflow
- [Verifiable Graph Concepts](verifiable-graph.md) — deep dive on I/O contracts, gates, recovery
