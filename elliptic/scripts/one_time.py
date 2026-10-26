from elliptic.preprocessing.elliptic_loader import get_labeled_tabular_splits
X_train, y_train, X_test, y_test, labeled, full_df, edges = get_labeled_tabular_splits()
print("train rows:", len(X_train), "| train illicit:", (y_train==1).sum(), "| train licit:", (y_train==0).sum())
print("test rows:", len(X_test), "| test illicit:", (y_test==1).sum(), "| test licit:", (y_test==0).sum())
print("unlabeled rows:", (full_df["label"] == -1).sum())
print("total rows:", len(full_df), "| total edges:", len(edges))