import sys
sys.path.append(".")
from preprocessing.elliptic_loader import get_labeled_tabular_splits
X_train, y_train, X_test, y_test, labeled, full_df, edges = get_labeled_tabular_splits()

train_out = X_train.copy(); train_out["label"] = y_train
test_out = X_test.copy(); test_out["label"] = y_test
train_out.to_parquet("data/processed/elliptic_train.parquet")
test_out.to_parquet("data/processed/elliptic_test.parquet")
full_df.to_parquet("data/processed/elliptic_all.parquet")