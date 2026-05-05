# Why GraphyAgent / 为什么选择 GraphyAgent

> 先看一个真实图规划（example2），再看 GraphyAgent 如何把任务拆成必要子模块、在必要处递归下钻，并与现在具备 ReAct 能力的 Claude Code 对比。

## How to use / 使用方式

- 切换语言 / Switch language: [中文](#zh) | [English](#en)
- 在线示例与快速上手页面: https://seethelightluo.github.io/grapghyagent/
- 先打开上面的页面，再按照图式规划、递归下钻、独立 memory 和审计流程理解 GraphyAgent 的使用方式。

<a id="zh"></a>
## 中文

## example2 图规划（原始图）

```
node_1 (Define Univ & Disciplines)
   │
   ▼
node_2 (Collect Rankings Data)
   │
   ▼
node_3 (Validate Data)
   │
   ├──────────────┐
   ▼              ▼
node_4           node_5
(Calc FP Error)  (Gen Statistics)
   │              │
   └──────┬───────┘
          ▼
       node_6
    (Gen TXT Output)
```

## example2 节点拆分（任务与门禁）

- node_1：定义 10 所大学 + 10 个学科（范围定界）
- node_2：收集排名数据（核心数据采集）
- node_3：数据校验（结构完整性 + 去重 + 计数）
- node_4：误差分析（总体排名 vs 学科平均）
- node_5：统计汇总（均值/方差/极值/计数）
- node_6：生成最终 TXT 输出

## GraphyAgent 的核心能力

### 1) 先做“必要性筛选”的图式规划
- 不是把所有步骤都塞进同一个提示词里，而是先设计只对目标真正必要的子模块。
- 对长任务、并行任务和复杂任务，先把结构定清楚，再执行。
- 每个节点都有清晰的输入、输出和 Gate，方便复核、回滚和重跑。

### 2) 递归下钻到子子模块，解决单个节点的困难问题
- 当某个节点本身过大、过难，或者原始模型一轮无法稳定完成时，GraphyAgent 会继续把它拆成更细的子图。
- 这让“一个问题解不出来”不再意味着整条链路失败，而是可以在更细的粒度上继续推进。
- 递归拆解不是临时补救，而是工作流本身的一部分。

### 3) 子模块 memory 干净且足量
- 每个子模块拥有独立 memory，只装载本节点真正需要的上下文。
- 这样可以避免无关历史、旧结论和噪声在长任务里不断堆积。
- 子模块拿到的是更纯净、也更充足的上下文空间，推理质量更稳定。

### 4) 子模块输出审计更严格
- 节点输出不是“看起来像完成了”就结束，而是要经过契约、Gate 和证据指针的审计。
- 结构化输出、验证规则和审计日志让结果更可复核，也更容易定位失败原因。

### 5) 工作流和任务处理流程可复用
- GraphyAgent 不是只会做一次性的提示词拆分，而是把节点职责、依赖关系、门禁和审计过程沉淀成可复用的工作流。
- 同一套流程可以迁移到不同任务，只需要替换节点内容，不必重写整个思路。

## 与现在具备 ReAct 能力的 Claude Code 对比

| 维度 | GraphyAgent | Claude Code（具备 ReAct 能力） |
| --- | --- | --- |
| 任务组织 | 显式 DAG，先规划必要子模块，再执行 | 在会话中通过推理-行动循环推进任务 |
| 长任务适配 | 先拆图，再按节点推进，适合长链路任务 | 能持续推进，但复杂任务更依赖即时提示与上下文管理 |
| 并行能力 | 天然支持可独立节点并行执行 | 可以做工具调用与循环，但并行结构通常不是成熟方法 |
| 递归能力 | 支持继续下钻到子子模块，解决单节点难题 | 可以继续追问或重规划，但结构化递归较弱 |
| 上下文噪声 | 子模块独立 memory，按节点注入必要上下文 | 共享会话上下文，更容易累积历史噪声 |
| 输出审计 | Gate、验证规则、证据指针、节点级审计 | 更偏向即时响应，审计链路通常没有被显式建模 |
| 流程复用 | 节点模板、工作流、门禁和审计可复用 | 更依赖提示词复用，流程治理不如图式显式 |

## 为什么它更适合复杂与并行问题

- **先规划，再执行**：先筛出必要节点，避免把复杂度全部压在一次推理里。
- **并行与递归兼容**：能并行的节点并行，单节点太大就继续下钻。
- **上下文更干净**：子模块只拿必要信息，避免噪声在长任务中污染判断。
- **审计更严谨**：输出不是只看结果，还要看契约、门禁和证据。
- **流程可复用**：图、节点、审计和 memory 机制可以迁移到新任务。

## 适用场景

- 多步骤研究与报告生成
- 需要并行子任务的复杂问题
- 对可验证性和可追溯性要求高的任务链

<a id="en"></a>
## English

> Start with a real graph plan from example2, then see how GraphyAgent decomposes a task into only the necessary submodules, drills down recursively when a node is still too hard, and compares with Claude Code that already has ReAct.

## How to use

- Switch language / 切换语言: [中文](#zh) | [English](#en)
- Online demo and quick-start page: https://seethelightluo.github.io/grapghyagent/
- Open the page above first, then follow the graph plan, recursive drilling, isolated memory, and audit flow to understand how GraphyAgent is used.

## example2 graph (original)

```
node_1 (Define Univ & Disciplines)
   │
   ▼
node_2 (Collect Rankings Data)
   │
   ▼
node_3 (Validate Data)
   │
   ├──────────────┐
   ▼              ▼
node_4           node_5
(Calc FP Error)  (Gen Statistics)
   │              │
   └──────┬───────┘
          ▼
       node_6
    (Gen TXT Output)
```

## example2 node breakdown (tasks and gates)

- node_1: Define 10 universities + 10 disciplines (scope definition)
- node_2: Collect ranking data (core data collection)
- node_3: Validate data (structural integrity + deduplication + count check)
- node_4: Error analysis (overall rank vs discipline average)
- node_5: Statistics summary (mean / variance / extremes / counts)
- node_6: Generate the final TXT output

## Core capabilities

### 1) Graph planning with necessity filtering
- Do not stuff every step into one prompt; first design only the submodules that are truly necessary.
- For long, parallel, and complex tasks, define the structure first, then execute.
- Each node has clear input, output, and gates for review, rollback, and rerun.

### 2) Recursive drilling into sub-submodules to solve hard single-node problems
- If a node is too large, too hard, or cannot be completed reliably in one pass, GraphyAgent keeps decomposing it into a finer subgraph.
- A node failure does not fail the whole chain; progress continues at a finer granularity.
- Recursive decomposition is part of the workflow, not an emergency patch.

### 3) Clean and sufficiently large per-node memory
- Each submodule has its own memory and only loads the context it actually needs.
- This keeps irrelevant history, old conclusions, and noise from accumulating across long tasks.
- Each node gets a cleaner and more spacious context window, which keeps reasoning stable.

### 4) Stricter output audit for submodules
- Node outputs do not stop at “looks done”; they must pass contract, gate, and evidence-pointer checks.
- Structured output, verification rules, and audit logs make results more reviewable and easier to debug.

### 5) Reusable workflows and task-handling flow
- GraphyAgent is not just a one-off prompt splitter; it turns node roles, dependencies, gates, and audit steps into reusable workflows.
- The same flow can be moved to different tasks by swapping node content instead of rewriting the whole process.

## Comparison with Claude Code with ReAct

| Dimension | GraphyAgent | Claude Code (with ReAct) |
| --- | --- | --- |
| Task organization | Explicit DAG, plan necessary submodules first, then execute | Progresses through a reasoning-action loop inside the conversation |
| Long-task fit | Split first, then run node by node, which works well for long chains | Can keep going, but complex tasks depend more on prompt steering and context management |
| Parallelism | Naturally supports independent node-level parallel execution | Can do tool calls and loops, but parallel structure is usually not a first-class pattern |
| Recursive depth | Can keep drilling down into sub-submodules to solve hard single-node problems | Can ask more questions or re-plan, but structured recursion is weaker |
| Context noise | Each submodule has isolated memory and only gets necessary context | Shared conversation context makes noise easier to accumulate |
| Output audit | Gates, verification rules, evidence pointers, and node-level audits | More focused on immediate response; audit trails are usually not modeled explicitly |
| Workflow reuse | Node templates, workflows, gates, and audits are reusable | More dependent on prompt reuse; workflow governance is less explicit |

## Why it is better for complex and parallel tasks

- **Plan before execution**: isolate the necessary nodes first, so the whole task does not rely on one giant reasoning step.
- **Parallelism and recursion together**: run what can run in parallel, and keep drilling down when a node is still too large.
- **Cleaner context**: each submodule only gets the information it needs, so noise does not pollute long tasks.
- **Stricter audit**: outputs are checked against contracts, gates, and evidence, not just judged by appearance.
- **Reusable flow**: the graph, nodes, audits, and memory model can be carried over to new tasks.

## Use cases

- Multi-step research and report generation
- Complex tasks that need parallel subtasks
- Task chains that require verifiability and traceability
