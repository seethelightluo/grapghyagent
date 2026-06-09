# data_audit Skill

## 职责

负责数据质量、人工合成数据、后训练数据风险、任务适用性和证据链审计。文件是 CSV/JSON/JSONL 或用户提到“审计/合成/后训练数据/造假/操纵/是否适合训练”时进入 `data_audit`。

执行原则：检测器先行、证据入库、标签归一、策略 Gate 输出动作，LLM 只能消费 `llm_summary_input` 里的结构化事实做摘要。

## 推荐命令

- `audit_dataset`：运行本地 evidence-first 审计，输出 `audit_report`、`record_tags`、`evidence`、`quality_dimensions`、`risk_assessment`、`review_queue` 和 `llm_summary_input`。
- 元数据建议包含 `schema.fields`、`task_spec`、`target_distribution`、`provenance` 和 `validation_context`；其中 `validation_context.benchmark_texts/test_records/reference_records` 用于泄漏/污染检查，`task_spec.critical_slices` 用于关键切片覆盖检查。

## 推荐下一模块

- 审计报告产出后，调度到 `data_manager.write_memory` 记录节点或文件记忆。
- 审计结论需要自然语言摘要时，调度到 `model_routing.chat_completion` 使用复杂模型，并只传 `llm_summary_input`。
- 审计流程要持久化时，调度到 `graph_saver.save_workflow`。
- 审计发现关键 schema、来源或合成风险时，调度到 `node_audit.validate_node_contract` 或 `graph_runner.run_node` 前先阻塞下游节点。

## 失败处理

- 文件无法读取时，调度到 `data_manager.list_managed_files`。
- 元数据缺失时，调度到 `task_decompose.decompose_node` 生成元数据提取子任务。
- `risk_assessment.metadata_confidence.status=limited` 时，不要给出高置信放行结论，先收集 schema、task_spec、target_distribution 和 provenance。
