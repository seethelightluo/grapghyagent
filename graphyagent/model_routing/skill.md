# model_routing Skill

## 职责

负责 `.env`、简单/复杂 API profile、模型选择、LLM 调用和 fallback。需要选择模型、简单任务失败切复杂任务、图记忆对话时进入 `model_routing`。

`model_routing` 只处理 node-local 的模型/提示词/能力问题，不负责图级重规划。典型适用范围：

- 简单模型能力不足。
- prompt 不清或上下文预算不足导致的节点局部失败。
- 节点任务本身成立，但当前模型 profile 不适合。
- 单个 LLM 节点需要切复杂模型、换 provider 或调整调用参数。

不适用范围：

- 上游证据缺失或数据 provenance 有问题。
- workflow 拆解或依赖边错误。
- 失败节点输出不可信且会污染下游。
- 多次复杂模型重试仍无法满足 output contract。

## 推荐命令

- `read_settings` / `update_settings`：读写本地 API 配置。
- `route_node`：预览节点路由。
- `chat_completion`：按 profile 调用 LLM，可配置 fallback。

## 推荐下一模块

- 路由出模型后，调度到 `graph_runner.run_node` 或 `graph_runner.run_graph`。
- 复杂模型也失败时，调度到 `task_decompose.decompose_node`。
- 需要记录推理过程时，调度到 `data_manager.write_memory`。

## 失败处理

- 简单 profile 失败时切到复杂 profile。
- 复杂 profile 失败时不要继续盲目重试，先把失败原因返回给 `graph_runner.failure_analysis`。
- 如果 failure_scope 仍是 `node_local`，调度到 `task_decompose.decompose_node` 做局部拆解。
- 如果证据显示是 `graph_level` / `plan_level`，不要继续路由模型；上报 `agent_runtime` 做图级恢复。
