# task_decompose Skill

## 职责

负责把自然语言任务拆成 workflow 图，也负责把过大的节点拆成子图，修正 agent 拆解不清、节点失败后需要更细粒度执行的问题。
拆出的子节点应保留可用的输入/输出说明、gate_condition 和 memory 使用要求；节点执行时由 `graph_runner` 注入 `memory.context.get_memory_context`，因此 description 应包含足够关键词以检索输入节点、输出节点和历史记忆。

## 推荐命令

- `decompose_node`：把一个节点拆成多个子节点。
- `decompose_task_to_graph`：把用户自然语言任务描述生成或重建 workflow 图。

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
