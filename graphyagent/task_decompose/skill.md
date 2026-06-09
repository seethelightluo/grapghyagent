# task_decompose Skill

## 职责

负责把自然语言任务拆成 workflow 图，也负责把过大的节点拆成子图，修正 agent 拆解不清、节点失败后需要更细粒度执行的问题。
拆出的子节点应保留可用的输入/输出说明、gate_condition、Node Memory Packet 使用要求和 lineage 依赖说明；节点 description 应包含足够关键词以便 `knowledge_graph` / `node_memory` 检索输入节点、输出节点和历史运行证据。

需要区分两种恢复：

- 失败节点拆解：`failure_scope=node_local` 时，`decompose_node` 只拆当前失败节点，产出诊断、修复、重试等局部子节点。
- 相关子图重规划：`failure_scope=graph_level` / `plan_level` 时，不应只拆当前节点，而应生成包含失败节点、关键上游、受影响下游和新 recovery branch 的 patch/subgraph。

## 推荐命令

- `decompose_node`：把一个节点拆成多个子节点。
- `decompose_task_to_graph`：把用户自然语言任务描述生成或重建 workflow 图。

## 已实现的恢复 module-command

- `replan_subgraph`：针对 plan-level failure 生成相关子图 patch，包括断开 failed edge、创建 recovery nodes、重连下游依赖和保留可复用上游节点。

## 仍可补充的 module-command

- `build_graph_patch`：把拆解结果表达为可交给 `graph_saver` 保存或 fork 的结构化 patch。

## 推荐下一模块

- 拆解后，调度到 `node_audit.audit_node_necessity` 刷新必要性。
- 拆解后，调度到 `graph_saver.save_workflow` 保存新版本。
- 任务生成图后，调度到 `graph_saver.save_workflow` 固化初始版本。
- 用户要求继续执行时，调度到 `graph_runner.run_graph`。
- 拆解出同一层多个可并行节点时，调度到 `multi_agent.plan_parallel_node_agents` 生成子 agent 计划。
- 最终输出需要用户预览时，调度到 `research.render_report`。

## 失败处理

- 拆解目标不存在时，调度到 `data_manager.snapshot`。
- 拆解后依赖不合理时，调度到 `node_audit.audit_node_necessity`。
- 对 `node_local` failure，优先生成局部子节点，例如 `analyze_failure`、`repair_inputs`、`retry_node`，并保留原失败节点 trace。
- 对 `graph_level` / `plan_level` failure，生成 patch/subgraph，而不是只拆当前节点；patch 应说明哪些边要 `blocked/stale/superseded`，哪些成功节点可复用，哪些下游需要重新连接。
- 拆解出的 recovery graph 必须保存到 `graph_saver.save_workflow` 或通过 `graph_saver.fork_from_checkpoint` 固化，随后由 `graph_runner.resume_from_checkpoint` 续跑。
