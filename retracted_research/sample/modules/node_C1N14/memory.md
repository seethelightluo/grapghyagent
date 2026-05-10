# Module Memory: C1N14 — Final Conclusion: vWb Disease + Large Volume Caveat

## Necessity
Single-claim final conclusion extracted from split of original C1N10. Contains two sub-claims with different contamination status.
- **Source**: C1N10 sentences 3-4, split into standalone claim

## Actual I/O
- **Actual Output**: C1N14 — final_conclusion. "The same colloid preferences apply to patients with von Willebrand disease. All artificial colloids could potentially induce increased bleeding tendency after infusion of very large volumes."
- **depends_on**: C1N9 (clean), C1N15 (clean, renamed from old C1N11)
- **uses_retracted_paper**: false

## Verification
- **Rule**: Must have clean support path after pruning
- **Result**: PARTIAL — large volume caveat supported by C1N15 (clean). vWb disease preference inherits mixed status from C1N12 (unsupported) and C1N13 (still_supported).

## Evidence Pointers
- `e:/graphyagent/retracted_research/sample/verdict.json` (C1N14_vWb_and_large_volume)

## Gate Status
- **Condition**: Mixed — one sub-claim supported, one indeterminate
- **Status**: **REVIEW NEEDED** — indeterminate_need_human_review
