# core Skill

## 职责

负责 GraphConfig 加载、schema 校验和基础结构解释。遇到外部图配置、导入前检查、配置格式错误时先进入 `core`。

## 推荐命令

- `load_graph_config`：读取 JSON/YAML 图配置。
- `inspect_graph_config`：归一化图配置并查看路由预览。
- `graph_schema`：返回当前图配置 schema，包含 `subgraph`、`http`、`sqlite` / `db_query` 等 executor 类型和节点 contract/gate 字段。

## 推荐下一模块

- 配置有效后，调度到 `graph_saver.save_workflow` 固化版本。
- 需要执行时，调度到 `graph_runner.run_graph`。
- 发现节点结构可疑时，调度到 `node_audit.audit_node_necessity`。

## 失败处理

- schema 或依赖错误时，先调度到 `task_decompose.decompose_node` 或 `graph_saver.restore_version`。
