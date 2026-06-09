# research Skill

## 职责

负责引用列表和报告文件渲染。`research.synthesizer.render_citations` 输出编号引用，`render_without_llm` 在没有 LLM 时确定性生成 Markdown 报告，`render_report` 会写出 Markdown/HTML 文件并返回 `preview_url` 供前端打开预览。

## 推荐命令

- `render_citations`：从 brief/results 渲染引用列表。
- `render_without_llm`：不调用 LLM，生成 Markdown 报告文本。
- `render_report`：写出 Markdown/HTML 报告文件，注册 artifact，并返回预览链接。

## 推荐下一模块

- 需要读取 graph/node outputs 时先调用 `graph_runner.list_run_outputs`。
- 需要把报告关联到 project/graph/node 文件树时调用 `data_manager.register_artifact` 或 `link_artifact_to_file_tree`。
- 需要记忆报告结论时调用 `data_manager.write_memory`。

## 失败处理

- brief 缺失时可用 `outputs` 构造 fallback brief。
- LLM 不可用时继续使用 `render_without_llm`，不得因此阻断报告生成。
