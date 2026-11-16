# T-P9 — TAML: code findings recorded ahead of the day-1 go/no-go (2026-11-14)

Recorded now on the author's instruction (round 3, decision 6). **Not acted on before T-P9 day 1**;
they are inputs to the day-1 go/no-go (runbook §T-P9: trains one epoch; our split feedable
without editing model code).

Source: TAML's released code (Rico et al. 2026), read during T-P6
(`dataset_scripts/build_ibm_graph_dataset.py`; see paper/RELATED_WORK_AUDIT.md row 20 and
results/notes/p6_related_work.md).

1. **Split and horizon.** The code keeps only transactions on days ≤ 10 of HI-Small and splits
   by day: train days 1–6, validation 7–8, test 9–10. Days after 10 (which contain the
   high-base-rate tail) are dropped without comment; the paper text does not state this.
   Our split and windows differ (test window = days 8–9 of our test split), so T-P9 must feed
   our split in, not reuse theirs.
2. **Ground truth.** Ground-truth sub-networks are built per single day (per-day snapshots), as
   the 2-hop neighbourhood of label-1 transactions. This is a different target from our
   laundering-attempt rings; a ring that spans days is cut into per-day pieces.
3. **Feature leak.** Node features are aggregated over all ten days, so a test-day snapshot sees
   features computed from its own and later days. Under our causal protocol this must be
   replaced by trailing (causal) aggregation, or the TAML numbers flagged as non-causal.

Day-1 questions these raise: can our split and causal features be fed through the data
scripts alone (no model edits)? If item 3 can only be fixed by editing model code → NO-GO per
the runbook.
