# front_bridge Skill

## 职责

负责 Web/API/CLI 与 agent command queue 的桥接。前端只提交用户意图，后端通过队列执行模块命令并让画板同步状态。

## 推荐命令

- `serve`：启动 Web/API。
- `submit_agent_command`：提交命令。
- `process_agent_command`：处理队列命令。
- `list_agent_commands`：查看命令历史。
- CLI `agent-worker --watch`：持续轮询队列，让后台 agent 处理 Web/CLI 提交的模块命令。
- 兼容 API `/api/projects/*`、`/api/graphs/*`、`/api/files/*`：保留旧响应字段，但内部必须提交 `data_manager` 模块命令。

## 推荐下一模块

- 用户运行图时，调度到 `graph_runner.run_graph`。
- 用户保存图时，调度到 `data_manager.save_graph`；需要版本化时再调度到 `graph_saver.save_workflow`。
- 用户上传、拖动或删除文件时，调度到 `data_manager.import_file`、`data_manager.move_file` 或 `data_manager.delete_file`。
- 用户在项目/图聊天中描述“创建/拆解/生成工作流”时，调度到 `task_decompose.decompose_task_to_graph`。
- Web 只是提交意图并轮询同步时，使用 `agent-worker --watch` 在 CLI 侧持续处理队列。

## 失败处理

- API 命令失败时，调度到 `agent_runtime.recommend_next_modules` 获取恢复建议。
