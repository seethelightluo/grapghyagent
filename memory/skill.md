# memory Skill

## 职责

负责从 GraphyAgent 现有 project/graph/node memory 文件中检索相关长期记忆，并渲染成可注入节点 prompt 的上下文。节点执行、图层规划和失败恢复都应优先使用 `memory.get_memory_context` 或 `memory.find_relevant_memories` 获取当前节点、输入节点、输出节点和历史运行信息。

## 推荐命令

- `find_relevant_memories`：按查询词返回相关记忆记录。
- `get_memory_context`：把相关记忆渲染成 prompt 片段。

## 推荐下一模块

- 节点执行进入 `graph_runner`。
- 记忆写入进入 `data_manager.write_memory`。
- 需要报告渲染进入 `research.render_report`。

## 失败处理

- 找不到相关记忆时返回空上下文，不阻断执行。
- memory 文件损坏时跳过该文件，并继续扫描其他 project/graph/node memory。
