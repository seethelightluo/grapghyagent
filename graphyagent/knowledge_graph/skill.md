# knowledge_graph Skill

## 职责

负责把 project 文件、workflow graph、GraphRun 和 NodeRun 转换为结构化 Knowledge Graph，并为节点构建 Node-Knowledge View。它只维护知识节点、边和权重，不直接修改 workflow 结构。

## 推荐命令

- `build_for_project`：从 project/graph 文件和节点定义构建或刷新知识图。
- `refresh_from_run`：GraphRun 完成后把运行摘要和 NodeRun 轨迹写入知识图。
- `build_view_for_node`：为单个节点返回 background/evidence/quarantine 分层视图。
- `update_weights_from_feedback`：根据 online reflection 标签更新节点条件权重。

## 推荐下一模块

- 节点执行前进入 `node_memory.prepare_node_context`。
- 节点完成后进入 `reflection.run_online_reflection` 和 `update_weights_from_feedback`。
- 多次运行后进入 `graph_optimizer.analyze_graph_runs`。

## 失败处理

- 知识图为空时，先运行 `build_for_project`；仍为空时允许返回空视图，不阻断 graph_runner。
