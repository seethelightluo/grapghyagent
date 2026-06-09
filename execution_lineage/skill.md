# execution_lineage Skill

## 职责

负责 GraphRun/NodeRun 的确定性执行血缘、checkpoint verifier、dirty node 判断和最小 replay 边界。它是底层状态基座，不执行 LLM 反思，不触发 node react，也不直接修改 workflow 结构。

`execution_lineage` 是所有恢复策略必须读取的状态账本，但它不决定怎么恢复。它只回答：

- 当前节点输入是否有效。
- 哪些 artifact / upstream output / executor signature / packet policy 变了。
- 哪些 completed nodes 可复用。
- 哪些节点 dirty，需要重跑。
- 从哪个 checkpoint 可以安全 replay。

它不能调用 LLM，不能判断“应该换模型还是改图”，也不能在线删除节点或断边。

## 推荐命令

- `verify_node_inputs`：节点执行前验证输入 artifact、上游输出和 fingerprint。
- `record_node_lineage`：节点执行后写入 NodeRun lineage record。
- `plan_replay_from_checkpoint`：从 checkpoint 和当前 graph 计算 reusable/dirty 节点。
- `list_dirty_nodes`：查看 checkpoint replay 或已有 lineage 中的 dirty 节点。

## 推荐下一模块

- preflight 通过后进入 `node_memory.prepare_node_context`。
- postflight 通过后进入 `reflection.run_online_reflection`。
- 需要实际重跑时进入 `graph_runner.resume_from_checkpoint` 或 `graph_runner.run_graph`。
- `graph_runner.failure_analysis`、`agent_runtime.recover_graph_failure`、`task_decompose.replan_subgraph` 必须先读取 lineage 的 dirty/reusable/replay boundary，再决定恢复策略。

## 失败处理

- lineage 只能返回 blocked/dirty/reusable/replay-boundary 结论；恢复策略交给 `graph_runner`、`model_routing`、`task_decompose` 或 `agent_runtime`。
- 当 NodeRun 失败时，必须保留 failed node 的 input/output/log artifacts 和 lineage record；后续 graph patch 只能把边标为 `blocked/stale/superseded` 或连接新 recovery output，不能抹掉失败 trace。
- checkpoint resume 必须基于 fingerprint 判断复用，不能只因为 checkpoint 中节点状态为 success 就跳过。
