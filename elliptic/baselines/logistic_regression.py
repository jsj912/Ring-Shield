import os
import yaml
import joblib
import numpy as np
import pandas as pd
import sys
sys.path.append(".")
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_recall_curve
from preprocessing.elliptic_loader import get_labeled_tabular_splits_with_val
from evaluations.classification_metrics import compute_metrics, save_metrics

seed = yaml.safe_load(open("configs/seed.yaml"))["seed"]
splits = get_labeled_tabular_splits_with_val()

# ---- 1. Scale features (fit on train_proper only, never on val/test) ----
scaler = StandardScaler()
X_train_proper_scaled = scaler.fit_transform(splits["X_train_proper"])
X_val_scaled = scaler.transform(splits["X_val"])

# ---- 2. Try a few class-weighting strategies, pick the best by validation F1 ----
candidate_weights = [
    ("none", None),
    ("balanced", "balanced"),
    ("light_3x", {0: 1, 1: 3}),
    ("light_5x", {0: 1, 1: 5}),
]

best_val_f1 = -1
best_weight_name, best_weight_val = None, None
for name, cw in candidate_weights:
    m = LogisticRegression(class_weight=cw, max_iter=1000, random_state=seed)
    m.fit(X_train_proper_scaled, splits["y_train_proper"])
    val_pred = m.predict(X_val_scaled)
    f1 = f1_score(splits["y_val"], val_pred, pos_label=1)
    print(f"class_weight={name}: val F1 = {f1:.4f}")
    if f1 > best_val_f1:
        best_val_f1 = f1
        best_weight_name, best_weight_val = name, cw

print(f"\nBest class_weight on validation: {best_weight_name} (val F1={best_val_f1:.4f})")

# ---- 3. With the best weighting, tune the decision threshold on validation ----
m = LogisticRegression(class_weight=best_weight_val, max_iter=1000, random_state=seed)
m.fit(X_train_proper_scaled, splits["y_train_proper"])
val_scores = m.predict_proba(X_val_scaled)[:, 1]

precisions, recalls, thresholds = precision_recall_curve(splits["y_val"], val_scores)
f1_scores = 2 * precisions * recalls / (precisions + recalls + 1e-10)
best_idx = np.argmax(f1_scores[:-1])   # last point has no corresponding threshold
best_threshold = thresholds[best_idx]
print(f"Best threshold on validation: {best_threshold:.4f} (val F1={f1_scores[best_idx]:.4f})")

# ---- 4. Refit on the FULL training period (timesteps 1-34) with chosen weight,
#         apply the chosen threshold, evaluate ONCE on test ----
X_train_full_scaled = scaler.fit_transform(splits["X_train_full"])   # refit scaler on full train
X_test_scaled = scaler.transform(splits["X_test"])

final_model = LogisticRegression(class_weight=best_weight_val, max_iter=1000, random_state=seed)
final_model.fit(X_train_full_scaled, splits["y_train_full"])

y_score = final_model.predict_proba(X_test_scaled)[:, 1]
y_pred = (y_score >= best_threshold).astype(int)

metrics = compute_metrics(splits["y_test"], y_pred, y_score)
metrics["chosen_class_weight"] = best_weight_name
metrics["chosen_threshold"] = float(best_threshold)

out_dir = "experiments/E1b_logistic_regression_tuned"
os.makedirs(out_dir, exist_ok=True)
save_metrics(metrics, f"{out_dir}/metrics.json")
joblib.dump({"model": final_model, "scaler": scaler, "threshold": best_threshold}, f"{out_dir}/model.pkl")
pd.DataFrame({"y_true": splits["y_test"], "y_pred": y_pred, "y_score": y_score}).to_csv(
    f"{out_dir}/predictions.csv", index=False
)

print("\nFinal test illicit F1:", metrics["illicit_f1"])
print("Weber et al. 2019 target: ~0.543")