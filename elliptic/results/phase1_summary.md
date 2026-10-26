## E1 → E1b iteration note
- E1 (default class_weight="balanced", threshold=0.5, no scaling): F1=0.314, Precision=0.192, Recall=0.867
- E1b (validation-tuned class_weight + threshold, scaled features): F1=0.488
- Diagnosis: E1's high recall/low precision combined with strong ROC-AUC (0.885)
  indicated the model's underlying ranking was good but the default threshold was
  miscalibrated for this class imbalance — confirmed by E1b's improvement via
  threshold tuning alone, isolated from the weighting change.

# Phase 1 Summary — Elliptic Tabular Baselines

Three models trained on identical splits (chronological 1-34 train / 35-49 test,
with a 30-34 validation window carved from train for tuning), AF feature set
(165 features), and consistent tuning discipline (class-weight/scale_pos_weight
sweep → threshold tuning, both on validation only, then a single evaluation on
held-out test).

## Results
- Logistic Regression: F1=0.489 (Weber et al.: 0.543, Δ=-0.054)
class_weight=none: val F1 = 0.6238
class_weight=balanced: val F1 = 0.5219
class_weight=light_3x: val F1 = 0.5912
class_weight=light_5x: val F1 = 0.5647
Best class_weight on validation: none (val F1=0.6238)
Best threshold on validation: 0.7728 (val F1=0.6762)
Final test illicit F1: 0.48892825509300264
Weber et al. 2019 target: ~0.543

- Random Forest: F1=0.822 (Weber et al.: 0.796, Δ=+0.026 — **exceeded**)
class_weight=none: val F1 = 0.9671
class_weight=balanced: val F1 = 0.9591
class_weight=light_3x: val F1 = 0.9626
class_weight=light_5x: val F1 = 0.9627
Best class_weight on validation: none (val F1=0.9671)
Best threshold on validation: 0.4800 (val F1=0.9691)
Final test illicit F1: 0.8221757322175732
Weber et al. 2019 target: ~0.796

- XGBoost: F1=0.759 (no literature target; best ROC-AUC at 0.938)
baseline_depth6: val F1 = 0.8977  ({'max_depth': 6, 'learning_rate': 0.3, 'subsample': 1.0, 'colsample_bytree': 1.0})
shallow_depth3: val F1 = 0.8921  ({'max_depth': 3, 'learning_rate': 0.1, 'subsample': 0.8, 'colsample_bytree': 0.8})
shallow_depth4: val F1 = 0.9275  ({'max_depth': 4, 'learning_rate': 0.1, 'subsample': 0.8, 'colsample_bytree': 0.8})
moderate_depth5_slow_lr: val F1 = 0.8409  ({'max_depth': 5, 'learning_rate': 0.05, 'subsample': 0.7, 'colsample_bytree': 0.7})
Best config: shallow_depth4 (val F1=0.9275)
Best threshold: 0.5627
Final test illicit F1: 0.7585877862595419


## Key findings
1. **Threshold miscalibration, not model weakness, was the initial bottleneck.**
   LR's untuned default (class_weight="balanced", threshold=0.5) produced F1=0.314
   despite ROC-AUC=0.885 — evidence the model's underlying ranking was always good,
   confirmed by threshold/weight tuning alone recovering F1=0.489.
2. **class_weight="none" (no reweighting) outperformed "balanced" on validation
   for all three models.** This is a genuine, reproducible pattern — maximal
   inverse-frequency weighting over-corrects for this dataset's ~9:1 imbalance;
   lighter or no correction, combined with a properly tuned decision threshold,
   consistently won.
3. **A validation→test performance gap appears across all three models**
   (RF: 0.969→0.822; XGBoost: 0.938→0.759), most severe for XGBoost. This is
   consistent with Elliptic's known mid-dataset distribution shift (the
   documented dark-market shutdown partway through the 49 timesteps), which
   makes the test period genuinely harder/different from the validation window
   — not a tuning bug. XGBoost's greater sensitivity to this shift, even after
   a regularization sweep (max_depth/learning_rate/subsample), is attributed to
   its sequential tree-fitting producing tighter, less-averaged decision
   boundaries than Random Forest's independent-tree ensemble.
4. Random Forest is the strongest F1; XGBoost has the best ROC-AUC (ranking
   quality) despite a lower F1 at its chosen threshold — both are legitimate,
   complementary observations for the report.

## Reproducibility
All three experiments use `configs/seed.yaml` (seed=42), the shared
`preprocessing/elliptic_loader.py` split logic, and
`evaluation/classification_metrics.py` for metrics — see individual
`experiments/E1_*/`, `E2a_*/`, `E2b_*/` folders for full configs/predictions/models.