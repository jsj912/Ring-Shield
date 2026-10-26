import os
import yaml
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from elliptic.evaluations.classification_metrics import compute_metrics, save_metrics

seed = yaml.safe_load(open("elliptic/configs/seed.yaml"))["seed"]

# ---- 1. Load and merge the two raw tables ----
train_trans = pd.read_csv("elliptic/data/raw/ieee_cis/train_transaction.csv")
train_id = pd.read_csv("elliptic/data/raw/ieee_cis/train_identity.csv")
df = train_trans.merge(train_id, on="TransactionID", how="left")

df = df.sample(50000, random_state=seed)

# ---- 3. Handle missing values ----
num_cols = df.select_dtypes(include=["int64", "float64"]).columns
cat_cols = df.select_dtypes(include=["object"]).columns
df[num_cols] = df[num_cols].fillna(df[num_cols].median())
df[cat_cols] = df[cat_cols].fillna("missing")

for col in cat_cols:
    le = LabelEncoder()
    df[col] = le.fit_transform(df[col].astype(str))

# ---- 5. Features / target split ----
df = df.drop(columns=["TransactionID"])
X = df.drop("isFraud", axis=1)
y = df["isFraud"]

# ---- 6. Train/test split (random, not chronological — see note below) ----
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=seed, stratify=y
)

# ---- 7. Scale the numeric/V-prefixed columns ----
sc = StandardScaler()
numeric_cols = ["TransactionAmt", "TransactionDT"] + [c for c in df.columns if c.startswith("V")]
X_train = X_train.copy()
X_test = X_test.copy()
X_train[numeric_cols] = sc.fit_transform(X_train[numeric_cols])
X_test[numeric_cols] = sc.transform(X_test[numeric_cols])

# ---- 8. Train ----
model = LogisticRegression(max_iter=5000, class_weight="balanced", solver="lbfgs", random_state=seed)
model.fit(X_train, y_train)

# ---- 9. Evaluate ----
y_pred = model.predict(X_test)
y_score = model.predict_proba(X_test)[:, 1]
metrics = compute_metrics(y_test, y_pred, y_score)

out_dir = "elliptic/baselines/_ieee_cis_scratch/experiments/full_features"
os.makedirs(out_dir, exist_ok=True)
save_metrics(metrics, f"{out_dir}/metrics.json")
joblib.dump(model, f"{out_dir}/model.pkl")
pd.DataFrame({"y_true": y_test, "y_pred": y_pred, "y_score": y_score}).to_csv(
    f"{out_dir}/predictions.csv", index=False
)

print("IEEE-CIS (full features) — fraud F1:", metrics["illicit_f1"])