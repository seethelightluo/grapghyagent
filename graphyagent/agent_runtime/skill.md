# agent_runtime Skill

## 职责

负责模块-命令调度、上下文整理、模块技能读取和队列执行。调用 tool 前应先查询 `agent_runtime.list_modules`，再查询 `agent_runtime.list_module_commands`。

`chat_graph` 的主执行路径使用 Anthropic 风格 `tool_use`/`tool_result` 协议作为全局 ReAct 控制循环；不要恢复文本版动作解析协议。工具循环中的每次调用应记录为 agent tool call trace，并通过 `node_binding` 显式关联真实 GraphRun/NodeRun。

v0.5 在线反思属于节点级 credit assignment：真实 workflow 节点执行后的 reflection/weight update 由 `graph_runner` 与 `reflection` 处理。`agent_runtime` 只标注工具调用是否绑定 workflow 节点，不能把所有 tool_use 都伪装成 NodeRun，也不能在线直接改 workflow 结构。
`execution_lineage` 是 checkpoint/verifier 底座，只能判断 reusable/dirty 和记录 NodeRun lineage；它不是第二套 ReAct，也不能执行恢复策略。

## 推荐命令

- `list_modules`：列出模块。
- `list_module_commands`：列出模块命令。
- `list_module_skills`：读取模块技能。
- `recommend_next_modules`：根据事件和失败信息推荐下一模块。
- `target_context`：读取当前 project/graph/node 上下文。

## 推荐下一模块

- 图持久化进入 `graph_saver`。
- 图执行进入 `graph_runner`。
- 文件和记忆进入 `data_manager`。
- 数据质量进入 `data_audit`。
- 模型选择进入 `model_routing`。
- 节点上下文进入 `knowledge_graph` 和 `node_memory`。
- checkpoint/replay/verifier 判断进入 `execution_lineage`。
- 节点反思进入 `reflection`。
- 历史运行压缩和版本建议进入 `graph_optimizer`，再进入 `evaluation`。
- 可复用子图进入 `playbooks`。
- 长期记忆检索进入 `memory`。
- 可并行子 agent 规划进入 `multi_agent`。
- 引用和报告渲染进入 `research`。

## 失败处理

- 调度失败时读取当前模块的 `skill.md`，再按推荐下一模块生成恢复命令。
