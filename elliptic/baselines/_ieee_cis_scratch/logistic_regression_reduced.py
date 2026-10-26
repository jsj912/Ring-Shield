import os
import yaml
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from elliptic.evaluations.classification_metrics import compute_metrics, save_metrics

seed = yaml.safe_load(open("elliptic/configs/seed.yaml"))["seed"]

train_trans = pd.read_csv("elliptic/data/raw/ieee_cis/train_transaction.csv")
train_id = pd.read_csv("elliptic/data/raw/ieee_cis/train_identity.csv")
df = train_trans.merge(train_id, on="TransactionID", how="left")

df = df.sample(20000, random_state=seed)

# ---- Reduced feature set: amount, time, and only the first 60 V-columns ----
# (V1...V339 are anonymized engineered features from Vesta; using only the first
# 60 is a deliberate simplification for faster iteration, matching your notebook)
important_cols = ["TransactionAmt", "TransactionDT"] + [c for c in df.columns if c.startswith("V")][:60]
X = df[important_cols].copy()
y = df["isFraud"]

X = X.fillna(X.median())

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=seed, stratify=y
)

sc = StandardScaler()
X_train = sc.fit_transform(X_train)
X_test = sc.transform(X_test)

model = LogisticRegression(max_iter=1000, solver="lbfgs", class_weight="balanced", random_state=seed)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
y_score = model.predict_proba(X_test)[:, 1]
metrics = compute_metrics(y_test, y_pred, y_score)

out_dir = "elliptic/baselines/_ieee_cis_scratch/experiments/reduced_features"
os.makedirs(out_dir, exist_ok=True)
save_metrics(metrics, f"{out_dir}/metrics.json")
joblib.dump(model, f"{out_dir}/model.pkl")
pd.DataFrame({"y_true": y_test, "y_pred": y_pred, "y_score": y_score}).to_csv(
    f"{out_dir}/predictions.csv", index=False
)

print("IEEE-CIS (reduced features) — fraud F1:", metrics["illicit_f1"])
print("Iterations used:", model.n_iter_)