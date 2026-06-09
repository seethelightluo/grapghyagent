# graph_saver Skill

## 职责

保存、版本化、恢复和导出 GraphyAgent workflow。凡是用户或上游 agent
表达“保存当前图”“固定这个工作流”“恢复某个版本”“导出可复用图配置”，优先进入
`graph_saver` 模块，而不是直接调用 `graph_runner`。

## 推荐命令

- `save_workflow`：当前图完成一次结构性编辑后调用，写入版本快照。
- `list_versions`：用户询问历史版本或恢复前先查看可用版本。
- `restore_version`：恢复到指定版本，随后建议调用 `node_audit.audit_node_necessity` 或保存新版本。
- `export_workflow`：导出可复用图配置。
- `import_workflow`：把外部图配置导入项目并创建初始版本。
- `merge_workflow`：把外部图、模板图或同项目图安全合并到当前 workflow。
- `fork_from_checkpoint`：从 GraphRun checkpoint 创建新的 workflow 分叉。若只是同一 workflow 续跑，优先用 `graph_runner.resume_from_checkpoint`。

## 推荐下一模块

- 保存成功后，如果要执行，调度到 `graph_runner.run_graph`。
- 合并 workflow 后，调度到 `node_audit.audit_node_necessity` 检查依赖合理性。
- 恢复版本后，调度到 `node_audit.audit_node_necessity` 或 `graph_runner.run_graph`。
- 从 checkpoint 分叉后，调度到 `graph_runner.run_graph` 执行新分支或调度到 `data_manager.write_memory` 记录分叉意图。
- 导入包含数据文件的图后，调度到 `data_audit.audit_dataset` 或由 `data_manager.import_file` 自动审计。

## 失败处理

- 如果保存失败，先调度到 `data_manager.snapshot` 确认 project/graph 是否存在。
- 如果恢复版本失败，调度到 `list_versions` 获取可恢复版本，再让上层 agent 重新选择。
