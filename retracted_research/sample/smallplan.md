# GraphyAgent 最小案例实现计划（smallplan）

## 目标

实现一个 **GraphyAgent-only** 的最小闭环案例：

**输入**
- 一篇被撤稿论文（retracted paper）
- 一篇引用该撤稿论文的论文（citing paper）

**输出**
- `retracted_graph.json`
- `citing_graph.json`
- `alignment_report.json`
- `pruned_graph.json`
- `verdict.json`
- `audit.md`

核心目标不是做大规模文献网络，而是验证以下命题：

1. 能否把撤稿论文拆成“造假数据 / 未造假数据 / 错误推理 / 正确推理 / 错误结论”的结构化 DAG。
2. 能否把引用论文拆成“data → reasoning → intermediate claim → final conclusion”的局部支撑 DAG。
3. 能否把 citing paper DAG 与 retracted paper DAG 做节点级污染比对。
4. 能否删除被污染的节点与边后，重新判断 citing paper 的目标结论是否仍成立。
5. 能否把上述过程沉淀成 GraphyAgent 的节点契约、审计日志与节点级 memory。

---

## 为什么这是最小案例

这个案例只处理 **1 对论文**，不处理：
- 批量 citation 扩展
- 图数据库
- 并行 worker
- checkpoint 恢复
- 多 hop 传播

这样可以把验证重点放在 GraphyAgent 的核心能力上：
- graph decomposition
- node-level memory
- necessity audit
- verification rule
- pruning + re-judgment

---

## 系统范围

### In scope
- 单 pair 输入
- 手动提供论文全文、摘要或结构化摘录
- 结论导向的局部 DAG 分解
- 节点级污染对齐
- 节点/边删除与结论重判
- 审计日志与压缩判断句

### Out of scope
- 自动联网抓全文
- 大规模文献图谱
- 可恢复任务队列
- 并行调度
- UI
- benchmark 批量评测

---

## 总体结构

最小系统由 3 个 GraphyAgent 子图组成：

1. **Retraction Graph Builder**
2. **Citing Paper DAG Builder**
3. **Contamination Pruner & Verdict**

```text
input pair
  ├── retracted paper text
  └── citing paper text

        ↓
[Subgraph A] Retraction Graph Builder
        ↓
  retracted_graph.json

        ↓
[Subgraph B] Citing Paper DAG Builder
        ↓
   citing_graph.json

        ↓
[Subgraph C] Contamination Pruner & Verdict
        ↓
alignment_report.json
pruned_graph.json
verdict.json
audit.md
```

---

## Subgraph A：Retraction Graph Builder

### 任务
把撤稿论文拆成一个“污染源图”。

### 输出节点类型
- `fabricated_data`
- `valid_data`
- `wrong_reasoning`
- `valid_reasoning`
- `wrong_conclusion`

### 推荐节点

#### A1. Extract factual units
- 输入：撤稿论文全文 / 结构化摘录
- 输出：候选 data / claim / reasoning span 列表
- 验证：每个单元必须带文本片段与位置说明

#### A2. Separate data nodes
- 输入：候选 factual units
- 输出：`fabricated_data_nodes` 与 `valid_data_nodes`
- 验证：每个 data node 必须有 evidence span 与分类理由

#### A3. Separate reasoning nodes
- 输入：候选 reasoning / claim 单元
- 输出：`wrong_reasoning_nodes` 与 `valid_reasoning_nodes`
- 验证：错误推理必须说明错误原因，正确推理不能依赖 fabricated data 或 earlier wrong reasoning

#### A4. Extract wrong conclusion
- 输入：论文结论段 + retraction notice / 标注
- 输出：`wrong_conclusion_nodes`
- 验证：结论节点必须明确由哪些 reasoning/data 支撑

#### A5. Build retracted DAG
- 输入：上述节点
- 输出：边集合 `edges`
- 验证：边必须表示“supports / derives / depends_on”之一

#### A6. Audit retracted DAG
- 输入：完整 DAG
- 输出：审计结果
- 验证：
  - 图非空
  - fabricated / valid / wrong / conclusion 节点类型合法
  - 每个 wrong conclusion 至少可回溯到一个 wrong_reasoning 或 fabricated_data

### 节点 memory 规则
每个节点保存：
- `input_spec`
- `output_spec`
- `verification_rule`
- `compressed_judgment`
- `evidence_pointer`
- `run_log`

---

## Subgraph B：Citing Paper DAG Builder

### 任务
把引用论文拆成一个 **与目标结论相关的局部支撑 DAG**，而不是整篇论文全图。

### 输出节点类型
- `data`
- `reasoning`
- `intermediate_claim`
- `final_conclusion`
- `citation_anchor`

### 推荐节点

#### B1. Select target conclusion
- 输入：引用论文全文 / 摘要
- 输出：需要重判的目标结论
- 验证：必须是具体结论，不是整篇论文主题

#### B2. Extract support path candidates
- 输入：目标结论 + 正文
- 输出：候选支撑片段
- 验证：每个片段与目标结论必须存在显式支撑关系

#### B3. Classify nodes
- 输入：候选支撑片段
- 输出：`data` / `reasoning` / `intermediate_claim` / `citation_anchor`
- 验证：每个节点类型唯一

#### B4. Build dependency edges
- 输入：节点集合
- 输出：局部 DAG 边集合
- 验证：DAG 无环；final conclusion 必须有入边

#### B5. Mark citation usage
- 输入：citation anchors + 论文引用上下文
- 输出：哪些节点显式使用了 retracted paper
- 验证：每个标记必须带上下文证据

#### B6. Audit citing DAG
- 输入：完整 citing DAG
- 输出：审计结果
- 验证：
  - final conclusion 可回溯到 data/reasoning
  - citation_anchor 与上游 reasoning/data 的依赖清晰
  - DAG 是局部支撑图，而非松散摘要

---

## Subgraph C：Contamination Pruner & Verdict

### 任务
对齐两个 DAG，识别污染，删除不可信节点与边，然后重判结论。

### 推荐节点

#### C1. Match retracted elements
- 输入：`retracted_graph.json` + `citing_graph.json`
- 输出：node-level alignment 列表
- 依赖类型：
  - `data_dependency`
  - `reasoning_dependency`
  - `conclusion_dependency`
- 验证：每条对齐必须带 citing node、retracted node、dependency type、evidence

#### C2. Score contamination strength
- 输入：alignment 列表
- 输出：污染强度
- 建议等级：
  - `direct`
  - `strong`
  - `weak`
  - `peripheral`
- 验证：高强度污染必须有直接文本证据

#### C3. Mark untrusted nodes and edges
- 输入：污染强度报告
- 输出：需删除 / 降权 / 保留的节点与边
- 默认规则：
  - 直接依赖 `fabricated_data` → 删除
  - 直接复用 `wrong_reasoning` → 删除
  - 仅背景提及错误结论 → 可保留但标记

#### C4. Prune citing DAG
- 输入：原 DAG + 删除规则
- 输出：`pruned_graph.json`
- 验证：删后图仍合法；记录 removed nodes / removed edges

#### C5. Recheck conclusion support
- 输入：`pruned_graph.json`
- 输出：重判结果
- 允许标签：
  - `still_supported`
  - `unsupported_after_pruning`
  - `indeterminate_need_human_review`
- 验证：必须显式列出删后是否仍存在从 data/reasoning 到 final conclusion 的支撑路径

#### C6. Final audit
- 输入：全部中间结果
- 输出：`audit.md` + `verdict.json`
- 验证：最终结论、删除路径、剩余支撑路径、置信度与人工复核建议必须齐全

---

## JSON Schema 建议

### retracted_graph.json

```json
{
  "paper_id": "retracted_001",
  "nodes": [
    {
      "id": "r_d1",
      "type": "fabricated_data",
      "text": "sample size = 420",
      "evidence_pointer": ["paper:results:para3"],
      "compressed_judgment": "fabricated_data_confirmed"
    }
  ],
  "edges": [
    {
      "from": "r_d1",
      "to": "r_r2",
      "relation": "supports"
    }
  ]
}
```

### citing_graph.json

```json
{
  "paper_id": "citing_001",
  "target_conclusion": "Drug A improves outcome B in subgroup C",
  "nodes": [
    {
      "id": "c_r3",
      "type": "reasoning",
      "text": "Because prior work established mechanism M...",
      "depends_on": ["c_d1", "c_a1"],
      "uses_retracted_paper": true,
      "evidence_pointer": ["paper:discussion:para2"]
    }
  ],
  "edges": []
}
```

### alignment_report.json

```json
{
  "alignments": [
    {
      "citing_node": "c_r3",
      "retracted_node": "r_r2",
      "dependency_type": "reasoning_dependency",
      "strength": "direct",
      "confidence": 0.87,
      "evidence_pointer": ["paper:discussion:para2"]
    }
  ]
}
```

### verdict.json

```json
{
  "final_verdict": "unsupported_after_pruning",
  "removed_nodes": ["c_r3"],
  "removed_edges": ["c_d1->c_r3", "c_r3->c_c1"],
  "remaining_support_paths": [],
  "confidence": 0.79,
  "human_review_needed": true
}
```

---

## 节点级验证规则

每个 GraphyAgent 节点统一具备：

- `input_spec`
- `output_spec`
- `verification_rule`
- `gate_condition`
- `necessity_audit`
- `compressed_judgment`
- `evidence_pointer`

### 最小 gate 规则

- 没有 `evidence_pointer` 不允许 pass
- 输出不是结构化 JSON 不允许 pass
- 节点类型不合法不允许 pass
- citing DAG 出现环不允许 pass
- pruning 后如果没记录 removed nodes / edges 不允许 pass
- verdict 不是三分类之一不允许 pass

---

## 最小实现顺序

### Phase 1：静态 schema
- 定义 5 个输出文件 schema
- 定义节点类型枚举
- 定义 gate 规则

### Phase 2：Subgraph A
- 先完成撤稿论文图生成
- 只支持手工输入文本
- 先不追求全文精确，只要求结构清楚

### Phase 3：Subgraph B
- 只做 target conclusion 的局部支撑 DAG
- 不解析全文所有细节

### Phase 4：Subgraph C
- 实现污染比对 → 删边删点 → 重判结论

### Phase 5：审计与 memory
- 为每个节点补充 compressed_judgment / evidence_pointer / run_log
- 输出 audit.md

---

## 成功标准

最小案例完成后，应满足：

1. 能成功生成 5 个结构化 JSON + 1 个审计文件。
2. 每个节点都有明确的验证与 gate。
3. 能显式指出 citing paper 的哪些节点被撤稿论文污染。
4. 能删除这些节点与边，并给出删后结论判断。
5. 能保留节点级 evidence 与 compressed judgment。

---

## 风险与边界

### 风险
- 模型可能把“被撤稿”误等同于“整篇全错”
- 模型可能把 citing paper 拆成摘要树，而不是支撑 DAG
- 删除污染节点后，结论判断容易被过度简化成 yes/no

### 应对
- 强制区分 fabricated / valid / wrong / conclusion
- 强制构造 target-conclusion-centered DAG
- verdict 保留 `indeterminate_need_human_review`

---

## 第一版不要做的事

- 不做 LangGraph 集成
- 不做并行 worker
- 不做 checkpoint 恢复
- 不做 Neo4j
- 不做全量 citation 扩展
- 不做自动全文抓取

先把 **GraphyAgent 的可信 DAG 分解、污染对齐、删边重判** 跑通。
