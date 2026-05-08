# GraphyAgent Documentation

## Guides

| Document | Description |
|----------|-------------|
| [Getting Started](getting-started.md) | Installation, setup, first run, basic concepts |
| [Slash Commands Reference](commands.md) | Every `/` command with usage examples (50+ commands) |
| [Evidence Chain Tutorial](evidence-chain.md) | Step-by-step walkthrough of the 8-phase verifiable graph workflow |
| [Verifiable Graph Concepts](verifiable-graph.md) | Deep dive: I/O contracts, gates, recovery pipeline, audits, memory |

## Quick Reference

### Start the REPL Attacks

```bash
cd program
python cheetahclaws.py
```

### Run a verifiable task graph

```
/evidence_chain <your task description>
```

### Run the example tests

```bash
python scripts/test_example1.py    # World Top 10 Cities × 10 Famous Things
python scripts/test_example2.py    # World Top 10 Universities × 10 Disciplines
python scripts/test_decompose_depth.py  # Decompose depth and sub-graph tests
```

### Key commands

| Command | Action |
|---------|--------|
| `/help` | Show all commands |
| `/model <name>` | Switch model |
| `/save [file]` | Save session |
| `/resume` | Resume last session |
| `/status` | Session status |
| `/context` | Context window usage |
| `/evidence_chain` | Run verifiable graph protocol |
| `/tasks` | List all tasks |
| `/memory` | Search memories |
| `/skills` | List skills |
| `/agent` | Launch autonomous agent |
| `/plan` | Enter plan mode |
| `/exit` | Exit |
