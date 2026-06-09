# node_audit Skill

## 职责

负责节点必要性、依赖合理性、contract/gate 和删除风险审计。图创建、保存、拆解和结构修改后应自动运行。

## 推荐命令

- `audit_node_necessity`：审计单个节点是否必要、是否可合并或删除。
- `validate_node_contract`：校验节点 `input_spec`、`interface.inputs`、`required_inputs`、`gate.status`、`gate_condition` 和输出绑定；明确 blocked/closed gate 或缺失 required input 时应阻止执行。

## 推荐下一模块

- 发现节点职责过宽时，调度到 `task_decompose.decompose_node`。
- 发现图结构变化后，调度到 `graph_saver.save_workflow`。
- contract/gate 校验通过且需要执行验证时，调度到 `graph_runner.run_node`。

## 失败处理

- 找不到节点时，调度到 `data_manager.snapshot`。
- gate 被关闭时，写入 `data_manager.write_memory` 并等待用户或上游验证打开 gate。
- required input 缺失时，先调度到 `data_manager.import_file` 或修改节点 `inputs`，再重新调用 `validate_node_contract`。
