# Module Memory: R1N1 — Fabricated Data: Patient Enrollment

## Necessity
Patient enrollment data is the foundation of the study design; classification as fabricated/valid determines downstream analysis.
- **Counterfactual**: Without classification, contamination analysis cannot distinguish trustworthy from untrustworthy study design. **Verdict: indispensable**

## Planned I/O
- **Input**: RCT1_full.md Materials and methods:Patients section
- **Output**: `{"id": "R1N1", "type": "fabricated_data", "text": "...", "evidence_pointer": [...]}`

## Actual I/O
- **Actual Input**: "Twenty-eight consecutive patients from our surgical ICU suffering from sepsis... and 28 consecutive trauma patients (ISS >15)... randomized into four groups: either 10% HES... or 20% HA... (n=14 each)"
- **Actual Output**: R1N1 — classified as fabricated_data. Exactly 14 patients per group across 4 groups is suspiciously uniform; Boldt retraction involved systematic fabrication across multiple studies.

## Verification
- **Rule**: Classification must have evidence pointer and justification
- **Result**: PASS — evidence_pointer to RCT1_full.md:Materials and methods:Patients

## Evidence Pointers
- `e:/graphyagent/retracted_research/sample/retracted_graph.json` (R1N1)

## Gate Status
- **Condition**: Classification justified with evidence
- **Status**: **OPEN**
