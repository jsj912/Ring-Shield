import os
import yaml
import joblib
import numpy as np
import pandas as pd
import sys
sys.path.append(".")
from xgboost import XGBClassifier
from sklearn.metrics import f1_score, precision_recall_curve
from preprocessing.elliptic_loader import get_labeled_tabular_splits_with_val
from evaluations.classification_metrics import compute_metrics, save_metrics

seed = yaml.safe_load(open("configs/seed.yaml"))["seed"]
splits = get_labeled_tabular_splits_with_val()

n_neg = (splits["y_train_proper"] == 0).sum()
n_pos = (splits["y_train_proper"] == 1).sum()
computed_ratio = n_neg / n_pos   # already know this wins from your run — fixed now

# ---- Regularization sweep: shallower trees, slower learning, row/column subsampling
#      all reduce overfitting to the tuning window ----
candidate_configs = [
    ("baseline_depth6", dict(max_depth=6, learning_rate=0.3, subsample=1.0, colsample_bytree=1.0)),
    ("shallow_depth3", dict(max_depth=3, learning_rate=0.1, subsample=0.8, colsample_bytree=0.8)),
    ("shallow_depth4", dict(max_depth=4, learning_rate=0.1, subsample=0.8, colsample_bytree=0.8)),
    ("moderate_depth5_slow_lr", dict(max_depth=5, learning_rate=0.05, subsample=0.7, colsample_bytree=0.7)),
]

best_val_f1, best_name, best_cfg = -1, None, None
for name, cfg in candidate_configs:
    m = XGBClassifier(n_estimators=200, scale_pos_weight=computed_ratio, random_state=seed,
                       eval_metric="logloss", n_jobs=-1, **cfg)
    m.fit(splits["X_train_proper"], splits["y_train_proper"])
    f1 = f1_score(splits["y_val"], m.predict(splits["X_val"]), pos_label=1)
    print(f"{name}: val F1 = {f1:.4f}  ({cfg})")
    if f1 > best_val_f1:
        best_val_f1, best_name, best_cfg = f1, name, cfg

print(f"\nBest config: {best_name} (val F1={best_val_f1:.4f})")

# threshold tuning with the winning config
m = XGBClassifier(n_estimators=200, scale_pos_weight=computed_ratio, random_state=seed,
                   eval_metric="logloss", n_jobs=-1, **best_cfg)
m.fit(splits["X_train_proper"], splits["y_train_proper"])
val_scores = m.predict_proba(splits["X_val"])[:, 1]
precisions, recalls, thresholds = precision_recall_curve(splits["y_val"], val_scores)
f1_scores = 2 * precisions * recalls / (precisions + recalls + 1e-10)
best_threshold = thresholds[np.argmax(f1_scores[:-1])]
print(f"Best threshold: {best_threshold:.4f}")

# final refit on train_full, evaluate once on test
final_model = XGBClassifier(n_estimators=200, scale_pos_weight=computed_ratio, random_state=seed,
                             eval_metric="logloss", n_jobs=-1, **best_cfg)
final_model.fit(splits["X_train_full"], splits["y_train_full"])
y_score = final_model.predict_proba(splits["X_test"])[:, 1]
y_pred = (y_score >= best_threshold).astype(int)

metrics = compute_metrics(splits["y_test"], y_pred, y_score)
metrics.update({"chosen_scale_pos_weight": float(computed_ratio), "chosen_config_name": best_name,
                 "chosen_config": best_cfg, "chosen_threshold": float(best_threshold)})

out_dir = "experiments/E2b_xgboost"
os.makedirs(out_dir, exist_ok=True)
save_metrics(metrics, f"{out_dir}/metrics.json")
joblib.dump({"model": final_model, "threshold": best_threshold}, f"{out_dir}/model.pkl")
pd.DataFrame({"y_true": splits["y_test"], "y_pred": y_pred, "y_score": y_score}).to_csv(f"{out_dir}/predictions.csv", index=False)

print("\nFinal test illicit F1:", metrics["illicit_f1"])