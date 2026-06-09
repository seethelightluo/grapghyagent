# graph_runner Skill

## 职责

负责执行 graph/node，产出 GraphRun、NodeRun、checkpoint、graphoutput 和运行轨迹。用户点击运行、CLI 自动执行或后台 worker 执行时进入 `graph_runner`。
节点 executor 可直接使用 `subgraph` 类型运行一个嵌套 GraphConfig，并把子图 graphoutput 汇总为父节点输出。
节点 executor 也支持 `http` 工具调用和只读 `sqlite` / `db_query` 查询，输出会作为普通 artifact 注册。
每个节点运行前会调用 `node_audit.validate_node_contract` 的同源校验逻辑；显式 blocked/closed gate 或缺失 required input 会让节点失败并进入恢复流程。
每个 LLM 节点执行前应优先使用 `node_memory.prepare_node_context` 生成 Node Memory Packet；旧 `memory.context.get_memory_context` 只作为兼容数据源进入 packet evidence，不应默认作为第二条无界 prompt 注入。
每个节点执行前还会调用 `task.store.check_gate_conditions` 的 DAG gate 检查；上游节点未成功、上游 artifact 缺失/为空，或上游声明 gate_condition 但 gate 未打开时，当前节点必须阻断，不能继续生成无关 LLM 输出。
每个节点执行前先调用 `execution_lineage.verify_node_inputs` 做 deterministic preflight，再调用 `node_memory.prepare_node_context` 构建 Node Memory Packet；节点完成后先写 lineage/postflight，再调用 `reflection.run_online_reflection` 写入 upstream/knowledge 使用标签；GraphRun 完成后调度 `knowledge_graph.refresh_from_run` 更新 Knowledge Graph。
从 checkpoint 续跑时默认使用 `strict_fingerprint`：只有图节点定义、输入 artifact、executor signature 和 packet policy 未变化的成功节点才标记为 reused；dirty 节点会重新执行。

`graph_runner` 负责 NodeRun 失败后的第一现场处理：保存失败状态、日志、输入 packet、artifact、lineage 和 checkpoint，然后生成 `failure_analysis`。`failure_analysis` 必须判断失败范围，不允许只把错误文本丢给下游模块。

推荐失败范围：

- `node_local`：节点自身 prompt、模型能力、局部参数、局部输入、单步工具调用失败。
- `evidence_level`：上游证据不足、数据来源不可信、schema/provenance 缺失。
- `environment_level`：Python/CUDA/GPU/依赖、文件权限、外部服务或运行环境问题。
- `graph_level` / `plan_level`：原 workflow 拆解、依赖边、执行策略或整体假设错误。

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

## 已实现的恢复 module-command

- `classify_node_failure`：读取 failed NodeRun、error、lineage/packet/artifact 摘要，输出 `node_local | graph_level | plan_level` 等失败归因。
- `pause_for_replan`：当 failure_scope 是 `graph_level` / `plan_level` 时，将 GraphRun 标记为 `paused_for_replan`，写入 replan event，并交给全局恢复编排。
- `mark_edges_blocked`：把 failed node 到下游的数据边标记为 `blocked` / `stale` / `superseded`，但保留失败节点 trace。

## 推荐下一模块

- 执行前可调度到 `graph_saver.save_workflow` 保存版本。
- 执行前需要上下文路由时，调度到 `knowledge_graph.build_view_for_node` 或 `node_memory.prepare_node_context`。
- 执行前需要复用/重放判断时，调度到 `execution_lineage.verify_node_inputs` 或 `execution_lineage.plan_replay_from_checkpoint`。
- 执行前发现节点声明了 `input_spec`、`required_inputs` 或 `gate_condition` 时，可先调度到 `node_audit.validate_node_contract`。
- 需要在同一 workflow 从中间状态继续时，调度到 `graph_runner.resume_from_checkpoint`。
- 需要保留原图并创建新分支时，调度到 `graph_saver.fork_from_checkpoint`。
- LLM 节点失败且 failure_scope 是 `node_local` 时，调度到 `model_routing.route_node` 选择复杂模型。
- 节点职责过大、复杂模型失败或 failure_scope 仍是 `node_local` 时，调度到 `task_decompose.decompose_node`。
- failure_scope 是 `graph_level` / `plan_level` 时，上报 `agent_runtime` 做图级恢复，不要在 runner 内部硬改整图。
- 数据质量相关节点失败时，调度到 `data_audit.audit_dataset`。
- 用户需要 SFT/RL 数据、执行复盘数据或 Hermes 风格轨迹时，调度到 `export_trace_dataset`。
- 多次运行后需要压缩结构时，调度到 `graph_optimizer.analyze_graph_runs`，再进入 `evaluation.compare_graph_versions`。
- 用户询问执行过程或错误原因时，先调用 `timeline`、`show_node_run` 或 `list_run_errors`，再决定是否恢复。
- 图中出现同一 DAG layer 的多个并行节点时，先调用 `multi_agent.plan_parallel_node_agents`，用 `multi_agent.tools._agent_tool` 为每个节点规划 `node-runner` 子 agent；如果用户只要求运行整图，仍可直接用 `graph_runner.run_graph`，runner 会按 layer 并行执行。
- 用户需要预览最终报告或引用列表时，调度到 `research.render_report` 或 `research.render_citations`。

## 失败处理

- NodeRun 失败后先写入失败 NodeRun、错误日志、输入 packet hash、output/log artifacts、lineage record 和 checkpoint。
- 随后生成 `failure_analysis`，至少包含 `failure_scope`、失败证据、影响下游节点、dirty/reusable 初判和推荐下一模块。
- 如果 `failure_scope=node_local`，优先调度 `model_routing.route_node` 使用更合适 profile 重试；复杂模型仍失败或节点职责过大时，调度 `task_decompose.decompose_node` 生成局部子图或 retry node。
- 如果 `failure_scope=evidence_level`，暂停受影响分支，调度 `data_audit.audit_dataset`、`knowledge_graph.build_view_for_node` 或 `node_memory.update_gap_state` 补证据，再从 checkpoint 续跑。
- 如果 `failure_scope=environment_level`，保存环境错误和参数，修复环境或降级执行策略；不应把环境错误误判为图结构错误。
- 如果 `failure_scope=graph_level` 或 `plan_level`，暂停整个 GraphRun，标记失败节点下游边为 `blocked/stale/superseded`，保留 checkpoint，并上报 `agent_runtime` 做图级 ReAct。全局恢复应通过 `graph_saver.fork_from_checkpoint`、`task_decompose.decompose_task_to_graph` / `decompose_node` 和 `graph_runner.resume_from_checkpoint` 完成。
- 每次失败和恢复都应写入 `data_manager.write_memory` 或 trace，并建议 `graph_saver.save_workflow` 固化恢复过程。
