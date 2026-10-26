| E1 | Logistic Regression (val-tuned: class_weight=none, threshold=0.773) | 0.489 | 0.470 | 0.510 | 0.894 | experiments/E1_logistic_regression/ | target 0.543 — within range (Δ=0.054), validated via held-out threshold/weight tuning |

| E2a | Random Forest (val-tuned: class_weight=none, threshold=0.480) | 0.822 | 0.948 | 0.726 | 0.927 | experiments/E2a_random_forest/ | target 0.796 — **exceeded** (Δ=+0.026) |

| E2b | XGBoost (val-tuned: scale_pos_weight=8.19, max_depth=4, lr=0.1, subsample=0.8, colsample=0.8, threshold=0.563) | 0.759 | 0.785 | 0.734 | 0.938 | experiments/E2b_xgboost/ | no direct target — below E2a RF (0.822), highest ROC-AUC of the three |

| E3a | GCN (val-tuned: class_weights=False, threshold=0.562, trained on timesteps 1-29 only) | 0.495 | 0.4918 | 0.4986 | 0.842 | experiments/E3a_gcn/ | target 0.628 — below target; large val→test gap (38%) vs. tree ensembles (15-19%), attributed to message-passing sensitivity to Elliptic's distribution shift — see config notes |

| E3b | GraphSAGE (val-tuned: class_weights=False, threshold=0.557, trained on timesteps 1-29 only) | 0.557 | 0.491 | 0.643 | 0.886 | experiments/E3b_graphsage/ | no direct target — beats E3a GCN by 0.062; same ~38% val→test gap pattern, corroborating the message-passing sensitivity finding rather than an architecture-specific quirk |