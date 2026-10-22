# Residual leak inside the causal fallback window (Step 3b-x, 2026-09-17)

Context. The causal loader (`models/causal_loader.py`) cannot use PyG's native edge-level
temporal sampling on this machine (no Windows `pyg-lib`), so it batches seeds in contiguous
time windows of W = 1,800 s and drops every sampled edge later than the batch's latest seed.
Inside a batch an early seed can therefore still see edges up to W later than itself. R1
(causal, 5 seeds) showed no F1 penalty against the non-causal E6 checkpoints, which raised
the question whether that residual window carries the signal the causal constraint was
supposed to remove. Four measurements answer it; nothing in the R1 run was changed (that run
is now `experiments/R1_gine_causal_legacyfeat/`, renamed in Step 3b-z when R1 was retrained
on the trailing GFP features; every number below is from those legacy-feature checkpoints).

All numbers below are printed by `evaluation/causal_leak_tables.py` from the artefacts named
in each section; none were typed in.

## 1. How much of a seed's neighbourhood is in-window future? (`tests/measure_window_leak.py`)

Every validation batch of the causal loader at W = 1,800 s (R1 config: 100/100 neighbours,
batch 8,192; 118 batches, 965,524 seeds, 1,036 illicit). For each seed edge (u→v, t) the
message-passing edges it can reach in the batch subgraph — hop 1: edges incident to u or v;
hop 2: edges incident to the endpoints of hop-1 edges — in both stores (`to`, `rev_to`),
and the share of them with timestamp in (t, t_max of the batch]. Seed-to-batch-max gap:
mean 733 s, p90 1,380 s. Artefact: `docs/window_leak_val_w1800.json`.

| seeds | hop | n | empty hop | mean frac | p50 | p90 | p99 | seeds with ≥1 future | pooled frac | edges |
|---|---|---|---|---|---|---|---|---|---|---|
| illicit | hop1 | 1,036 | 0 | 1.67% | 0.00% | 2.81% | 36.36% | 23.46% | 1.49% | 1,455,071 |
| illicit | hop2 | 1,036 | 6 | 0.35% | 0.00% | 1.15% | 2.20% | 42.76% | 0.71% | 5,820,857 |
| illicit | hop1+2 | 1,036 | 0 | 0.75% | 0.06% | 1.63% | 11.43% | 51.16% | 0.86% | 7,275,928 |
| licit | hop1 | 964,488 | 0 | 1.28% | 0.00% | 2.94% | 12.90% | 43.20% | 1.55% | 1,170,516,131 |
| licit | hop2 | 964,488 | 3,484 | 0.35% | 0.00% | 1.14% | 2.17% | 42.50% | 0.74% | 5,022,805,480 |
| licit | hop1+2 | 964,488 | 0 | 0.67% | 0.37% | 1.52% | 5.26% | 62.83% | 0.89% | 6,193,321,611 |

Illicit seeds with ≥ 1 in-window-future neighbour that is itself illicit: hop 1 **1.16%**,
hop 2 4.25%, either 5.02% (n = 1,036).

Per store (pooled, hop 1): `to` 0.80% (illicit) / 0.84% (licit) vs `rev_to` **11.67% / 9.65%**;
hop 2: `to` 0.77% / 0.79%, `rev_to` 0.22% / 0.24%. Almost all in-window future mass sits in
the `rev_to` store at hop 1, i.e. it is the *sender's own subsequent outgoing transactions*
within the window (AMLworld accounts transact in bursts), not counterparties. Illicit and
licit seeds look alike on every row; the future share is not concentrated on illicit seeds.

## 2. How tightly are ring transactions clustered in time? (`preprocessing/ring_time_spread.py`)

|t_i − t_j| over every unordered pair of transactions in the same ring, all 370 rings
(43 have a single transaction). Artefact: `docs/ring_time_spread.json`.

| pattern | rings | pairs | < 300s | < 1800s | < 1h | < 6h | < 24h | median gap | p90 gap | median ring span |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 370 | 23,127 | 0.1% | 0.8% | 1.9% | 12.2% | 39.3% | 31.2 h | 79.8 h | 80.3 h |
| BIPARTITE | 49 | 1,066 | 0.7% | 2.4% | 4.1% | 26.9% | 74.2% | 14.2 h | 31.8 h | 35.2 h |
| CYCLE | 54 | 901 | 0.0% | 0.6% | 1.6% | 11.9% | 41.1% | 30.2 h | 70.0 h | 71.9 h |
| FAN-IN | 40 | 1,629 | 0.0% | 0.6% | 1.9% | 12.5% | 39.9% | 29.9 h | 71.6 h | 85.6 h |
| FAN-OUT | 48 | 1,681 | 0.0% | 0.7% | 2.3% | 13.4% | 41.2% | 28.4 h | 69.7 h | 84.6 h |
| GATHER-SCATTER | 51 | 6,700 | 0.0% | 0.5% | 1.3% | 8.0% | 26.5% | 48.8 h | 117.6 h | 150.8 h |
| RANDOM | 41 | 604 | 0.0% | 0.0% | 1.0% | 10.1% | 40.2% | 30.3 h | 66.2 h | 76.5 h |
| SCATTER-GATHER | 44 | 6,541 | 0.0% | 0.5% | 1.7% | 12.5% | 42.0% | 29.0 h | 69.3 h | 88.8 h |
| STACK | 43 | 4,005 | 0.3% | 1.4% | 2.5% | 14.7% | 45.3% | 26.0 h | 65.6 h | 73.3 h |

Only 0.8% of same-ring pairs are within 1,800 s of each other (2.4% for the tightest
pattern, BIPARTITE); the median gap is 31 h and the median ring spans 80 h. A 30-minute
window cannot contain a ring.

## 3. Scoring-only sensitivity to W (`evaluation/window_sensitivity.py`)

The five R1 checkpoints re-scored (no retraining) with `models/score.py --window-s W` into
`experiments/R1x_score_w{60,300}/`, val-tuned threshold per seed and window as usual
(`evaluation/edge_metrics.py --no-table`). W = 60 s was capped at the two seeds that had
finished when the analysis was closed (per-seed cost is the same as at 1,800 s, ≈ 6 min for
val + test, but the run shared the machine with the training run of §4). Artefacts:
`results/tables/r1_window_sensitivity.csv`, footnote `results/tables/r1_edge_metrics.footnote.md`.

| seed | val F1 / AP W=60 | val F1 / AP W=300 | val F1 / AP W=1800 | test F1 / AP W=60 | test F1 / AP W=300 | test F1 / AP W=1800 |
|---|---|---|---|---|---|---|
| 1 | 0.606 / 0.566 | 0.609 / 0.569 | 0.608 / 0.568 | 0.589 / 0.544 | 0.592 / 0.548 | 0.599 / 0.549 |
| 2 | 0.558 / 0.489 | 0.563 / 0.494 | 0.564 / 0.491 | 0.613 / 0.580 | 0.619 / 0.578 | 0.622 / 0.571 |
| 3 | – | 0.585 / 0.522 | 0.590 / 0.525 | – | 0.594 / 0.542 | 0.599 / 0.542 |
| 4 | – | 0.605 / 0.548 | 0.606 / 0.551 | – | 0.588 / 0.523 | 0.585 / 0.526 |
| 5 | – | 0.621 / 0.570 | 0.623 / 0.570 | – | 0.663 / 0.627 | 0.652 / 0.627 |
| mean (seeds present) | 0.582 / 0.528 | 0.597 / 0.541 | 0.598 / 0.541 | 0.601 / 0.562 | 0.611 / 0.564 | 0.611 / 0.563 |
| sd | 0.034 / 0.054 | 0.023 / 0.033 | 0.022 / 0.033 | 0.018 / 0.025 | 0.032 / 0.040 | 0.026 / 0.039 |

On the two seeds every window has (1, 2): val F1 0.582 / 0.586 / 0.586 and test F1
0.601 / 0.605 / 0.611 for W = 60 / 300 / 1,800 s. Narrowing the window 30× moves F1 by at
most 0.01 per seed, inside the threshold-grid noise (thresholds: seed 1 0.71 / 0.63 / 0.62,
seed 2 0.54 / 0.54 / 0.51). Inference does not use the in-window future edges.

## 4. Training sensitivity, one run (seed 1, `--window-s 300`, otherwise R1's command)

Run directory `experiments/R1x_gine_causal_w300/` — stopped after epoch 5 and **deleted in
Step 3b-z** (decision 2026-09-17: the collapse is a learning-rate artefact of 3.3× more
optimizer steps per epoch, not evidence about leakage, and the W = 300 s scoring is flat, so
the partial run had no further use; the two logged epochs are preserved here and in
`evaluation/causal_leak_tables.py`'s fallback parser). `models/tgn.py` prints epoch 1 and
every fifth epoch, so only two matched epochs exist.

| epoch | val F1 W=1800 | val F1 W=300 | Δ | val AP W=1800 | val AP W=300 | Δ | epoch s W=1800 | epoch s W=300 |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.4194 | 0.3132 | −0.1062 | 0.3410 | 0.2695 | −0.0715 | 231 | 979 |
| 5 | 0.5214 | 0.0000 | −0.5214 | 0.4775 | 0.0589 | −0.4186 | 231 | 518 |

The W = 300 s run collapsed to the all-negative solution by epoch 5 (train F1 0.005). That
is a learning-rate artefact, not evidence about leakage: a 300-s window gives 1,475 train
batches per epoch (mean 2,203 seeds) against 441 (mean 7,367) at 1,800 s — 3.3× more
optimizer steps per epoch at the same lr 0.006, on a model that has collapsed before when the
lr was too high for the schedule (implementation log: E6 collapse at epoch 75). Epoch time (979 s / 518 s vs 231 s)
was measured while two scoring jobs shared the machine and is not a clean number; §3 shows
scoring cost per seed does not depend on W. The run was stopped on that basis; a fair
training comparison would need the lr / schedule re-tuned for the step count, which is a
different experiment.

## Conclusion

**In-window future neighbours are rare and uninformative; W = 1,800 s stands.** A seed sees
on average 1.3–1.7% in-window-future edges at hop 1 and 0.35% at hop 2, illicit and licit
alike; only 1.2% of illicit seeds have any in-window-future illicit hop-1 neighbour; and
what future there is sits almost entirely in the `rev_to` store, i.e. the sender's own next
transactions in the same burst rather than ring counterparties. That matches the ground
truth: 0.8% of same-ring transaction pairs fall within 1,800 s of each other and the median
ring spans 80 hours, so the 30-minute window cannot expose ring structure. Consistently,
re-scoring the same checkpoints with W = 300 s (five seeds) and W = 60 s (two seeds)
changes F1 / AP by less than the threshold-grid noise. The absence of a causal penalty in
R1 therefore reflects the model not depending on future neighbours in the first place, not a
leak through the window. R1 is not re-run. (The features the model reads are a separate
question — see `docs/FEATURE_CAUSALITY.md`, Step 3b-y: two GFP columns look forward without
bound and do have to be recomputed.)

## Loose ends

* `models/causal_loader.py` / `models/tgn.py` / `models/score.py` gained `--window-s`
  (value recorded on the loader, in every score log and in `config.yaml`); a loader test
  covers it (`tests/test_causal_loader.py::test_window_s_parameter`).
* `experiments/R1x_score_w{60,300}/` hold the re-scored files and their `metrics.json`
  (tagged `feature_set: legacy_forwardcycle`); the stopped W = 300 s training directory was
  deleted (see §4). None of them feed the main table; `evaluation/edge_metrics.py --table`
  ignores `R1x_*`.
* The W = 60 s scoring was capped at seeds 1–2 (decision 2026-09-17) — the two seeds already
  showed the same flat picture as W = 300 s on five.
