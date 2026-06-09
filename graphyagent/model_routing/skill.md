# model_routing Skill

## 职责

负责 `.env`、简单/复杂 API profile、模型选择、LLM 调用和 fallback。需要选择模型、简单任务失败切复杂任务、图记忆对话时进入 `model_routing`。

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
- 复杂 profile 失败时不要继续盲目重试，调度到 `task_decompose.decompose_node`。
