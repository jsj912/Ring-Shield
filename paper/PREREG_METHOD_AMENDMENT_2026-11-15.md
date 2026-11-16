# Pre-registration amendment — method track (2026-11-15)

Amends `paper/PREREG_METHOD_2026-11-15.md` (sha256
5b14316ffb34f3469935435fad5c94bd582cba283903826ca9cbd197729b4d49), which stays frozen. Written on
the author's instruction before any M1 training or candidate generation. No M-track result has
been seen.

## 1. M1 variants (replaces the M1 "Variants" paragraph and the feature list's role)

- **M1-V (primary).** The registered verifier, **without** any expansion-policy probability
  feature (mean / min / count of expanded-edge probabilities) and **without** any affinity /
  partition probability feature. Reason: the policy and affinity models were fit on train-period
  labels, so these features are in-sample on train candidates. `confidence` and `max_edge_prob`
  are also dropped from M1-V, because in the rings file they are derived from the expansion
  probabilities. All other features, the model, the threshold grid and the gate are as registered.
- **M1-V-IS (secondary, labelled "in-sample features").** The registered full feature set,
  including those probabilities. Same model, own threshold chosen on validation from the same
  grid. Reported beside M1-V, **excluded from the Holm family**, never the basis of a reading.
- **Out-of-fold variant: not added.** Checked 2026-11-15: no out-of-fold policy or affinity
  probabilities for train candidates exist under `experiments/R3_ringfold` (cross_scores holds
  fold-model edge scores and embeddings; `expansion/training_set.parquet` has fold ids and
  features but no prediction column; `policy_proposed/` holds the fitted policy only) or under
  `experiments/R4_partition_ringfold` (rings, configs and metrics only). They will not be built.
- The SUCCESS reading, the Holm p-value and the seed-1 validation gate for M1 use **M1-V only**.
  The baselines (REF, full at 0.2 % unverified, score-only filter M1-S) are unchanged.

## 2. Workload columns

The M1 table reports, for every variant and baseline, rings output per seed and accounts output per
seed (in-window and unrestricted), so a gain cannot come from outputting more.

## 3. Order and stops

M1 runs first and in full. M2 starts only while M1 waits on a long job or after M1 ends. M3 runs
only if M1 and M2 both finish inside their time boxes. Work stops for a report at the M1 seed-1
validation gate, pass or fail.
