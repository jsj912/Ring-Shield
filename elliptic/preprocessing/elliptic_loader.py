import pandas as pd
import yaml

def load_elliptic_raw(raw_dir="data/raw/elliptic"):
    features = pd.read_csv(f"{raw_dir}/elliptic_txs_features.csv", header=None)
    features.columns = ["txId", "time_step"] + [f"feat_{i}" for i in range(165)]
    classes = pd.read_csv(f"{raw_dir}/elliptic_txs_classes.csv")
    edges = pd.read_csv(f"{raw_dir}/elliptic_txs_edgelist.csv")

    df = features.merge(classes, on="txId", how="left")
    # illicit=1, licit=0, unknown=-1
    label_map = {"1": 1, "2": 0, "unknown": -1}
    df["label"] = df["class"].map(label_map)
    df = df.drop(columns=["class"])
    return df, edges

def split_by_timestep(df, split_cfg):
    train_lo, train_hi = split_cfg["train_timesteps"]
    test_lo, test_hi = split_cfg["test_timesteps"]
    train_mask = df["time_step"].between(train_lo, train_hi)
    test_mask = df["time_step"].between(test_lo, test_hi)
    return train_mask, test_mask

def get_labeled_tabular_splits(feature_cfg_path="configs/elliptic_features.yaml",
                                split_cfg_path="configs/elliptic_split.yaml",
                                raw_dir="data/raw/elliptic"):
    with open(feature_cfg_path) as f:
        feat_cfg = yaml.safe_load(f)
    with open(split_cfg_path) as f:
        split_cfg = yaml.safe_load(f)

    df, edges = load_elliptic_raw(raw_dir)
    train_mask, test_mask = split_by_timestep(df, split_cfg)

    labeled = df[df["label"] != -1].copy()
    train_mask_l, test_mask_l = split_by_timestep(labeled, split_cfg)
    print("Number of timesteps:", df["time_step"].nunique())
    print("Label counts:")
    print(labeled["label"].value_counts())
    print("All labeled rows accounted for:",train_mask_l.sum() + test_mask_l.sum() == len(labeled))

    feat_cols = [c for c in labeled.columns if c.startswith("feat_")]
    if feat_cfg["feature_set"] == "LF":
        feat_cols = feat_cols[:93] 

    X_train = labeled.loc[train_mask_l, feat_cols]
    y_train = labeled.loc[train_mask_l, "label"]
    X_test = labeled.loc[test_mask_l, feat_cols]
    y_test = labeled.loc[test_mask_l, "label"]

    return X_train, y_train, X_test, y_test, labeled, df, edges
def get_labeled_tabular_splits_with_val(feature_cfg_path="configs/elliptic_features.yaml",
                                          split_cfg_path="configs/elliptic_split.yaml",
                                          raw_dir="data/raw/elliptic"):

    with open(feature_cfg_path) as f:
        feat_cfg = yaml.safe_load(f)
    with open(split_cfg_path) as f:
        split_cfg = yaml.safe_load(f)

    df, edges = load_elliptic_raw(raw_dir)
    labeled = df[df["label"] != -1].copy()

    val_lo, val_hi = split_cfg["val_timesteps"]           # [30, 34]
    train_lo, train_hi = split_cfg["train_timesteps"]     # [1, 34]
    test_lo, test_hi = split_cfg["test_timesteps"]        # [35, 49]

    # "train_proper" excludes the val window so val is genuinely held out
    train_proper_mask = labeled["time_step"].between(train_lo, val_lo - 1)
    val_mask = labeled["time_step"].between(val_lo, val_hi)
    full_train_mask = labeled["time_step"].between(train_lo, train_hi)  # for final refit
    test_mask = labeled["time_step"].between(test_lo, test_hi)

    feat_cols = [c for c in labeled.columns if c.startswith("feat_")]

    return {
        "X_train_proper": labeled.loc[train_proper_mask, feat_cols],
        "y_train_proper": labeled.loc[train_proper_mask, "label"],
        "X_val": labeled.loc[val_mask, feat_cols],
        "y_val": labeled.loc[val_mask, "label"],
        "X_train_full": labeled.loc[full_train_mask, feat_cols],
        "y_train_full": labeled.loc[full_train_mask, "label"],
        "X_test": labeled.loc[test_mask, feat_cols],
        "y_test": labeled.loc[test_mask, "label"],
    }