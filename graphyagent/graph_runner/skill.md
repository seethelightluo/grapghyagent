# graph_runner Skill

## 职责

负责执行 graph/node，产出 GraphRun、NodeRun、checkpoint、graphoutput 和运行轨迹。用户点击运行、CLI 自动执行或后台 worker 执行时进入 `graph_runner`。
节点 executor 可直接使用 `subgraph` 类型运行一个嵌套 GraphConfig，并把子图 graphoutput 汇总为父节点输出。
节点 executor 也支持 `http` 工具调用和只读 `sqlite` / `db_query` 查询，输出会作为普通 artifact 注册。
每个节点运行前会调用 `node_audit.validate_node_contract` 的同源校验逻辑；显式 blocked/closed gate 或缺失 required input 会让节点失败并进入恢复流程。
每个 LLM 节点 prompt 会注入 `memory.context.get_memory_context` 生成的相关 project/graph/node 记忆，检索时应覆盖当前节点、输入节点和 output_nodes，以便子节点知道上游输入、历史输出和节点记忆。
每个节点执行前还会调用 `task.store.check_gate_conditions` 的 DAG gate 检查；上游节点未成功、上游 artifact 缺失/为空，或上游声明 gate_condition 但 gate 未打开时，当前节点必须阻断，不能继续生成无关 LLM 输出。
每个节点执行前先调用 `execution_lineage.verify_node_inputs` 做 deterministic preflight，再调用 `node_memory.prepare_node_context` 构建 Node Memory Packet；节点完成后先写 lineage/postflight，再调用 `reflection.run_online_reflection` 写入 upstream/knowledge 使用标签；GraphRun 完成后调度 `knowledge_graph.refresh_from_run` 更新 Knowledge Graph。
从 checkpoint 续跑时默认使用 `strict_fingerprint`：只有图节点定义、输入 artifact、executor signature 和 packet policy 未变化的成功节点才标记为 reused；dirty 节点会重新执行。

## 推荐命令

- `run_graph`：执行整图。
- `run_node`：执行节点及其上游依赖。
- `list_runs` / `show_run` / `list_node_runs`：查看轨迹。
- `show_run_manifest`：查看 GraphRun 的配置 hash、sanitized GraphConfig、experiment、router/provider 摘要和输出计数。
- `timeline` / `show_node_run`：查看图运行时间线和单个节点运行详情。
- `list_run_outputs` / `list_run_errors`：查看输出工件、graphoutput 和错误日志路径。
- `list_graph_outputs` / `list_checkpoints` / `read_checkpoint`：查看输出和 checkpoint。
- `resume_from_checkpoint`：从 checkpoint 的 GraphState 续跑当前图，默认按 strict fingerprint 复用未变化的成功节点并重跑 dirty 节点。
- `export_trace_dataset`：把 GraphRun/NodeRun 轨迹导出为 JSONL 训练/复盘数据集，并注册为 artifact。

## 推荐下一模块

- 执行前可调度到 `graph_saver.save_workflow` 保存版本。
- 执行前需要上下文路由时，调度到 `knowledge_graph.build_view_for_node` 或 `node_memory.prepare_node_context`。
- 执行前需要复用/重放判断时，调度到 `execution_lineage.verify_node_inputs` 或 `execution_lineage.plan_replay_from_checkpoint`。
- 执行前发现节点声明了 `input_spec`、`required_inputs` 或 `gate_condition` 时，可先调度到 `node_audit.validate_node_contract`。
- 需要在同一 workflow 从中间状态继续时，调度到 `graph_runner.resume_from_checkpoint`。
- 需要保留原图并创建新分支时，调度到 `graph_saver.fork_from_checkpoint`。
- LLM 节点失败时，调度到 `model_routing.route_node` 选择复杂模型。
- 节点职责过大或失败仍无法恢复时，调度到 `task_decompose.decompose_node`。
- 数据质量相关节点失败时，调度到 `data_audit.audit_dataset`。
- 用户需要 SFT/RL 数据、执行复盘数据或 Hermes 风格轨迹时，调度到 `export_trace_dataset`。
- 多次运行后需要压缩结构时，调度到 `graph_optimizer.analyze_graph_runs`，再进入 `evaluation.compare_graph_versions`。
- 用户询问执行过程或错误原因时，先调用 `timeline`、`show_node_run` 或 `list_run_errors`，再决定是否恢复。
- 图中出现同一 DAG layer 的多个并行节点时，先调用 `multi_agent.plan_parallel_node_agents`，用 `multi_agent.tools._agent_tool` 为每个节点规划 `node-runner` 子 agent；如果用户只要求运行整图，仍可直接用 `graph_runner.run_graph`，runner 会按 layer 并行执行。
- 用户需要预览最终报告或引用列表时，调度到 `research.render_report` 或 `research.render_citations`。

## 失败处理

- 首次 LLM/路由失败，调度到 `model_routing.route_node` 并用复杂任务配置重试。
- 重试仍失败，调度到 `task_decompose.decompose_node` 生成子图。
- 每次失败都应写入 `data_manager.write_memory`，并建议 `graph_saver.save_workflow` 固化恢复过程。
