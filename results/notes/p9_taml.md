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

## 2026-11-17: TAML seed 28 on the seeded rebuild (addendum 2)

Every number in this section carries these labels:
- one seed;
- features aggregated over all ten days, including the test days, with normalisation fitted on steps 1–8;
- about 42 % of in-window ring transactions are absent from its graphs (247 of 585);
- ceiling of 63 of 97 matchable rings under the joined view;
- no paired test.

**Protocol differences from our pipeline**
1. Accounts are keyed by the account string alone; 8 strings occur at more than one bank.
2. Node features are aggregated over all ten days, test days included.
3. The builder drops transactions with an unseeded coin flip (remove_leakage). Here it was rebuilt with seed 20261117 so the graphs repeat.
4. It predicts nodes, not rings. Rings are formed by the conversion rule in addendum 2.

**Representability:** see results/tables/p9_taml_representability.json. 63 of 97 matchable rings (64.9 %) have at least 3 connected members in the joined view; 25 do on day 8 and 39 on day 9.

**Training:** early stopping at epoch 37 (training-loss plateau); 7,664 s.

**Threshold:** τ = 0.797, chosen on validation steps 7–8 (class-1 F1 0.743). Predicted accounts: 1,080 on step 9 and 679 on step 10.

**Rows** (primary window, days 8–9; Jaccard 0.5; test_visible scope; 1,000-draw intervals)

| Conversion | Predicted rings | Precision | Recall | Ring-F1 [95 % interval] | Member coverage | Recall on representable rings |
|---|---|---|---|---|---|---|
| Joined (primary) | 144 | 0.326 | 0.270 | 0.296 [0.226, 0.371] | 0.848 | 46/63 = 0.730 |
| Per step (sensitivity) | 143 | 0.336 | 0.276 | 0.303 [0.233, 0.379] | — | 15/25 = 0.600 (day 8); 34/39 = 0.872 (day 9) |

Other scopes for the joined view: full_membership 0.076, component 0.327, component_ge3 0.476. Jaccard 0.3 and 0.7 are in scored_seed28/*/summary.csv.

**Their own node-wise metrics (AUC-ROC / AUC-PR):** step 9 0.935 / 0.430; step 10 0.949 / 0.660. On validation, steps 7–8 give 0.954 / 0.816 and 0.954 / 0.786.

**Our reference on the same window:** GenAgg B0 ring-F1 0.5511 [0.458, 0.634], five seeds.

**Proposed paragraph for related work and limitations (proposal, not paper text).** TAML (ref) predicts laundering accounts and their sub-networks from per-day graphs. Under a conversion of its node predictions into rings, fixed before scoring, one seed reaches ring-F1 0.30 [0.23, 0.37] on our primary window, against 0.55 for our seeds-only baseline. That comparison is favourable to TAML: its features see the test days. Its graphs omit about 42 % of ring transactions, which caps it at 63 of 97 matchable rings, and on those rings its recall is 0.73. With one seed and different inputs, no paired test is made. The gap is better read as a difference in task (account flagging against ring recovery) than as a ranking of methods.

## 2026-11-18: three seeds (28, 1999, 1130), 10,000-draw intervals
Labels on every TAML number: features aggregated over all ten days, including the test days, with normalisation fitted on steps 1–8; about 42 % of in-window ring transactions are absent from its graphs (247/585); ceiling 63 of 97 matchable rings (joined view). HI-Small primary window, test days 8–9, 174 truth rings, Jaccard 0.5, test_visible. All intervals now use 10,000 draws (the 1,000-draw per-seed intervals above are superseded).

| Row | Seeds | Rings / seed | Precision | Recall | Ring-F1 [10k interval] | Coverage |
|---|---|---|---|---|---|---|
| TAML joined | 3 (seeds averaged per draw) | 132.7 | 0.379 [0.295, 0.467] | 0.287 [0.224, 0.354] | **0.327 [0.254, 0.403]** | 0.852 |
| TAML per step | 3 | 130.0 | 0.379 [0.293, 0.469] | 0.282 [0.216, 0.349] | 0.323 [0.249, 0.399] | 0.791 |
| GenAgg B0 (reference, same scorer) | 5 | 84.4 | 0.846 [0.709, 0.968] | 0.409 [0.343, 0.477] | 0.551 [0.462, 0.639] | 0.891 |

Per seed, joined ring-F1 [10k]: 28 0.296 [0.226, 0.371]; 1999 0.355 [0.274, 0.435]; 1130 0.330 [0.257, 0.409]. Per step: 0.303 [0.233, 0.379]; 0.343 [0.263, 0.424]; 0.322 [0.242, 0.403]. τ 0.797 / 0.873 / 0.862.
Recall on representable rings: joined, 63 rings: 0.730 / 0.841 / 0.794 (mean 0.788); per step, 25 (day 8) / 39 (day 9): 0.72 / 0.87, 0.88 / 0.90, 0.80 / 0.85.

**Exploratory paired bootstrap** (score_external --compare, 10,000 draws, seed 20261114, 174 rings): GenAgg B0 (5 seeds) − TAML joined (3 seeds), ring-F1 **+0.224 [+0.146, +0.304]**, p 0.0002; precision +0.466 [+0.351, +0.574]; recall +0.122 [+0.059, +0.186]. Exploratory, not pre-registered as a superiority test; it compares a ring pipeline with an account-flagging method converted to rings under the labels above.

**Proposed framing (not applied to the paper):** TAML solves account flagging; converted to rings it loses mainly through what its graphs omit. Inside the 63 rings its graphs can represent, it recovers 79 % (three-seed mean); over all 174 in-window rings its recall is 0.287, and most of the gap to GenAgg B0 is precision (0.38 vs 0.85). Not "we beat TAML".
Sources: experiments/R15_taml/scored_3seed_10k/{joined,per_step}, scored_seed{28,1999,1130}_10k, genagg_b0_ref_10k, paired_genagg_b0_vs_taml_joined.
