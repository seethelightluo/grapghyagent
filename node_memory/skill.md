# node_memory Skill

## 职责

负责把 Knowledge Graph、execution lineage 和兼容旧 memory 的检索视图压缩成 Node Memory Packet。packet 必须有边界、类型和日志，不能把全部上下文平铺注入节点。
v0.5 packet 使用 v2 schema，但保留 v1 字段；旧 memory markdown 只能作为 bounded evidence item 或 KG candidate 进入 packet，不能作为第二段原文 prompt 默认注入。

## 推荐命令

- `prepare_node_context`：为节点构建 packet。
- `summarize_context_for_model`：把 packet 渲染成 LLM 可消费摘要。
- `record_context_usage`：记录上下文候选是否被使用。
- `update_gap_state`：记录节点证据缺口。

## 推荐下一模块

- packet 构建前可调用 `execution_lineage.verify_node_inputs` 和 `knowledge_graph.build_view_for_node`。
- 节点执行进入 `graph_runner.run_node`。
- 节点完成后进入 `reflection.run_online_reflection`。

## 失败处理

- 没有候选知识时返回空 evidence packet，并记录 evidence gap；不得把样例或模板塞进上下文补位。
