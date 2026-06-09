# data_manager Skill

## 职责

负责 project、graph、文件、节点目录、模块视图和 project/graph/node/file memory。用户给节点放文件、移动文件、删除文件、查看记忆时优先进入 `data_manager`。

## 推荐命令

- `create_project` / `create_graph` / `save_graph`：维护当前项目和图。
- `import_file` / `move_file` / `delete_file`：维护文件同步。
- `write_memory` / `read_memory`：维护作用域记忆。
- `register_artifact` / `list_artifacts`：管理内容寻址工件。

## 推荐下一模块

- 文件是数据集时，调度到 `data_audit.audit_dataset`。
- 图结构改变后，调度到 `graph_saver.save_workflow`。
- 用户要求执行时，调度到 `graph_runner.run_graph` 或 `graph_runner.run_node`。

## 失败处理

- 找不到 project/graph/node 时，先调度到 `data_manager.snapshot`。
- 文件同步失败时，调度到 `data_manager.list_managed_files` 检查虚拟树。
