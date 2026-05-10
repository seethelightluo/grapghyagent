# Verifiable Task Graph Plan

## Task
分析撤稿论文 Boldt et al. 1996 (R1) 及其引用论文 de Jonge & Levi 2001 (C1) 的污染传播关系。

## 命名规范
- 撤稿论文节点：`R1N1`, `R1N2`, ... (Retracted Paper 1, Node N)
- 引用论文节点：`C1N1`, `C1N2`, ... (Citing Paper 1, Node N)
- 撤稿论文边：`R1E1-2` (Edge from R1N1 to R1N2)
- 引用论文边：`C1E1-2` (Edge from C1N1 to C1N2)

## Retracted Paper (R1)
- **Title**: Influence of different volume therapies on platelet function in the critically ill
- **Authors**: J. Boldt, M. Müller, M. Heesen, O. Heyn, G. Hempelmann
- **Year**: 1996, Journal: Intensive Care Medicine 22(11):1083-1088
- **DOI**: 10.1007/bf01699231
- **Retraction**: Data fabrication by Joachim Boldt

## Citing Paper (C1)
- **Title**: Effects of different plasma substitutes on blood coagulation: A comparative review
- **Authors**: Evert de Jonge, Marcel Levi
- **Year**: 2001, Journal: Critical Care Medicine 29(6):1261-1267
- **DOI**: 10.1097/00003246-200106000-00038
- **Retraction status**: NOT retracted

## Boldt 1996 在 C1 中的引用上下文

引用位置 1（HES 节，讨论血小板功能）:
> "Boldt et al. [61] and Rackow et al. [119] did not find significant differences in platelet function between HES and albumin in patients after cardiac surgery and in patients with sepsis, respectively."

引用位置 2（结论段，临床建议）:
> "In patients with increased risk of bleeding, rapidly degradable HES 200/0.5/6 and gelatin-based plasma expanders may be preferred over slowly degradable HES or dextran."

---

## Mermaid Flowchart

```mermaid
graph TD
    subgraph R1["R1: Boldt 1996 — Retracted Paper"]
        R1N1["R1N1 fabricated_data<br/>patient enrollment 56pts"]
        R1N2["R1N2 fabricated_data<br/>ADP aggregometry no diff"]
        R1N3["R1N3 fabricated_data<br/>collagen aggregometry"]
        R1N4["R1N4 fabricated_data<br/>epinephrine aggregometry"]
        R1N5["R1N5 fabricated_data<br/>volume & coagulation data"]
        R1N6["R1N6 valid_data<br/>platelet pathophysiology"]
        R1N7["R1N7 valid_data<br/>HES formulation literature"]
        R1N8["R1N8 valid_reasoning<br/>aggregometry methodology"]
        R1N9["R1N9 wrong_reasoning<br/>stats on fabricated data"]
        R1N10["R1N10 wrong_reasoning<br/>clinical safety inference"]
        R1N11["R1N11 valid_reasoning<br/>HES formulation comparison"]
        R1N12["R1N12 wrong_conclusion<br/>HES safe without risk"]

        R1N1 --> R1N2
        R1N1 --> R1N3
        R1N1 --> R1N4
        R1N2 --> R1N9
        R1N3 --> R1N9
        R1N4 --> R1N9
        R1N9 --> R1N12
        R1N10 --> R1N12
        R1N5 --> R1N10
        R1N6 --> R1N8
        R1N7 --> R1N11
    end

    subgraph C1["C1: de Jonge & Levi 2001 — Citing Paper"]
        C1N1["C1N1 data<br/>dextran anticoagulant"]
        C1N2["C1N2 data<br/>HES MW-dependent effects"]
        C1N3["C1N3 data<br/>gelatin least adverse"]
        C1N4["C1N4 reasoning<br/>HES platelet safety synthesis"]
        C1N5["C1N5 reasoning<br/>MW/substitution mechanism"]
        C1N6["C1N6 reasoning<br/>gelatin vs HES comparison"]
        C1N7["C1N7 ic<br/>HES 200/0.5/6 & gelatin safe"]
        C1N8["C1N8 citation_anchor<br/>Boldt 1996 + Rackow 1982"]
        C1N9["C1N9 ic<br/>dextran & slowly-degradable HES worst"]
        C1N10["C1N10 fc<br/>colloid choice by patient risk"]
        C1N11["C1N11 ic<br/>all colloids impair beyond dilution"]

        C1N1 --> C1N4
        C1N2 --> C1N4
        C1N2 --> C1N5
        C1N3 --> C1N6
        C1N4 --> C1N7
        C1N8 --> C1N7
        C1N5 --> C1N9
        C1N6 --> C1N7
        C1N7 --> C1N10
        C1N9 --> C1N10
        C1N4 --> C1N11
        C1N5 --> C1N11
        C1N8 --> C1N11
    end

    R1N2 -.->|contaminates| C1N8
```
