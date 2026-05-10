# Module Memory: C1N15 — Intermediate Claim: All Colloids Impair Beyond Dilution

## Necessity
Renamed from original C1N11 due to C1N10 split occupying IDs C1N11-C1N14.
- **Original ID**: C1N11
- **Rename reason**: C1N10 split into C1N11-C1N14, old C1N11 renumbered to C1N15

## Actual I/O
- **Actual Output**: C1N15 — intermediate_claim. "All colloids except albumin can induce specific decreases of vWF and FVIII:C. Hemodilution alone does not explain the observed changes; specific interactions with coagulation factors are involved."
- **depends_on**: C1N4 (deleted), C1N5 (clean)
- **uses_retracted_paper**: false

## Verification
- **Rule**: Must have clean support path after pruning
- **Result**: PASS — C1N5 (MW mechanism) is clean and present. Lost C1N4->C1N15 edge but C1N5 alone suffices.

## Evidence Pointers
- `e:/graphyagent/retracted_research/sample/verdict.json` (C1N15_all_colloids_impair_beyond_dilution)

## Gate Status
- **Condition**: Clean support path exists (via C1N5)
- **Status**: **OPEN** — still_supported (weakened — lost C1N4 edge)
