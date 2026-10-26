import pandas as pd

def test_no_timestep_overlap():
    train = pd.read_parquet("data/processed/elliptic_train.parquet")
    test = pd.read_parquet("data/processed/elliptic_test.parquet")
    assert train.index.isin(test.index).sum() == 0, "train/test row overlap detected"