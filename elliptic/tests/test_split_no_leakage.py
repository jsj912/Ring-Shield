import pandas as pd

def test_no_timestep_overlap():
    train = pd.read_parquet("elliptic/data/processed/elliptic_train.parquet")
    test = pd.read_parquet("elliptic/data/processed/elliptic_test.parquet")
    assert train.index.isin(test.index).sum() == 0, "train/test row overlap detected"


if __name__ == "__main__":
    test_no_timestep_overlap()
    print("no train/test row overlap")
