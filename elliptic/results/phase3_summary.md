# Phase 3 Summary — Elliptic Static GNN Baselines

Two GNN architectures trained on the Elliptic graph object (Phase 2), using the
same validation-tuning discipline as Phase 1's tabular baselines, adapted for
neural-network training (class-weight comparison, then threshold tuning, both
on a held-out validation window carved from the training period).

## Results
- GCN: F1 = 0.495 (Weber et al.: 0.628) — training/eval on timesteps 1-29 only
- GraphSAGE: F1 = 0.557 (no literature target) — same setup

## Key findings
1. **Both GNN architectures substantially underperform Random Forest (0.822) and
   XGBoost (0.759)**, replicating and extending Weber et al.'s core caution:
   graph structure alone, without temporal or ring-level modeling, does not
   automatically beat tabular baselines on this dataset.
2. **Both GNNs show a much larger validation-to-test performance gap (~38%
   relative) than the tree ensembles (15-19%)**, despite four different
   tuning approaches attempted for GCN specifically (see experiments/E3a_gcn's
   config.yaml notes for the full comparison). This gap size, being consistent
   across two different GNN architectures, points to a general property of
   message-passing models on this dataset rather than an architecture-specific
   bug: neighborhood feature statistics likely shift after Elliptic's documented
   mid-dataset distribution change (dark-market shutdown), and this shift
   propagates through every node's learned representation via message passing
   — a mechanism tree ensembles, which score each transaction independently,
   are structurally insulated from.
3. **GraphSAGE outperformed GCN** (0.557 vs 0.495), plausibly because its
   simpler mean-aggregation is less rigid than GCN's degree-normalized
   convolution when neighborhood statistics shift — a softer aggregation
   rule has less to get wrong when the underlying distribution moves. This is
   a reasonable hypothesis given the comparative evidence, not a confirmed
   mechanism.
3. Given four attempted tuning strategies for GCN converged toward the same
   ceiling (~0.4-0.5), further tuning was judged likely to constitute indirect
   test-set fitting rather than genuine improvement, and was stopped.

## Reproducibility
Same seed (42), same preprocessing/elliptic_loader.py split logic origin
(configs/elliptic_split.yaml's val_timesteps), same evaluation/classification_metrics.py.
Full tuning history for GCN documented in experiments/E3a_gcn/config.yaml.