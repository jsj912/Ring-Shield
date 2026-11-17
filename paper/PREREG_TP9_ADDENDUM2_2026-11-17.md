# T-P9 addendum 2 (2026-11-17): TAML seed 28 on the seeded rebuild, conversion and scoring

Author decision, 2026-11-17, approving the conversion rule proposed after addendum 1 (paper/PREREG_TP9_ADDENDUM_2026-11-17.md, gate 63/97 = 64.9 %) with the changes below. Written and sha256-logged in paper/RUNBOOK_PROGRESS.md before any training on the rebuilt graphs.

## 1. Training (seed 28 only)
- Graphs: `experiments/R15_taml/work_seeded/build_A`, the seeded rebuild (np.random.seed 20261117, repeatable).
- Fit with `experiments/R15_taml/run_ours.py --split ours --epochs 250 --seed 28` (steps 1–6 = our days 0–5), their IBM/FraudGT settings and their early stopping, unchanged. Output `experiments/R15_taml/runs_seeded/`.
- Stop after seed 28's rows and report. Seeds 1999 and 1130 need a further go-ahead.

## 2. Inference and threshold
- **Inference:** a wrapper runs TAML's own tester logic (`TAML_Tester.test_model`, unchanged forward pass: undirected embeddings, per-target-node signature and anomaly score = mean of the signature's anomaly scores) on steps 7, 8, 9 and 10, and saves per node: step, name, label, anomaly score and signature (as names).
- **Threshold τ for "predicted illicit":** chosen on validation steps 7–8 pooled, as the anomaly-score cut maximising node-wise F1 for class 1 (their ML-classification target), scanning every observed score. The test steps are not seen when choosing τ.

## 3. Primary conversion (joined view)
- Take the accounts with score ≥ τ on step 9 or step 10.
- Join the two step graphs by account name (union of the undirected edges).
- Form connected pieces of the joined graph restricted to the predicted accounts. Each piece with ≥ 3 accounts is one ring prediction.
- **Members:** our account ids whose `account_number` equals a piece's name. As in the representability count, accounts are keyed by the account string. The 8 strings shared across banks map to every one of our account ids with that string, so a shared string can add more than one of our accounts.
- **Member edges:** our test edge ids on days 8–9 whose two endpoints are members of the piece and whose (sender string, receiver string, step) is an edge of TAML's graph for that step (matched by account pair and day).

## 4. Sensitivity conversion (per step)
The same, but pieces are formed in each step's graph separately (predicted accounts of that step only, not joined across days). Member edges come only from that step's day.

## 5. Scoring
- `evaluation/score_external.py --split test --window primary --thresholds 0.3 0.5 0.7` (Jaccard 0.5 primary), all four scope conventions, its deterministic tie-break, default bootstrap intervals, min size 3. Minimal schema (ring_id, members, member_edges).
- **Reported:** ring precision, recall, ring-F1 with intervals, number of predictions, and member coverage (share of truth members inside some prediction).
- **Additionally:**
  - ring recall (Jaccard 0.5, test_visible) restricted to the 63 representable rings for the joined row;
  - the same restricted to the 25 (day 8) and 39 (day 9) per-day representable rings for the sensitivity row;
  - their own node-wise metrics on our test steps 9–10 (AUC-ROC, AUC-PR, average signature precision and recall per class), computed by their formulas on the saved signatures.

## 6. Labels carried by every TAML number
- One seed.
- Features aggregated over all ten days, including the test days; normalisation fitted on steps 1–8.
- About 42 % of in-window ring transactions are absent from its graphs (247/585).
- Ceiling: 63 of 97 matchable rings under the joined view.
- No paired test against our pipeline with one seed.

## 7. Scheduling
- HI-Medium has priority. TAML training or inference does not run while a HI-Medium scoring block runs (the last overlap cut scoring to about a third of its rate). TAML runs between HI-Medium jobs or after them.
- If the HI-Medium seed-1 bar fails and HI-Medium stops, TAML starts immediately.

## 8. After seed 28
Append to results/notes/p9_taml.md (dated):
- the four protocol differences;
- the representability table;
- the rows above;
- one paragraph for related work and limitations, marked as a proposal. The paper is not edited.
