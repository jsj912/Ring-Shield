# Moved out of the 8 pages (Checkpoint B cut list, applied 2026-11-18/19)

Pre-cut sources are kept unchanged in paper/_pre_checkpointB_cuts_2026-11-18/.

Moved out of the main text; the files stay in paper/ and go to the released repository:
- **Rank 1–2:** the whole appendix (`sections/appendix.tex`, commented out in main.tex). That covers typing, held-out cycle, per-pattern, tenant, robustness, windows, val–test gap, scope_sensitivity, component_scope and the platform.
- **Rank 4–5:** tables `significance`, `precision_paired` (the figure r9_quiet_vs_precision is kept) and every per-seed table. `ring_methods` is kept as the one summary table.
- **Rank 6:** table `hm_closeout` and its old-detector prose. They are replaced by `tables/hm_transfer.tex` (3 rows) and one transfer subsection; the old-detector partition gain (+0.015) is kept in one sentence.
- **Rank 7:** table `hm_audit`. One summary sentence is kept.
- **Rank 8:** table `tail`. The figure is kept, and the global-quantile subsection was already one paragraph.
- **Rank 9:** table `related_comparison`. Related work was compressed to about 340 words.
- **Rank 10:** table `window_budget` and the "untouched count" paragraph, including the dropped "6.4 of the 9.2" clause. The budget paragraph is cut to three sentences.
- **Rank 12:** evaluation-window and statistics detail, now in docs/PROTOCOL.md. The definitions are kept.
- **Rank 13:** the platform and explanation-layer paragraph in method.tex.

Rank 11 ("What did not help") is **not** shortened: author item 2 asked for one line for each of the nine attempts.
