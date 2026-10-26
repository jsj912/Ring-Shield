import os
import yaml
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_recall_curve
from elliptic.preprocessing.elliptic_loader import get_labeled_tabular_splits_with_val
from elliptic.evaluations.classification_metrics import compute_metrics, save_metrics

seed = yaml.safe_load(open("elliptic/configs/seed.yaml"))["seed"]
splits = get_labeled_tabular_splits_with_val()

# ---- 1. Sweep class_weight options on train_proper/val (no scaling needed — trees
#         split on raw thresholds, unlike Logistic Regression) ----
candidate_weights = [
    ("none", None),
    ("balanced", "balanced"),
    ("light_3x", {0: 1, 1: 3}),
    ("light_5x", {0: 1, 1: 5}),
]

best_val_f1, best_weight_name, best_weight_val = -1, None, None
for name, cw in candidate_weights:
    m = RandomForestClassifier(n_estimators=100, class_weight=cw, random_state=seed, n_jobs=-1)
    m.fit(splits["X_train_proper"], splits["y_train_proper"])
    f1 = f1_score(splits["y_val"], m.predict(splits["X_val"]), pos_label=1)
    print(f"class_weight={name}: val F1 = {f1:.4f}")
    if f1 > best_val_f1:
        best_val_f1, best_weight_name, best_weight_val = f1, name, cw

print(f"\nBest class_weight on validation: {best_weight_name} (val F1={best_val_f1:.4f})")

# ---- 2. With the winning weight, tune the decision threshold on validation ----
m = RandomForestClassifier(n_estimators=100, class_weight=best_weight_val, random_state=seed, n_jobs=-1)
m.fit(splits["X_train_proper"], splits["y_train_proper"])
val_scores = m.predict_proba(splits["X_val"])[:, 1]

precisions, recalls, thresholds = precision_recall_curve(splits["y_val"], val_scores)
f1_scores = 2 * precisions * recalls / (precisions + recalls + 1e-10)
best_idx = np.argmax(f1_scores[:-1])
best_threshold = thresholds[best_idx]
print(f"Best threshold on validation: {best_threshold:.4f} (val F1={f1_scores[best_idx]:.4f})")

# ---- 3. Refit on the FULL training period (timesteps 1-34), evaluate ONCE on test ----
final_model = RandomForestClassifier(n_estimators=100, class_weight=best_weight_val, random_state=seed, n_jobs=-1)
final_model.fit(splits["X_train_full"], splits["y_train_full"])

y_score = final_model.predict_proba(splits["X_test"])[:, 1]
y_pred = (y_score >= best_threshold).astype(int)

metrics = compute_metrics(splits["y_test"], y_pred, y_score)
metrics["chosen_class_weight"] = best_weight_name
metrics["chosen_threshold"] = float(best_threshold)

out_dir = "elliptic/experiments/E2a_random_forest"
os.makedirs(out_dir, exist_ok=True)
save_metrics(metrics, f"{out_dir}/metrics.json")
joblib.dump({"model": final_model, "threshold": best_threshold}, f"{out_dir}/model.pkl")
pd.DataFrame({"y_true": splits["y_test"], "y_pred": y_pred, "y_score": y_score}).to_csv(
    f"{out_dir}/predictions.csv", index=False
)

print("\nFinal test illicit F1:", metrics["illicit_f1"])
print("Weber et al. 2019 target: ~0.796")