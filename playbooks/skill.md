# playbooks Skill

## 职责

负责可复用子图 motif 的序列化和匹配。playbook 必须来自重复成功结构、显式用户提供结构或 optimizer 证据，不能把演示样例当作默认智能体知识。

## 推荐命令

- `serialize_subgraph`：把当前图的一组节点序列化为 playbook。
- `match_playbooks`：按任务或 graph 节点关键词匹配已有 playbook。

## 推荐下一模块

- 候选子图通常来自 `graph_optimizer.mine_reusable_subgraphs`。
- 匹配到 playbook 后调度到 `task_decompose.decompose_task_to_graph` 或 `graph_saver.merge_workflow`。
- 使用前调度到 `evaluation.compare_graph_versions`。

## 失败处理

- 没有 playbook 时返回空列表，不使用内置示例补位。
