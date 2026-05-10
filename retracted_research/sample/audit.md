# GraphyAgent Audit Report — Retracted Research Contamination Analysis

## Run Metadata
- **Date**: 2026-05-11
- **System**: GraphyAgent Retracted Research Analysis
- **Naming Convention**: R1N#/C1N# for nodes, R1E#-#/C1E#-# for edges
- **Retracted Paper (R1)**: Boldt et al. 1996, Intensive Care Medicine 22(11):1083-1088, DOI: 10.1007/bf01699231, retracted for data fabrication
- **Citing Paper (C1)**: de Jonge & Levi 2001, Critical Care Medicine 29(6):1261-1267, DOI: 10.1097/00003246-200106000-00038, NOT retracted
- **Input**: R1 full text in RCT1_full.md, C1 full text in dejonge2001.pdf

---

## 1. Subgraph A: Retraction Graph Builder (R1)

### A1. Extract Factual Units
- **Input**: RCT1_full.md (Boldt 1996 full text)
- **Output**: 12 candidate units extracted
- **Verification**: Each unit has text span and location pointer to RCT1_full.md
- **Gate**: **PASS**

### A2. Separate Data Nodes
- **Output**: 5 fabricated_data (R1N1-R1N5), 2 valid_data (R1N6-R1N7)
- **Classification basis**: R1N1-R1N5 contain the core study findings (patient data, aggregometry results, volume data) that are the targets of the retraction notice. R1N6-R1N7 are literature-derived background knowledge verifiable from cited references.
- **Gate**: **PASS**

### A3. Separate Reasoning Nodes
- **Output**: 2 wrong_reasoning (R1N9, R1N10), 2 valid_reasoning (R1N8, R1N11)
- **Classification basis**: R1N9 (ANOVA on fabricated data) and R1N10 (clinical safety inference from small fabricated study) depend on fabricated inputs. R1N8 (aggregometry methodology, ref 13) and R1N11 (HES formulation literature, refs 20-24) are independently verifiable.
- **Gate**: **PASS**

### A4. Extract Wrong Conclusion
- **Output**: 1 wrong_conclusion (R1N12) containing both abstract and discussion conclusions
- **Traceability**: R1N12 <- R1N9 <- R1N2,R1N3,R1N4 (all fabricated aggregometry data)
- **Gate**: **PASS**

### A5. Build Retracted DAG
- **Output**: 12 nodes, 11 edges
- **Edge types**: "supports" (data->reasoning) and "derives" (reasoning->conclusion)
- **Cycle check**: No cycles detected
- **Gate**: **PASS**

### A6. Audit Retracted DAG
- **Structural checks**:
  - Graph non-empty: 12 nodes — PASS
  - All node types from valid set: fabricated_data, valid_data, wrong_reasoning, valid_reasoning, wrong_conclusion — PASS
  - Every wrong_conclusion traces to fabricated_data or wrong_reasoning: R1N12<-R1N9<-R1N2 — PASS
- **Gate**: **PASS**

---

## 2. Subgraph B: Citing Paper DAG Builder (C1)

### B1. Select Target Conclusion
- **Target**: "In patients with increased risk of bleeding, rapidly degradable HES 200/0.5/6 and gelatin-based plasma expanders may be preferred over slowly degradable HES or dextran"
- **Source**: de Jonge 2001, page 5, Conclusions final paragraph
- **Specificity**: Specific, testable clinical recommendation — not whole-paper topic
- **Gate**: **PASS**

### B2. Extract Support Path Candidates
- **Output**: 11 nodes from full-text analysis
- **Boldt 1996 citation found at**: page 3, HES section "Effects on Platelet Function" — "Boldt et al. [61] and Rackow et al. [119] did not find significant differences in platelet function between HES and albumin"
- **Second citation context**: page 5, Conclusions — clinical recommendation for HES 200/0.5/6 in bleeding-risk patients
- **Gate**: **PASS**

### B3. Classify Nodes
- **Output**: 3 data (C1N1-C1N3), 1 citation_anchor (C1N8), 3 reasoning (C1N4-C1N6), 3 intermediate_claim (C1N7, C1N9, C1N11), 1 final_conclusion (C1N10)
- **Gate**: **PASS**

### B4. Build Dependency Edges
- **Output**: 16 edges forming DAG
- **Cycle check**: No cycles
- **C1N10 (final_conclusion) incoming edges**: C1E7-10, C1E9-10 — PASS
- **Gate**: **PASS**

### B5. Mark Citation Usage
- **C1N8**: `uses_retracted_paper: true` — explicitly cites Boldt 1996 [61]
- **C1N4**: `uses_retracted_paper: true` — reasoning synthesis incorporates C1N8's Boldt finding
- **C1N7**: `uses_retracted_paper: true` — intermediate claim derives from C1N4 and C1N8
- **Gate**: **PASS**

### B6. Audit Citing DAG
- **C1N10 traceable to data/reasoning**: via C1N7<-C1N4<-C1N1,C1N2,C1N8 and C1N9<-C1N5<-C1N1,C1N2 — PASS
- **C1N8 dependency chain**: C1N8 is leaf node (citation_anchor), feeds into C1N4 and C1N7 — PASS
- **Target-conclusion-centered**: DAG focuses on support paths to C1N10, not loose summary — PASS
- **Gate**: **PASS**

---

## 3. Subgraph C: Contamination Pruner & Verdict

### C1. Match Retracted Elements
- **Output**: 6 alignments (AL1-AL6)
- **Alignment types**: 3 data_dependency, 2 reasoning_dependency, 1 conclusion_dependency
- **Gate**: **PASS**

### C2. Score Contamination Strength
- **Output**: 3 direct (AL1:0.95, AL2:0.85, AL4:0.90), 3 strong (AL3:0.80, AL5:0.75, AL6:0.75)
- **Evidence quality**: Direct alignments have verbatim text match between C1 and R1. Strong alignments have clear causal chain.
- **Gate**: **PASS**

### C3. Mark Untrusted Nodes and Edges
- **Deleted**: C1N8 (Rule 1: direct on fabricated_data), C1N4 (Rule 2: strong on wrong_reasoning via deleted upstream), C1N7 (Rule 3: conclusion on wrong_conclusion)
- **Edges removed**: 8 edges
- **Gate**: **PASS**

### C4. Prune Citing DAG
- **Remaining**: 8 nodes, 8 edges (from original 11 nodes, 16 edges)
- **Pruned graph validity**: DAG acyclic — PASS
- **Removed items documented**: 3 nodes with reasons, 8 edges with reasons — PASS
- **Gate**: **PASS**

### C5. Recheck Conclusion Support
- **HES 200/0.5/6 preferred in bleeding risk**: `unsupported_after_pruning` — lost C1N8->C1N4->C1N7->C1N10 path
- **Gelatin preferred in bleeding risk**: `still_supported` — via C1N3->C1N6->C1N9->C1N10
- **Dextran/slowly-degradable HES worst**: `still_supported` — via C1N1/C1N2->C1N5->C1N9->C1N10
- **All colloids impair beyond dilution**: `still_supported` — via C1N5->C1N11
- **Gate**: **PASS**

### C6. Final Audit
- **Verdict**: `indeterminate_need_human_review` — PASS (three-class label)
- **Confidence**: 0.75
- **Removed nodes/edges**: documented — PASS
- **Remaining/lost paths**: documented — PASS
- **Human review reasons**: 5 specific reasons — PASS
- **Gate**: **PASS**

---

## 4. Cross-Subgraph Data Integrity

| Flow | Source | Target | Status |
|------|--------|--------|--------|
| R1 DAG -> C1 | retracted_graph.json | alignment_report.json C1 input | VERIFIED |
| C1 DAG -> C1 | citing_graph.json | alignment_report.json C1 input | VERIFIED |
| Alignments -> Scores | alignment_report.json | verdict.json scoring | VERIFIED |
| Scores -> Pruning | alignment_report.json strengths | pruned_graph.json rules | VERIFIED |
| Pruning -> Verdict | pruned_graph.json remaining paths | verdict.json assessments | VERIFIED |

---

## 5. Node-Level Memory Summary

### R1 Nodes (Retracted Paper)

| Node | Type | Status | Key Judgment |
|------|------|--------|-------------|
| R1N1 | fabricated_data | FABRICATED | Patient enrollment (exactly 14/group) |
| R1N2 | fabricated_data | FABRICATED | ADP aggregometry — primary fabrication target |
| R1N3 | fabricated_data | FABRICATED | Collagen aggregometry — corroborating fabrication |
| R1N4 | fabricated_data | FABRICATED | Epinephrine aggregometry — corroborating fabrication |
| R1N5 | fabricated_data | FABRICATED | Volume/coagulation supporting data |
| R1N6 | valid_data | VALID | Platelet pathophysiology (established knowledge) |
| R1N7 | valid_data | VALID | HES formulation literature (independently verifiable) |
| R1N8 | valid_reasoning | VALID | Aggregometry methodology (standard technique) |
| R1N9 | wrong_reasoning | WRONG | Statistics on fabricated data |
| R1N10 | wrong_reasoning | WRONG | Clinical safety inference from fabricated study |
| R1N11 | valid_reasoning | VALID | HES formulation comparison (literature-based) |
| R1N12 | wrong_conclusion | WRONG | "HES safe without risk" — primary false output |

### C1 Nodes (Citing Paper)

| Node | Type | Uses R1 | Post-Pruning |
|------|------|---------|-------------|
| C1N1 | data | No | RETAINED |
| C1N2 | data | No | RETAINED |
| C1N3 | data | No | RETAINED |
| C1N4 | reasoning | Yes | DELETED |
| C1N5 | reasoning | No | RETAINED |
| C1N6 | reasoning | No | RETAINED |
| C1N7 | intermediate_claim | Yes | DELETED |
| C1N8 | citation_anchor | Yes | DELETED |
| C1N9 | intermediate_claim | No | RETAINED |
| C1N11 | final_conclusion | No | still_supported (rate of degradation key) |
| C1N12 | final_conclusion | No | **unsupported_after_pruning** (HES 200/0.5/6 preferred) |
| C1N13 | final_conclusion | No | still_supported (gelatin preferred) |
| C1N14 | final_conclusion | No | indeterminate_need_human_review (vWb + large volume) |
| C1N15 | intermediate_claim | No | still_supported (all colloids impair, weakened) |

注：原 C1N10 拆分为 C1N11-C1N14。原 C1N11 重编号为 C1N15。

---

## 6. Key Finding

**Boldt 1996 的污染通过 C1N8（citation_anchor）进入 C1 的证据图，经过 C1N4（reasoning synthesis）传播到 C1N7（intermediate claim），最终影响拆分后的 C1N12（final conclusion: HES 200/0.5/6 preferred）。**

污染路径: `R1N2 -> C1N8 -> C1N4 -> C1N7 -> C1N12`

原 C1N10 已拆分为 4 个独立 final conclusion 节点（C1N11-C1N14），原 C1N11 重编号为 C1N15。逐条判定：

- **C1N11** (降解速率是决定因素): still_supported — C1N5, C1N9 干净
- **C1N12** (HES 200/0.5/6 可能优先): **unsupported_after_pruning** — C1N7 已删除（受 Boldt 污染），C1N9 无法独立支撑 HES 安全
- **C1N13** (gelatin 可能优先): still_supported — C1N6, C1N9 干净
- **C1N14** (vWb 病 + 大容量出血): indeterminate — vWb 部分继承 C1N12/C1N13 混合状态，大容量部分有 C1N15 支撑
- **C1N15** (所有胶体超越稀释效应): still_supported — C1N5 干净

---

## 7. File Manifest

```
retracted_research/sample/
├── RCT1_full.md                    # R1 全文
├── dejonge2001.pdf                 # C1 全文
├── smallplan.md                    # 实施计划
├── review/graph_plan.md           # 命名规范 + Mermaid DAG
├── retracted_graph.json           # R1 DAG: 12 nodes, 11 edges
├── citing_graph.json              # C1 DAG: 14 nodes, 22 edges (C1N10 split into C1N11-14, old C1N11->C1N15)
├── alignment_report.json          # 6 contamination alignments
├── pruned_graph.json              # Pruned C1: 11 nodes, 13 edges (post-split)
├── verdict.json                   # indeterminate_need_human_review
├── audit.md                       # This file
├── result.txt                     # Full audit trail
└── modules/
    ├── node_R1N{1-12}/memory.md   # R1 node memories (12 files)
    └── node_C1N{1-15}/memory.md   # C1 node memories (15 files, C1N10 split + C1N11->C1N15 rename)
```
