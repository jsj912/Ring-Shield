# Pre-registration amendment 2 — M1 train-split embeddings (2026-11-15)

Amends `paper/PREREG_METHOD_2026-11-15.md` (sha256 5b14316f…4d49) and
`paper/PREREG_METHOD_AMENDMENT_2026-11-15.md` (sha256 7feb2334…95bd); both stay frozen. Written on
the author's approval of option A, before any M1 training-candidate generation, embedding export or
verifier training. No M1 result has been seen (only the v42 0.2 % seed-1 reproduction, which
matched exactly).

## 1. Problem

The ring-folded expansion policy uses two embedding features (`cos_mean_included`, `cos_anchor`).
On val/test every edge has an embedding from the R1 detector. On train, the stored out-of-fold
embeddings (`experiments/R3_ringfold/cross_scores/embeddings_fold{k}.parquet`) cover only the edges
the policy's own training set needed (13,809 / 23,338 / 17,975 / 24,641 / 20,578 rows). The M1
train-candidate generator needs embeddings for every train edge its expansion and partition reach.

## 2. Fold rule (the rule cross_score.py uses, `CrossScorer.__init__` with `--ring-folds`)

- Day folds: contiguous day-aligned groups minimising the largest fold, as recorded in
  `experiments/R3_ringfold/cross_scores/config.yaml`: fold 0 = day 0, 1 = day 1, 2 = days 2–3,
  3 = day 4, 4 = day 5.
- Owner fold of a train edge: if the edge belongs to a train truth ring (`amlworld_train.parquet`
  `ring_id > 0`), the day fold holding the plurality of that ring's edges (ties → lower fold
  index); **every edge outside a ring keeps its own day fold**. This equals the `fold` column of
  `cross_scores_train.parquet` and of `ring_folds.parquet`; it is re-checked (0 mismatches required).
- Fold model k is trained with its owner-fold-k edges removed from both graph and labels, so
  **each train edge's embedding is taken from its owner fold's model**, which never trained on it.
- Recorded difference from the stored files: `make_training_set.py` embedded each ring's seeds
  with the fold model of the candidate group being featurised, so a stored seed embedding can come
  from a model that trained on that seed. M1 does not do that. Consequence: a trajectory that
  crosses a fold boundary compares embeddings from two fold models in its cosine features; the
  number of such trajectories is logged.

## 3. Export settings

Identical to the original export: `ringshield/expand/cross_score.py` embed path (`CrossScorer.embed`
→ `score_edges`), run directory `../RS-e2e/experiments/R1_gine_causal` (the `run_dir` in the
cross-score config), so batch size 8192, neighbours [100, 100], causal loader, loader route
`fallback`, window 1800 s, reverse message passing, ego ids and ports as in the R1 config; no
feature cache (the original chain passed none); `--ring-folds`. The only difference is the device:
CPU (`CUDA_VISIBLE_DEVICES=""`), at most 18 threads; the original ran on CUDA.
Checkpoints: byte copies of `experiments/R3_ringfold/cross_scores/fold{k}/model_best.pt` (and
`fold.json`, `cross_scores.json`) in `experiments/M1_verifier/embed/`, sha256-verified against the
originals. All outputs are written there; nothing under `experiments/R3_ringfold` is written.

## 4. Which edges are exported

The edges the M1 train generator reads embeddings for, found by closure:
1. Run the train generator (§5) with a recording store that logs every requested edge id and
   returns zeros for missing ones.
2. Export the logged edges (each with its owner fold) not yet exported.
3. Re-run with the real embeddings; repeat 2–3 until a run requests no missing edge. The final run
   is the one used. Iterations and per-fold counts are recorded.

## 5. Train generator details fixed here

- Edge score: `cross_scores_train.parquet` `score_raw` (owner-fold model); score quantile and dead
  region from that file's `score_quantile` and `dead_region` columns, as `make_training_set.py`.
- Train seeds: 0.2 % **within each fold** (`make_training_set.fold_seed_mask`, strict `score > q`),
  because fold models' scores are not on a common scale — the same rule the policy's own training
  set used. Val/test candidates keep the registered 0.2 % global rule.
- Expansion cell, affinity and linkage cut as registered (ring-folded fixed cell per detector seed;
  R4 affinity; seed's ring-folded average-linkage cut). The train generator depends on the detector
  seed only through these cells; one train candidate set is built per distinct cell.

## 6. Embedding reproduction check (before use)

Per fold, the export request includes every stored edge of `embeddings_fold{k}.parquet` whose owner
fold is k (at least 1,000 per fold; if fewer exist, the check says so). Recomputed and stored values
are compared: maximum and median absolute difference, and per-edge cosine similarity (median, min).
**If the median cosine of any fold is below 0.999, stop and report.** Fold 0 is exported first and
timed; if the projected time for all five folds (and the closure iterations) exceeds 6 hours, stop.
