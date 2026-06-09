# reflection Skill

## 职责

负责 NodeRun 完成后的在线反思标签。它可以标记 upstream output 和 knowledge item 的 useful/unused/critical/risky/insufficient，但不能在线删除节点、边或改写 workflow 结构。

## 推荐命令

- `run_online_reflection`：读取或接收 NodeRun 快照并生成结构化标签。
- `apply_feedback_updates`：把标签应用到 `knowledge_graph` 权重。

## 推荐下一模块

- 反思后调度到 `knowledge_graph.update_weights_from_feedback`。
- 多次运行后调度到 `graph_optimizer.analyze_graph_runs`。
- 证据缺口明显时调度到 `node_memory.update_gap_state` 或 `task_decompose.decompose_node`。

## 失败处理

- 反思无法加载 NodeRun 时返回错误；不得用猜测标签更新权重。
