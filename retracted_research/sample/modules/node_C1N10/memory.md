# Module Memory: C1N10 — [SPLIT] Final Conclusion: Colloid Choice by Patient Risk

## Status: SPLIT into C1N11, C1N12, C1N13, C1N14

**This node was split because it mixed multiple independent claims that have different post-pruning verdicts.**

### Original text
"Rate of degradation is most important determinant. Rapidly degradable HES 200/0.5/6 and gelatin may be preferred in bleeding-risk patients. Same for von Willebrand disease. All artificial colloids may increase bleeding with very large volumes."

### Split mapping
| New Node | Single Claim | Verdict |
|----------|-------------|---------|
| C1N11 | Rate of degradation is the key determinant | still_supported |
| C1N12 | HES 200/0.5/6 may be preferred in bleeding-risk patients | **unsupported_after_pruning** |
| C1N13 | Gelatin may be preferred in bleeding-risk patients | still_supported |
| C1N14 | vWb disease + large volume caveat | indeterminate_need_human_review |

### Evidence Pointers
- `e:/graphyagent/retracted_research/sample/verdict.json` (split_nodes, conclusion_assessment C1N11-C1N14)
