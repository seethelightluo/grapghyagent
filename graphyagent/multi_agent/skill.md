# multi_agent Skill

## 职责

负责把可并行的 graph/node 工作拆成子 agent 任务描述。GraphyAgent 的真实执行仍通过 command queue 和 `graph_runner` 完成；本模块提供 `multi_agent.tools._agent_tool` 兼容能力，用于为并行节点创建 `node-runner` 子 agent 计划。

## 推荐命令

- `plan_parallel_node_agents`：分析当前图的 DAG layer，找出可并行节点并生成子 agent 任务。
- `create_agent_task`：创建单个子 agent 任务描述。

## 推荐下一模块

- 子 agent 任务对应的真实节点执行进入 `graph_runner.run_node`。
- 并行节点需要共享长期记忆时，先调用 `memory.get_memory_context`。
- 子 agent 完成后需要报告输出时，调度到 `research.render_report`。

## 失败处理

- 如果没有可并行 layer，返回空计划并建议直接运行 `graph_runner.run_graph`。
- 如果图有环或节点依赖不完整，调度到 `node_audit.validate_node_contract` 或 `task_decompose.decompose_task` 修复。
