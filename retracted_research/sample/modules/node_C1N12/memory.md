# Module Memory: C1N12 — Final Conclusion: HES 200/0.5/6 Preferred (UNSUPPORTED)

## Necessity
Single-claim final conclusion extracted from split of original C1N10. This is the contaminated claim.
- **Source**: C1N10 sentence 2 HES portion, split into standalone claim

## Actual I/O
- **Actual Output**: C1N12 — final_conclusion. "In patients with increased risk of bleeding, rapidly degradable HES 200/0.5/6 may be preferred over slowly degradable HES or dextran."
- **depends_on**: C1N7 (deleted — contaminated), C1N9 (clean but insufficient)
- **uses_retracted_paper**: false

## Verification
- **Rule**: Must have clean support path after pruning
- **Result**: FAIL — C1N7 deleted (depends on C1N4/C1N8 which import Boldt 1996 fabricated data). C1N9 only says dextran/slowly-degradable worst, cannot independently support HES 200/0.5/6 safety.

## Evidence Pointers
- `e:/graphyagent/retracted_research/sample/verdict.json` (C1N12_HES_200_0.5_6_preferred)

## Gate Status
- **Condition**: No clean support path
- **Status**: **BLOCKED** — unsupported_after_pruning
