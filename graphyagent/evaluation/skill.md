# evaluation Skill

## 职责

负责 graph version 的回归评估和 promotion 前比较。它检查结构、效率、上下文和学习相关指标，避免 optimizer 直接采用未评估的新版本。

## 推荐命令

- `compare_graph_versions`：比较 base/candidate graph 的结构指标。
- `graph_metrics`：计算单图指标。
- `load_task_set`：加载外部 benchmark task set。
- `render_evaluation_report`：把比较结果渲染为报告。

## 推荐下一模块

- candidate 来自 `graph_optimizer.materialize_new_graph_version`。
- 通过比较后进入 `graph_saver.save_workflow`。
- 未通过时回到 `graph_optimizer.suggest_structure_changes` 降低建议强度。

## 失败处理

- 缺少 benchmark 时仍可做结构回归比较，但不能声称任务质量提升。
