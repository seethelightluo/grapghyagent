# graph_optimizer Skill

## 职责

负责离线图级优化。它读取多个 GraphRun/NodeRun 轨迹，计算边效用、挖掘重复成功子图并生成版本化结构建议。它不能在线原地删除或改写运行中的 workflow。

## 推荐命令

- `analyze_graph_runs`：汇总历史运行、边效用、子图候选和建议。
- `compute_edge_utilities`：计算单独的边效用表。
- `mine_reusable_subgraphs`：从成功运行路径中找可复用 motif。
- `suggest_structure_changes`：生成机器可消费结构建议。
- `materialize_new_graph_version`：把建议写入新 graph version，可选择持久化。

## 推荐下一模块

- 生成候选版本后调度到 `evaluation.compare_graph_versions`。
- 可复用子图进入 `playbooks.serialize_subgraph`。
- 通过评估后调度到 `graph_saver.save_workflow`。

## 失败处理

- 历史运行不足时只返回低置信建议或空建议，不允许根据单次幸运运行硬删除结构。
