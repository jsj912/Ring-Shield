# T-P6 — related work verified (2026-11-14)

Gate: **PASS.** No paper read makes any of our four contribution claims; none of the
group-level papers states a scope rule for groups that cross the evaluation window; 1 of 17
characterised papers was only partly accessible (Chai et al. 2023, abstract page).

| Finding | Where verified | Positioning sentence it touches |
|---|---|---|
| Group-level evaluation on AMLworld exists (Rico 2026, Tian 2025, Wang & Cao 2026, Deprez 2025) with incompatible units, ground truths and metrics | full texts; see paper/RELATED_WORK_AUDIT.md rows 10–15 | **supports** "group-level evaluation exists but is not comparable" |
| No paper states how a group crossing a split/window boundary is scored | every full text read | **supports** the scope-rule contribution |
| No published quantification of the AMLworld tail; two practitioner repos note it informally; TAML code silently drops days > 10 | searches + TAML code | **supports** the tail finding as first published quantification; text says "not aware of", never "first" |
| Transaction- vs actor-level queues diverge on Elliptic++ (Malik, arXiv 2604.23494) | full text | **weakens slightly** the novelty of "edge and group metrics decouple" in general; ours is on AMLworld, ring level, under a detector swap. Cite it in pass 1. |
| GARG-AML studies pre-partition and limited-view sensitivity of **account** scores | arXiv 2506.04292 §5.3, App. D | does not touch the group-scope claim; cite fairly |
| MEGA-GenAgg published HI-Small F1 is 74.48 ± 0.84, not 74.88 ± 0.38 | arXiv 2412.00241v3 Table 16 | changes no bar (T-P7 gate is 0.70); docs/FUTURE_IMPLEMENTATIONS.md F4 should be corrected (author's call) |
| TAML's protocol: per-day snapshots, 2-hop label-1 ground truth, features aggregated over all ten days | TAML code | relevant to T-P9's design; a reviewer-checkable example of an unstated scope choice |
