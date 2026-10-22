# Footnote to r1_edge_metrics.csv — loader_window_s sensitivity (Step 3b-x, 2026-09-17)

test_* columns below are the WHOLE test split (as in the 3b-x analysis); primary_* columns are the days 8-9 primary window of configs/eval_window.yaml (3b-w). The `causal_legacyfeat` row in `r1_edge_metrics.csv` was scored with the causal fallback window W = 1,800 s (`loader_window_s`). The same checkpoints re-scored at W = 60 s and W = 300 s (scoring only, no retraining; side runs `experiments/R1x_score_w60`, `_w300`; threshold re-tuned on val per seed as usual) give (W = 60 s was capped at the seeds that had finished; the mean rows average the seeds present for each window):

| seed | W=60 val F1 / AP | W=300 val F1 / AP | W=1800 val F1 / AP | W=60 test F1 / AP | W=300 test F1 / AP | W=1800 test F1 / AP |
|---|---|---|---|---|---|---|
| 1 | 0.606 / 0.566 | 0.609 / 0.569 | 0.608 / 0.568 | 0.589 / 0.544 | 0.592 / 0.548 | 0.599 / 0.549 |
| 2 | 0.558 / 0.489 | 0.563 / 0.494 | 0.564 / 0.491 | 0.613 / 0.580 | 0.619 / 0.578 | 0.622 / 0.571 |
| 3 | – | 0.585 / 0.522 | 0.590 / 0.525 | – | 0.594 / 0.542 | 0.599 / 0.542 |
| 4 | – | 0.605 / 0.548 | 0.606 / 0.551 | – | 0.588 / 0.523 | 0.585 / 0.526 |
| 5 | – | 0.621 / 0.570 | 0.623 / 0.570 | – | 0.663 / 0.627 | 0.652 / 0.627 |
| mean | 0.582 / 0.528 | 0.597 / 0.541 | 0.598 / 0.541 | 0.601 / 0.562 | 0.611 / 0.564 | 0.611 / 0.563 |

Mean ± sd over the seeds present (n per window: W=60: 2, W=300: 5, W=1800: 5):

```
          val_f1          val_ap         test_f1         test_ap        
            mean     std    mean     std    mean     std    mean     std
window_s                                                                
60        0.5817  0.0340  0.5276  0.0539  0.6010  0.0177  0.5622  0.0251
300       0.5967  0.0228  0.5406  0.0325  0.6112  0.0316  0.5637  0.0404
1800      0.5980  0.0225  0.5412  0.0333  0.6114  0.0262  0.5631  0.0391
```

Per-seed values: `results/tables/r1_window_sensitivity.csv`. Full analysis: `docs/CAUSAL_LEAK.md`.
