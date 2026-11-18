# Page budget: acmart sigconf, 8 pages including references (proposal, 2026-11-16)

Nothing has been deleted. This is a proposal. The page count must be measured on Overleaf, because this
machine has no LaTeX toolchain. The estimates below are rough.

## Where the draft stands
- **Main body:** about 8,600 words. Section by section:
  - abstract 240, introduction 590, related work 610
  - protocol (data.tex) 1,100, audit (findings.tex) 1,500, method 570
  - results 2,860, recommendations 290, limitations 590, conclusion 280
- **Main-body floats:** 9 tables and 6 figures.
- **Appendix:** 980 words, 8 tables and 4 figures.
- **References:** 24 entries, about 0.6 page.
- **Budget:** a sigconf page holds about 1,000 to 1,100 words of plain two-column text. Eight pages, less about 0.6 page of references and about 2 pages of floats, leave room for roughly **5,500 to 6,000 words of body text**.
- **Gap:** the main body must lose about **2,600 to 3,100 words** and about 6 floats. Reviewers are not required to read an appendix, and the target is no supplementary material, so the appendix goes to the released repository in full.

## Proposed cuts and moves (in order of size)
| # | What | Saves (approx.) | Where it goes |
|---|---|---|---|
| 1 | Whole appendix (corrections, scope tables, val–test gap, robustness, windows, typing, held-out cycle, per-pattern, platform, tenant, dashboard figures) | 980 words, 8 tables, 4 figures | Released repository, as `docs/paper_appendix.pdf` built from the same sources. Main-text references become "see the released repository". |
| 2 | Results §6: the HI-Medium close-out (table hm_closeout and its prose). Keep one sentence with the +0.015 [+0.010, +0.020] result. | ~350 words, 1 table | Repository |
| 3 | Results §6: the significance table. Its numbers are already quoted in the text. | 1 table | Repository |
| 4 | Results §6: the precision-paired table. Keep figure r9_quiet_vs_precision, or the table, but not both. | 1 table or 1 figure | Repository |
| 5 | Audit §4: the HI-Medium audit table (hm_audit). Keep one sentence. | ~200 words, 1 table | Repository |
| 6 | Audit §4: shorten the "global quantile hands the seed budget to one day" subsection to one paragraph, and keep the tail table *or* the tail figure. | ~400 words, 1 float | Repository |
| 7 | Related work: move the related-comparison table to the repository and compress the prose to about 350 words. | ~250 words, 1 table | Repository |
| 8 | Results §7 (where recovery stops): keep the decomposition figure, and move the window-budget table and the "untouched count" paragraph. | ~300 words, 1 table | Repository |
| 9 | Results "What did not help": compress to a 4-row table or a single paragraph. | ~250 words | Stays in the paper, shortened |
| 10 | Protocol §3: move the evaluation-window details and the statistics paragraph to the repository's PROTOCOL.md, and keep the definitions. | ~400 words | docs/PROTOCOL.md (already released) |
| 11 | Method §5: move the platform paragraph and the pipeline figure's long caption. | ~150 words | Repository |
| 12 | Limitations and recommendations: merge them into one section. | ~250 words | Stays, merged |

Items 1–12 together save about 3,000 words and 7 to 9 floats. If the measured count is still over,
trim items 9 and 12 further.

## Layout fixes needed for sigconf (not content cuts)
- Five figures use `width=0.55`–`0.9\textwidth` inside `figure`. In two columns this overflows a column. They should become `\columnwidth`, or `figure*` for the decomposition figure.
- Wide tables (for example detector_swap, with six columns) may need `table*`, or `\small` with `\columnwidth`.
- `\ci{}{}{}` cells widen tables. Consider moving the intervals to a separate row.
