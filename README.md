# GraphyAgent v0.5 Hybrid Memory + Lineage Core

## 中文版

### 1. 核心定位

GraphyAgent v0.5 不是单纯的 LangGraph 工作流，也不是只靠一个全局 ReAct/tool loop 的聊天智能体。它的目标是：

> 一个能根据进度、节点执行结果、失败原因和历史运行反馈，实时判断是否继续、局部修复、暂停重构或离线优化 workflow 的 graph-native agent runtime。

核心分工：

- `agent_runtime` 保留 Anthropic-style tool loop，负责全局 ReAct 和模块命令调度。
- `graph_runner` 是唯一真实执行层，负责 `GraphRun`、`NodeRun`、checkpoint、trace 和 artifact。
- `execution_lineage` 是底层 verifier/checkpoint/dirty-set/replay-boundary 基座。
- `node_memory` 把 React 和 memory 下沉到每个 `NodeRun` 的局部上下文包。
- `model_routing` 和 `task_decompose` 是节点级失败恢复消费者。
- 全局恢复只在节点判断为 graph-level / plan-level failure 后介入，负责图级 ReAct、graph patch/fork 和 checkpoint resume。

### 2. 架构层次表

| 层次 | 主要模块 | 核心功能 | 状态归属 | 禁止事项 |
| --- | --- | --- | --- | --- |
| 全局控制层 | `agent_runtime` | Anthropic-style `tool_use/tool_result` 循环；选择下一模块命令；处理 graph-level recovery | agent tool trace | 不把每个 tool call 伪装成 `NodeRun`；不直接乱改运行中图 |
| 任务规划层 | `task_decompose`, `graph_saver` | 自然语言任务生成 workflow；失败节点拆子图；保存、恢复、fork、merge workflow | graph version / graph patch | 不硬编码样例模板或 benchmark fallback |
| 图执行层 | `graph_runner` | 调度节点；创建 `GraphRun/NodeRun`；写 checkpoint；并行执行 DAG layer；执行 resume | GraphRun / NodeRun / checkpoint | 不绕过 lineage 盲目跳过成功节点 |
| 执行血缘层 | `execution_lineage` | preflight/postflight verifier；input fingerprint；artifact provenance；dirty/reusable/replay plan | lineage records / checkpoint manifest | 不调用 LLM；不做恢复策略；不改图 |
| 节点上下文层 | `node_memory`, `knowledge_graph`, `memory` | 构建 Node Memory Packet；召回 KG evidence；兼容旧 memory | packet / KG view / bounded evidence | 不把旧 memory markdown 作为第二条无界 prompt 注入 |
| 节点校验层 | `node_audit`, `data_audit` | output contract/gate 校验；数据质量、污染、schema、provenance 审计 | audit verdict / gate status | 不承担图级恢复决策 |
| 模型与局部恢复层 | `model_routing`, `task_decompose` | 简单失败切复杂模型；复杂失败拆节点；局部 retry / subgraph recovery | route decision / child graph | 不维护自己的 dirty-set 账本 |
| 在线学习层 | `reflection` | NodeRun 后打 useful/unused/risky/critical/insufficient 标签；更新 KG/边权重 | reflection labels / weight updates | 不在线删除节点或改 workflow |
| 离线优化层 | `graph_optimizer`, `playbooks`, `evaluation` | 多次运行后挖掘高价值边、低价值节点、可复用子图；产出新版本建议并评估 | optimizer suggestions / graph versions | 不在线替换当前运行图 |
| 证据与报告层 | `data_manager`, `research` | 文件、artifact、memory、报告、引用、预览链接 | project files / artifacts / reports | 不把存储层变成 prompt 拼接层 |

### 3. 与 LangChain / Claude Code 的比较

| 维度 | LangChain / LangGraph 常见形态 | Claude Code 常见形态 | GraphyAgent v0.5 |
| --- | --- | --- | --- |
| 核心抽象 | chain、agent executor、graph workflow、state/checkpointer | 全局 ReAct/tool loop，强交互式工具使用 | graph-native runtime：全局 tool loop + workflow graph + lineage + node memory + optimizer |
| 控制流 | 预定义 workflow 或 agent executor 决策 | 模型持续决定下一步 tool call | 全局 `agent_runtime` 做 tool loop；真实节点执行由 `graph_runner` 管 |
| 节点状态 | checkpointer 可保存 state，但语义依赖应用设计 | 主要在对话、文件和 tool trace 中 | 每个 `NodeRun` 有 input/output snapshot、packet、lineage、audit、reflection |
| 记忆方式 | memory/vector store/checkpointer 组合 | 会话上下文、文件系统、工具观察 | hybrid memory：execution lineage、artifact evidence、KG、NodeMemoryPacket、reflection/playbook |
| 失败恢复 | 通常由应用代码或 graph branch 写死 | 模型在同一 tool loop 中继续试 | 先 node-local failure analysis；节点原因局部修；整体原因暂停 GraphRun 并升级全局 ReAct 改图 |
| 复用进度 | checkpointer 可恢复，但 dirty/reuse 语义需自建 | 依赖人工判断或上下文记忆 | `strict_fingerprint` 判断 graph/node/input/executor/packet policy 是否可复用 |
| 图修改 | 可通过程序修改 graph，通常偏静态 | 可以改文件/计划，但不一定形成版本化 workflow | graph patch/fork/version 由 `graph_saver` 管；运行中失败节点保留 trace，边可 blocked/stale/superseded |
| 学习闭环 | 通常外接 eval / memory update | 总结经验，但结构沉淀弱 | `reflection` 在线打标；`graph_optimizer` 离线剪枝、合并、提炼 playbook |
| 审计性 | 取决于应用日志 | tool trace 强，但节点契约弱 | GraphRun/NodeRun/lineage/audit/artifact/report 全链路可查 |
| 与 Claude Code 的关系 | 可替代部分 agent orchestration | 强全局工具循环 | 不替代 Claude Code 式 tool loop，而是把 ReAct 和 memory 局部化到可维护 workflow |

### 4. 标准失败升级路径

GraphyAgent 的恢复目标不是“失败后继续瞎试”，而是先诊断失败归因，再决定局部恢复还是图级重构。

```text
NodeRun failed
  -> graph_runner 保存失败 NodeRun、日志、参数、artifact、checkpoint
  -> execution_lineage 记录 input fingerprint、output/log artifacts、dirty 边界
  -> node_audit / executor 生成 failure evidence
  -> failure_analysis 判断失败范围
     - node_local: 节点自身、模型能力、参数、局部输入、环境小问题
     - evidence_level: 上游证据不足、数据来源不可信、schema/provenance 缺失
     - environment_level: Python/CUDA/GPU/依赖/权限/外部服务问题
     - graph_level / plan_level: 原任务拆解、依赖边、执行策略、整体假设错误
```

| 失败归因 | 处理方式 | 典型模块 | 是否暂停 GraphRun |
| --- | --- | --- | --- |
| `node_local` | 换模型、改 prompt、局部 retry、拆当前节点 | `model_routing`, `task_decompose.decompose_node`, `graph_runner.run_node` | 不一定暂停整图，只阻断当前节点下游 |
| `evidence_level` | 新增取证/审计节点，修正上游输入，再 resume | `data_audit`, `node_memory`, `knowledge_graph`, `task_decompose` | 暂停受影响分支 |
| `environment_level` | 保存环境错误，修复依赖或降级执行策略 | `graph_runner`, `model_routing`, `data_manager` | 暂停受影响节点 |
| `graph_level` / `plan_level` | 暂停 GraphRun，升级给全局 agent，重构失败节点相关边和策略 | `agent_runtime`, `graph_saver`, `task_decompose`, `execution_lineage`, `graph_runner.resume_from_checkpoint` | 是 |

图级恢复标准流程：

```text
graph_runner marks run as paused_for_replan
  -> failed node remains in trace
  -> downstream edges become blocked/stale/superseded
  -> checkpoint is saved
  -> agent_runtime global tool loop reads run state
  -> agent_runtime calls task_decompose / graph_saver to create patch or fork
  -> graph_runner.resume_from_checkpoint reuses unchanged successful nodes
  -> only dirty/recovery branches rerun
```

说明：

- 失败节点不应被静默删除；它是 trace 和学习材料。
- 可以断开失败节点到下游的边，防止错误 artifact 污染最终输出。
- 可以新增 `analyze_failure`、`repair_inputs`、`alternative_method`、`retry_node` 等 recovery branch。
- 真正删除、合并、降级节点更适合由 `graph_optimizer` 在离线阶段提出新 graph version。

### 5. 模块与 tool / 功能顺序说明

#### 5.1 `agent_runtime`

职责：全局模块命令调度和 Anthropic-style ReAct/tool loop。它负责“下一步调用哪个模块命令”，不负责伪造 `NodeRun`。

| Tool / 功能 | 作用 | 常见后续 |
| --- | --- | --- |
| `chat_graph` | 面向 project/graph 的主聊天入口，内部使用 `tool_use/tool_result` 循环 | `InspectWorkspace`, `DecomposeTaskToGraph`, `RunGraph`, `UpdateWorkflowGraph` |
| `list_modules` | 列出可用模块 | `list_module_commands` |
| `list_module_commands` | 列出某模块可调用命令 | 对应模块命令 |
| `list_module_skills` | 读取模块 skill 指南 | `recommend_next_modules` |
| `recommend_next_modules` | 根据事件或失败文本推荐下一模块 | failure recovery |
| `target_context` | 获取当前 project/graph/node 上下文 | 任意模块调度 |
| `execute_tool` | 执行注册工具 | 工具结果进入 tool loop |

全局恢复时，`agent_runtime` 读取 `GraphRun`、`NodeRun`、lineage、audit 和 reflection，然后通过模块命令生成 graph patch/fork，而不是直接改内存状态。

#### 5.2 `core`

职责：GraphConfig、schema 和基础结构检查。

| Tool / 功能 | 作用 |
| --- | --- |
| `load_graph_config` | 读取 JSON/YAML 图配置 |
| `inspect_graph_config` | 归一化图配置并查看路由预览 |
| `graph_schema` | 返回支持的 graph/node/executor/contract schema |

#### 5.3 `data_manager`

职责：项目、文件、artifact、旧 memory 和虚拟文件树。

| Tool / 功能 | 作用 |
| --- | --- |
| `create_project` / `create_graph` / `save_graph` | 维护 project 和 graph 基础数据 |
| `import_file` / `move_file` / `delete_file` | 管理 project 文件和节点文件 |
| `write_memory` / `read_memory` | 读写兼容旧 memory |
| `register_artifact` / `list_artifacts` | 管理内容寻址 artifact |
| `snapshot` / `list_managed_files` | 排查项目、图、节点和文件树状态 |

#### 5.4 `task_decompose`

职责：自然语言任务生成 workflow；失败节点或过大节点拆成更小子图。

| Tool / 功能 | 作用 | 使用场景 |
| --- | --- | --- |
| `decompose_task_to_graph` | 把用户目标生成或重建 workflow graph | 初始规划、plan-level recovery |
| `decompose_node` | 把失败或过大的节点拆成子节点 | node-local failure、职责过宽 |
| `build_retry_prompt` | 构造失败重试提示 | 局部 retry |
| `build_decompose_prompt` | 构造拆解提示 | 子图生成 |

说明：`decompose_node` 已经存在，是节点失败后继续拆解的核心入口；plan-level failure 需要通过全局 loop 调用它或重新生成相关子图。

#### 5.5 `graph_saver`

职责：workflow 持久化、版本、恢复、导入导出和 checkpoint fork。

| Tool / 功能 | 作用 |
| --- | --- |
| `save_workflow` | 保存当前图版本 |
| `list_versions` | 查看历史版本 |
| `restore_version` | 恢复指定版本 |
| `export_workflow` / `import_workflow` | 导出或导入可复用 workflow |
| `merge_workflow` | 合并外部图、模板图或同项目图 |
| `fork_from_checkpoint` | 从 GraphRun checkpoint 创建新 workflow 分支 |

图级恢复时，推荐保留失败 run，用 `fork_from_checkpoint` 或 graph patch 生成 recovery version。

#### 5.6 `graph_runner`

职责：唯一真实执行器。它创建 `GraphRun` / `NodeRun`，写 checkpoint、trace、artifact，并根据 lineage 做 resume/reuse。

| Tool / 功能 | 作用 |
| --- | --- |
| `run_graph` | 执行整图 |
| `run_node` | 执行节点及其上游依赖 |
| `resume_from_checkpoint` | 从 checkpoint 续跑，默认 `strict_fingerprint` |
| `list_runs` / `show_run` / `list_node_runs` | 查看运行和节点运行列表 |
| `timeline` / `show_node_run` | 查看时间线和单个 NodeRun 详情 |
| `list_run_outputs` / `list_run_errors` | 查看输出和错误 |
| `list_graph_outputs` | 查看 graphoutput |
| `list_checkpoints` / `read_checkpoint` | 查看 checkpoint |
| `show_run_manifest` | 查看配置 hash、路由、输出计数 |
| `export_trace_dataset` | 导出 GraphRun/NodeRun 轨迹数据集 |

标准节点生命周期：

```text
verify_node_inputs
  -> prepare_node_context
  -> execute node
  -> validate_node_outputs
  -> record_node_lineage
  -> run_online_reflection
  -> apply_feedback_updates
  -> checkpoint
```

已实现的图级恢复接口：

| 接口 | 作用 |
| --- | --- |
| `classify_node_failure` | 生成 node_local / graph_level / plan_level 等失败归因 |
| `pause_for_replan` | graph-level / plan-level failure 时把 GraphRun 标记为 `paused_for_replan` 并写入 replan event |
| `mark_edges_blocked` | 标记失败节点下游边为 blocked/stale/superseded，并可把下游依赖改接到 replacement node |

#### 5.7 `execution_lineage`

职责：确定性执行血缘、checkpoint verifier、dirty node 判断和 replay boundary。

| Tool / 功能 | 作用 |
| --- | --- |
| `verify_node_inputs` | 节点执行前验证输入 artifact、上游输出和 fingerprint |
| `record_node_lineage` | 节点执行后写入 lineage record |
| `plan_replay_from_checkpoint` | 比较 checkpoint 与当前 graph/state，计算 reusable/dirty 节点 |
| `list_dirty_nodes` | 查询 dirty/reusable 节点 |

它只回答“什么变了、哪里能复用、哪里要重跑”，不决定“如何修”。

#### 5.8 `knowledge_graph`

职责：语义记忆、知识节点/边/权重、Node-Knowledge View。

| Tool / 功能 | 作用 |
| --- | --- |
| `build_for_project` | 从 project 文件、graph、节点定义构建 KG |
| `refresh_from_run` | GraphRun 后把运行摘要和 NodeRun 写入 KG |
| `build_view_for_node` | 为节点返回 background/evidence/quarantine 分层视图 |
| `update_weights_from_feedback` | 根据 reflection 标签更新权重 |

#### 5.9 `node_memory`

职责：把 lineage、KG 和兼容旧 memory 压缩成 `NodeMemoryPacket`。

| Tool / 功能 | 作用 |
| --- | --- |
| `prepare_node_context` | 构建 v2 Node Memory Packet |
| `summarize_context_for_model` | 把 packet 渲染成模型可消费摘要 |
| `record_context_usage` | 记录上下文候选是否被使用 |
| `update_gap_state` | 记录证据缺口 |

规则：

- 旧 `memory.context` 只能作为 bounded evidence item 或 KG candidate。
- 不允许把旧 memory markdown 默认整段注入 prompt。
- packet hash 和 retrieval policy version 要参与 checkpoint reuse 判断。

#### 5.10 `memory`

职责：兼容旧 project/graph/node memory。

| Tool / 功能 | 作用 |
| --- | --- |
| `find_relevant_memories` | 按查询词找相关记忆 |
| `get_memory_context` | 渲染兼容上下文片段 |

长期方向：作为兼容数据源，逐步通过 `knowledge_graph` / `node_memory` 进入 packet，不再是默认第二条 prompt 通道。

#### 5.11 `node_audit`

职责：节点必要性、contract、gate、删除风险审计。

| Tool / 功能 | 作用 |
| --- | --- |
| `audit_node_necessity` | 判断节点是否必要、可合并或可删除 |
| `validate_node_contract` | 校验 input_spec、required inputs、gate、输出绑定 |
| `validate_node_outputs` | 节点执行后校验 output contract |

#### 5.12 `data_audit`

职责：数据质量、schema、provenance、污染、后训练数据风险审计。

| Tool / 功能 | 作用 |
| --- | --- |
| `audit_dataset` | 输出 audit_report、record_tags、evidence、quality_dimensions、risk_assessment、review_queue |

数据审计结论应作为 evidence artifact 进入 KG/packet，不应直接变成无来源 prompt 文本。

#### 5.13 `model_routing`

职责：API profile、简单/复杂模型路由、LLM fallback。

| Tool / 功能 | 作用 |
| --- | --- |
| `read_settings` / `update_settings` | 读写本地 API 配置 |
| `route_node` | 预览节点路由 |
| `chat_completion` | 按 profile 调用 LLM，可配置 fallback |

恢复规则：

- 简单 profile 失败时可切复杂 profile。
- 复杂 profile 失败后不要盲目重试，应进入 `task_decompose.decompose_node` 或升级 graph-level recovery。

#### 5.14 `reflection`

职责：NodeRun 后在线 credit assignment。

| Tool / 功能 | 作用 |
| --- | --- |
| `run_online_reflection` | 读取 NodeRun/packet，生成 upstream 和 KG 使用标签 |
| `apply_feedback_updates` | 把标签应用到 KG/edge 权重 |

它可以打标签和更新权重，不能在线删除节点、断边或改图。

#### 5.15 `graph_optimizer`

职责：离线图优化。

| Tool / 功能 | 作用 |
| --- | --- |
| `analyze_graph_runs` | 汇总历史运行、边效用、子图候选和建议 |
| `compute_edge_utilities` | 计算边效用 |
| `mine_reusable_subgraphs` | 挖掘可复用 motif |
| `suggest_structure_changes` | 生成结构建议 |
| `materialize_new_graph_version` | 物化候选 graph version |

它可以建议删除、合并、降级低价值审计节点，但不能在线修改当前运行图。

#### 5.16 `playbooks`

职责：可复用子图 motif 和经验沉淀。

| Tool / 功能 | 作用 |
| --- | --- |
| `serialize_subgraph` | 把一组节点序列化为 playbook |
| `match_playbooks` | 按任务或图节点关键词匹配 playbook |

playbook 必须来自重复成功结构、用户显式提供结构或 optimizer 证据；不能来自 benchmark 样例污染。

#### 5.17 `evaluation`

职责：graph version 回归评估和 promotion 前比较。

| Tool / 功能 | 作用 |
| --- | --- |
| `compare_graph_versions` | 比较 base/candidate graph |
| `graph_metrics` | 计算单图结构指标 |
| `load_task_set` | 加载外部 task set |
| `render_evaluation_report` | 渲染评估报告 |

#### 5.18 `multi_agent`

职责：为并行 DAG layer 生成 node-runner 子 agent 计划。

| Tool / 功能 | 作用 |
| --- | --- |
| `plan_parallel_node_agents` | 分析可并行节点并生成子 agent 任务 |
| `create_agent_task` | 创建单个子 agent 任务描述 |

真实执行仍由 `graph_runner` 完成。

#### 5.19 `research`

职责：引用和报告渲染。

| Tool / 功能 | 作用 |
| --- | --- |
| `render_citations` | 渲染编号引用 |
| `render_without_llm` | 不调用 LLM 生成 Markdown 报告 |
| `render_report` | 写出 Markdown/HTML 报告并注册 artifact |

#### 5.20 `front_bridge`

职责：Web/API/CLI 与后端 command queue 的桥接。

| Tool / 功能 | 作用 |
| --- | --- |
| `serve` | 启动 Web/API |
| `submit_agent_command` | 提交命令 |
| `process_agent_command` | 处理队列命令 |
| `list_agent_commands` | 查看命令历史 |
| `agent-worker --watch` | CLI 持续处理队列命令 |

前端只提交意图，复杂 routing 和 recovery 应留在后端模块命令中。

### 6. 反样例污染规则

GraphyAgent 的 decomposition、packet construction、recovery、optimizer、playbook 和 evaluation 路径禁止引入 benchmark 样例污染。

禁止：

- 硬编码 benchmark sample 或 task template answer。
- 根据评测题格式写固定 fallback。
- 在 prompt/recovery/KG/playbook 中注入样例答案。
- 用示例数据污染 KG 权重或 optimizer 统计。

允许：

- 模块 `skill.md` 中的通用操作原则。
- agent-level 行为提示词。
- 通用验证、搜索、引用、证据要求。
- 与具体 benchmark 答案无关的模块接口说明。

### 7. 当前实现状态

已经具备：

- 全局 Anthropic-style tool loop。
- `GraphRun` / `NodeRun` 执行和 trace。
- `execution_lineage` preflight / record / replay plan。
- `NodeMemoryPacket` v2 和 packet hash。
- `model_routing` 复杂模型 fallback。
- `task_decompose.decompose_node` 失败节点拆解入口。
- `resume_from_checkpoint` strict fingerprint 复用。
- online reflection 和 KG 权重更新。

本次已补上的图级恢复接口：

- `classify_node_failure`：失败归因。
- `pause_for_replan`：graph-level failure 暂停当前 GraphRun。
- `mark_edges_blocked/stale/superseded`：阻断失败输出污染下游。
- `replan_subgraph`：生成图级 recovery patch，可选择 `save/apply` 写回当前 workflow。
- `recover_graph_failure`：全局恢复编排，按 failure_scope 决定节点局部恢复还是图级 pause + replan。
- skill 中把 node-local recovery 与 graph-level recovery 的升级路径持续保持一致。

已验证：

- 全包 Python 语法编译通过。
- 模块主接口 import 和新 module-command 注册解析通过。
- `agent_runtime.recover_graph_failure` 端到端烟测通过，可从 graph-level failure 生成候选 recovery branch。

## English Version

GraphyAgent v0.5 is a graph-native agent runtime, not just a static LangGraph workflow and not just a global chat-style ReAct agent. It keeps the global Anthropic-style tool loop in `agent_runtime`, but pushes React and memory into bounded, auditable, node-local execution through `graph_runner`, `execution_lineage`, `node_memory`, `knowledge_graph`, and `reflection`.

The main distinction is:

- Global loop: decides which module command to call next.
- Workflow runtime: creates real `GraphRun` and `NodeRun` records.
- Lineage: decides what changed, what is stale, and what can be reused.
- Node memory: decides what each node is allowed to see.
- Recovery: node-local failures go through `model_routing` or `task_decompose`; graph-level failures pause the run and escalate to global ReAct.
- Offline optimization: repeated traces become graph-version suggestions, playbooks, and evaluation candidates.

Compared with LangChain/LangGraph, GraphyAgent makes lineage, node memory, audit, reflection, and optimizer first-class module surfaces instead of leaving those policies to application code. Compared with Claude Code, GraphyAgent keeps the strong tool loop but binds tool use to workflow state, artifacts, checkpoints, and replayable node traces.

Current implemented recovery commands:

- `graph_runner.classify_node_failure`
- `graph_runner.pause_for_replan`
- `graph_runner.mark_edges_blocked`
- `task_decompose.replan_subgraph`
- `agent_runtime.recover_graph_failure`

The current validation pass covers Python compilation, module imports, command registry resolution, and an end-to-end recovery smoke test that creates a candidate recovery branch from a graph-level node failure.
