# execution_lineage Skill

## 职责

负责 GraphRun/NodeRun 的确定性执行血缘、checkpoint verifier、dirty node 判断和最小 replay 边界。它是底层状态基座，不执行 LLM 反思，不触发 node react，也不直接修改 workflow 结构。

## 推荐命令

- `verify_node_inputs`：节点执行前验证输入 artifact、上游输出和 fingerprint。
- `record_node_lineage`：节点执行后写入 NodeRun lineage record。
- `plan_replay_from_checkpoint`：从 checkpoint 和当前 graph 计算 reusable/dirty 节点。
- `list_dirty_nodes`：查看 checkpoint replay 或已有 lineage 中的 dirty 节点。

## 推荐下一模块

- preflight 通过后进入 `node_memory.prepare_node_context`。
- postflight 通过后进入 `reflection.run_online_reflection`。
- 需要实际重跑时进入 `graph_runner.resume_from_checkpoint` 或 `graph_runner.run_graph`。

## 失败处理

- lineage 只能返回 blocked/dirty/reusable 结论；恢复策略交给 `graph_runner`、`model_routing` 或 `task_decompose`。
