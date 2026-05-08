# GraphyAgent -- Agent for Agent

> 用图式思维组织任务、用独立记忆隔离噪声、用可验证的节点输出加速迭代 — 一个为 agent 设计的 agent 运行时。
>
> A graph-native runtime for coding agents: organize work as a graph, isolate noise with per-node memory, and iterate faster with verifiable node outputs.

[English](#english) | [中文](#中文)

- Demo: https://seethelightluo.github.io/grapghyagent/

### 3 步上手 GraphyAgent

每一步的提示词已润色，直接复制给你的 code agent 即可。

**Step 1 — 拉取与环境**

> 请从 https://github.com/seethelightluo/grapghyagent 克隆仓库，并进入项目根目录。检查本机 Python 版本（建议 >= 3.10），然后在 program 目录创建虚拟环境并安装依赖。依赖安装请优先遵循 program/README.md 的说明。完成后请列出可用的启动/运行命令与入口脚本，并说明每个命令的用途。

**Step 2 — 填写密钥**

> 打开 program/.env，将 API Key 填入对应字段（如 ANTHROPIC_AUTH_TOKEN、ANTHROPIC_BASE_URL）。如果还提供了代理或 Base URL，也一起填写。.env 只用于本地运行，不要提交到仓库。

**Step 3 — 用图能力解题**

> 先阅读 program/.cheetahclaws/skills/evidence_chain/SKILL.md，提炼它的输入、输出与使用约束。然后使用 program 内置的 agent 或 CLI 来回答你的问题。输出要求：1) 图式拆分（节点、依赖、并行关系）2) 每个节点的输入/输出与 Gate 3) 最终答案 + 关键证据/数据来源摘要。

---

## 中文

## 为什么还需要 graphyagent？

很多 code agent 已经很强了。  
但在真正复杂、长链、多约束、需要中途纠偏的任务里，用户经常遇到的不是“模型不会写代码”，而是下面这几类问题：

### 场景 1：你发现 agent 已经做偏了，但它纠不回来

你看到 agent 的工作方向已经偏离目标，于是输入一段纠错指令。  
问题是，agent 往往已经把之前任务压缩成模糊上下文，新的纠错命令不能准确地落在正确的步骤和依赖上。  
结果就是：你明明指出了问题，agent 却像“听懂了一半”。

### 场景 2：任务快完成了，最后几步出了错，但你很难一次讲清楚

agent 已经完成了 90%。  
最后几步出现多个错误：顺序错了、输出字段错了、依赖断了、某个文件格式不对。  
你辛苦写一大段反馈，逐条描述每个错误，但 agent 很难完整吸收，常常只修一部分，甚至修了一个又破坏另一个。

### 场景 3：最后几步虽然修对了，但和前面的版本已经不兼容

你成功纠正了最后几步。  
但因为前面执行过程已经被压缩或遗忘，agent 现在是在“缺少上文”的状态下补最后几步。  
于是出现一种很典型的失败：前面的实现本身没错，后面的修复本身也没错，但它们实际上属于两个不兼容的版本。

### 场景 4：你有很复杂的真实需求，但 agent 按自己的默认套路拆错了

你辛苦写了一大段任务说明，尤其是那种“一个项目要同时产出多个维度结果”的任务。  
agent 看起来给了一个合理流程：探索阶段 → 设计方案 → 实现 → 测试验证。  
但细节不对：顺序不对、依赖不对、漏掉你特别在意的小任务、把并行关系误拆成串行。  
接下来你只能继续用长文本反复纠偏，而且越改越难讲清楚。

---

## GraphyAgent 解决什么问题？


它的思路是：**先把任务变成一个可验证的 task graph，再按节点执行、按节点验证、按节点审计、按节点记忆。**

> 不把整个复杂任务交给一段会话上下文，而是拆成带 input_spec/output_spec（I/O 契约）、verification_rule（验证规则）、gate_condition（门控条件）、necessity_audit（必要性审计）、evidence_pointers（证据指针）和 per-node memory 的图执行流程。

---

## GraphyAgent 的核心优势

### 1. 用户可以先审 graph，再让 agent 干活

在执行之前，GraphyAgent 会先生成任务图。  
图里会明确每个节点的职责、输入、输出、依赖关系、验证方式和 gate。  
这时你不是只能对一大段自然语言说“这里不对”，而是可以非常直接地指出：

- 这个节点不该存在
- 这个节点漏了
- 这个节点应该依赖另一个节点
- 这两个节点应该并行，不应该串行
- 这个节点的 output_spec 写错了

也就是说，**你纠错的对象从“整段模糊计划”变成了“具体图结构”**。

### 2. memory 不再是整段对话压缩，而是节点级的干净记忆

传统 code agent 很依赖长会话上下文和压缩记忆。  
一旦任务很长，信息精度会损失，旧噪声会混进来，后续步骤读到的是“混合过的历史”。  

GraphyAgent 的 memory 是按节点组织的：

- 只装载当前节点真正需要的上下文
- 保存该节点的输入、输出、审计结果、证据指针
- 压缩的是节点 judgment，而不是整条任务的模糊摘要

这样做的好处是：

- 更干净，噪声更少
- 更聚焦，不会把无关历史塞进当前步骤
- 更容易复用，因为节点记忆天然绑定职责边界

### 3. 节点失败时，不是整条链一起崩

当某个节点失败时，GraphyAgent 可以：

- 重试当前节点
- 对当前节点再拆分成更细的子图
- 触发独立 audit，分析失败原因
- 把失败结论写入节点的 run_log 和 compressed_judgment，而不是污染整条任务上下文

这意味着失败被限制在**节点**范围，而不是把整个任务拖回“大段重新解释”的状态。  
复杂任务里，这一点非常关键。

### 4. 每个节点只对自己的 input_spec / output_spec 负责，减少版本串线

在规划阶段，GraphyAgent 就会定义每个节点的输入和输出。  
节点不是“尽量完成一个模糊目标”，而是“交付一个明确 output”。  

这样做的意义是：

- 后续修复时不会无意改坏前面步骤
- 节点之间通过 spec 对接，不靠模糊语义猜测
- 更容易发现“前后两步各自都对，但拼起来不兼容”的问题

### 5. 图拆分比线性步骤更适合复杂精细任务

很多 agent 默认把任务写成线性流程：

1. 探索
2. 设计
3. 实现
4. 测试

这对简单任务够用。  
但对复杂任务，问题往往不在线性步骤本身，而在：

- 哪些任务能并行
- 哪些依赖必须先满足
- 哪些只是辅助步骤，哪些才是关键节点
- 哪些结果要共享给多个后续节点

GraphyAgent 用 graph 表达依赖和数据传递，而不是只表达顺序。  
因此它更适合：

- 多目标任务
- 并行子任务
- 带多个交付物的任务
- 中间结果需要复用的任务
- 对可验证性要求高的任务

---

## 和其他方案相比，差别在哪？

### GraphyAgent vs Claude Code（ReAct 风格）

Claude Code 很强，尤其在单次迭代、交互式修复、即时工具调用上非常顺手。  
但它更偏向“在会话里持续推进任务”，而不是先把整个任务图显式建模。

| 维度 | GraphyAgent | Claude Code（ReAct 风格） |
| --- | --- | --- |
| 任务组织 | 先建 graph，再按节点执行 | 在会话中边想边做 |
| 用户纠偏 | 先审图，纠偏对象明确 | 主要通过补充自然语言反馈纠偏 |
| 记忆方式 | 节点级 memory，按职责隔离 | 更依赖共享会话上下文与压缩 |
| 节点失败处理 | 可重试、可再拆分、可独立审计 | 通常靠继续对话修复 |
| 并行与依赖表达 | 显式表达 dependencies 和 data flow | 可以处理，但通常不是一等结构 |
| 最适合的任务 | 长链、复杂、多约束、多交付任务 | 快速迭代、局部修复、交互式编码 |


### GraphyAgent vs Harness Agent

Harness Agent 已经在“长任务中的恢复、管理、工程隔离”上走得更前。  
它解决了很多“agent 跑着跑着乱掉”的问题。  

但 GraphyAgent 的重点不同：  
它不是主要从 worktree / 工程工作区的角度管理任务，而是从**节点执行**的角度组织 memory 和 audit。

| 维度 | GraphyAgent | Harness Agent |
| --- | --- | --- |
| 核心视角 | 节点语义、input_spec/output_spec、verification_rule、gate_condition、necessity_audit、evidence_pointers、节点记忆 | 工程隔离、任务恢复、工作区管理 |
| memory 组织 | 节点级 memory，绑定当前职责 | 更偏任务/工作区粒度的状态管理 |
| 用户纠偏入口 | 改 graph、改节点 spec、改依赖 | 改任务或继续驱动执行 |
| 失败定位 | 哪个节点失败、为什么失败、证据在哪 | 哪个任务或执行阶段出问题 |
| 优势场景 | 复杂依赖、多交付、强审计需求 | 长任务恢复、工程执行稳定性 |


- Harness 更像“更强的任务执行与恢复底座”
- GraphyAgent 更像“更强的图式规划、节点记忆和语义审计层”


## 什么时候应该用 GraphyAgent？

当你的任务满足下面任意几条时，GraphyAgent 会特别有价值：

- 你已经知道普通 agent 经常做偏
- 你需要在执行前先看计划结构
- 你希望精确指出哪个节点不对，而不是一直打长段文字
- 你有多个并行子任务或多个交付物
- 你担心后期修复和前期实现变成两个不兼容版本
- 你需要可审计、可追溯、可重跑的过程

从技术能力角度，GraphyAgent 特别适合这些场景：

- **复杂依赖和并行任务** — graph 的 `blocked_by`/`blocks` 边显式表达依赖关系，支持并行节点。哪些任务能并行、哪些依赖必须先满足、哪些结果要共享给多个后续节点，全部在图结构里一目了然，不需要靠长文本反复解释。
- **必要性审计配合图实现最简流程** — 每个节点必须声明 `necessity_audit`（"如果我去掉这个节点会怎样？"）。如果去掉某个节点目标仍然达成，该节点会被剪掉。这让图始终保持最小必要结构，模型不会做多余的事。
- **节点失败时拆分成子图，保证每步难度适当** — 当某个节点验证失败且重试仍然不过时，`TaskDecompose` 会把它拆成 2-3 个更细的子节点。这意味着模型在每一步面对的都是难度适当的子任务，而不是一个过大过难的原始目标。上游已通过的节点结果完全保留，不动。
- **I/O 验证而不只是"看起来对"** — `verify_output()` 做 structural check + type check，不依赖 LLM 自判。输出是否符合 `output_spec`，是程序检查的，不是模型自己说"我觉得对了"。
- **独立审计而不只是自检** — `subagent_type="auditor"` 用受限工具集（只读）做独立 review，产出 PASS/FAIL + confidence score。审计和执行是分离的。
- **节点级干净记忆而不是整段对话压缩** — `TaskWriteMemory` 程序生成 memory.md，用 `json.dumps()` 写入原始数据，不经过 LLM 摘要。每个节点的输入、输出、验证结果、证据指针都是精确记录。

---

## 一个更准确的理解方式

GraphyAgent 不是“另一个会写代码的 agent”。  
它更像是一个 **graph-native runtime for coding agents**：

- graph planning
- user review before execution
- node-level isolated memory (TaskWriteMemory — programmatic, not LLM-summarized)
- retry / re-decompose on failure (TaskExecuteRecovery — three-level automatic pipeline)
- gate-controlled execution (TaskGateCheck — blocks downstream on failure)
- evidence chains (evidence_pointers — every execution logged to file)
- necessity audit (counterfactual: "if I remove this node, what breaks?")
- independent audit (auditor subagent with restricted read-only tools)
- spec-based delivery (input_spec / output_spec with structural verification)

它要解决的，不是“模型不会写”，而是：

> 当任务变长、变复杂、变多依赖、变多版本时，如何让 agent 仍然可控、可纠偏、可审计、可复用。

---

## Demo

- Demo: https://seethelightluo.github.io/grapghyagent/

---

## English

[English](#english) | [中文](#中文)

## Why another coding agent?

Many coding agents are already powerful.  
But in long, complex, multi-constraint workflows, users still run into the same failures:

1. The agent drifts, and a correction message does not fully pull it back.
2. The task is 90% done, but the last few steps fail in multiple ways, and it is hard to explain every issue clearly.
3. The final fixes look correct, but they no longer match the earlier implementation, so the project ends up with two incompatible versions.
4. The agent decomposes a complex request into a reasonable-looking but wrong sequence, and the user has to keep correcting the plan in long natural-language messages.

GraphyAgent is built for these cases.

## What GraphyAgent does differently

GraphyAgent turns a complex task into a verifiable execution graph before running it.

Each node has:

- a clear role
- input_spec / output_spec (typed I/O contracts)
- dependency edges (blocked_by / blocks)
- verification rules (structural + type check, not LLM self-judgment)
- gate conditions (blocks downstream on failure)
- necessity audit (counterfactual: "if removed, what breaks?")
- evidence pointers (logged prompt + response per execution)
- node-level memory (program-generated with raw JSON, not LLM-summarized)

This means the user can correct the **structure of the plan**, not just react to mistakes after execution has already started.

## Core advantages

### 1. Review the graph before execution

Instead of asking the model to carry the whole plan in one conversation, GraphyAgent first exposes the graph:

- which nodes exist
- which nodes are missing
- which nodes should depend on which
- which nodes should run in parallel
- what each node must deliver

That makes correction much easier.

### 2. Node-level memory instead of one noisy compressed conversation

Traditional agents often rely on long shared context and compression.  
Over time, precision drops and irrelevant history leaks into later steps.

GraphyAgent stores memory at the node level:

- only the context needed for that node
- the node’s input and output
- audit result and evidence pointer
- compressed judgment tied to that node

This keeps memory cleaner and more reusable.

### 3. Failure stays local

If one node fails, GraphyAgent can:

- retry the node with failure context injected
- decompose the node into a finer subgraph (2-3 sub-nodes of appropriate difficulty)
- run an independent audit to analyze the failure
- save the failure result into node's run_log and compressed_judgment

Upstream results are preserved. The whole workflow does not need to collapse back into one giant conversation.

### 4. Each node is responsible for its own spec

Because input_spec and output_spec are defined early, later fixes are less likely to silently break earlier work.
Nodes connect through explicit typed boundaries rather than vague conversational assumptions.

### 5. Graph decomposition fits complex work better than linear step lists

For simple tasks, a linear process is enough.  
For complex tasks, what matters is not only order, but also dependency, reuse, parallelism, and delivery boundaries.

GraphyAgent models those relationships explicitly.

## Comparison

### GraphyAgent vs Claude Code

Claude Code is strong for interactive coding and quick iteration.  
But it is still mostly conversation-driven.

| Dimension | GraphyAgent | Claude Code |
| --- | --- | --- |
| Task organization | Graph-first, then execute by node | Conversation-driven reasoning and tool use |
| Correction flow | Review and edit the graph before execution | Correct through more natural-language feedback |
| Memory | Node-level isolated memory | More dependent on shared conversation context |
| Failure handling | Retry, re-decompose into subgraph, audit per node | Usually continue the conversation and repair |
| Best fit | Long, structured, multi-deliverable workflows | Fast iteration and interactive coding |

### GraphyAgent vs Harness Agent

Harness is stronger as an execution and recovery foundation.  
GraphyAgent focuses more on graph planning, node semantics, node memory, and node-level audit.

| Dimension | GraphyAgent | Harness Agent |
| --- | --- | --- |
| Core abstraction | Node graph with specs, gates, and audits | Task/workspace execution and recovery |
| Memory organization | Node-level semantic memory | More task/workspace-oriented state |
| Failure localization | Which node failed and why | Which task/stage failed |
| Best fit | Complex dependency-heavy workflows | Long-running execution reliability |

They are not mutually exclusive.  
Harness can be seen as a stronger execution substrate; GraphyAgent can be seen as a stronger graph-native planning and memory layer.

## When to use GraphyAgent

Use GraphyAgent when you need:

- you know that ordinary agents often drift from your goals
- you want to review the plan structure before execution
- you want to point at exactly which node is wrong, instead of writing long paragraphs of feedback
- better control over dependencies and parallelism
- auditable and reusable workflows
- fewer version-mismatch failures near the end of a task

Technical capabilities that matter:

- **Complex dependencies and parallel tasks** — `blocked_by`/`blocks` edges express dependency explicitly. Which tasks can run in parallel, which must complete first, which results are shared — all visible in the graph structure.
- **Necessity audit + graph = simplest possible workflow** — every node must justify its existence via `necessity_audit`. If removing a node still achieves the goal, it gets pruned. The graph stays minimal.
- **Failed nodes decompose into subgraphs** — when a node fails verification and retry doesn't help, `TaskDecompose` breaks it into 2-3 finer sub-nodes. The model faces appropriately scoped sub-tasks at every step. Upstream results are preserved.
- **I/O verification, not "looks right"** — `verify_output()` does structural + type checking programmatically against `output_spec`. No reliance on LLM self-judgment.
- **Independent audit, not self-check** — `subagent_type="auditor"` runs with restricted read-only tools. Audit and execution are separated.
- **Clean node-level memory** — `TaskWriteMemory` generates `modules/node_N/memory.md` programmatically with `json.dumps()`, bypassing LLM summarization bias.

## One-line summary

GraphyAgent is not just another coding agent.
It is a graph-native runtime for coding agents that decomposes complex tasks into verifiable nodes with typed I/O specs, automatic recovery, gate control, evidence chains, and independent audit — keeping long workflows controllable and correct.