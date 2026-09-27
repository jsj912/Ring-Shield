"""Checks for contract/make_scored_edges.py, run on the 1% dry-run sample.

    python -m pytest contract/tests -q

Needs experiments/E6_tgn/predictions_with_ids.csv, data/processed/amlworld_test.parquet
and data/raw/HI-Small_{Trans,accounts}.csv on disk (all untracked).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import (  # noqa: E402
    DRY_RUN_FRAC, load_paths, main, make_scored_edges,
)
from contract.schema import (  # noqa: E402
    LABELS_ORDER, PREDICTIONS_WITH_IDS_COLUMNS, SCORED_EDGES_COLUMNS, SCORED_EDGES_ORDER,
    pandas_dtypes,
)

PATHS = load_paths()
ACCOUNT_MAP = PATHS["account_bank_map"]
PREDS_CSV = REPO_ROOT / "experiments" / "E6_tgn" / "predictions_with_ids.csv"
TEST_PARQUET = PATHS["processed_dir"] / "amlworld_test.parquet"
ACCOUNTS_CSV = PATHS["raw_dir"] / f"{PATHS.get('dataset', 'HI-Small')}_accounts.csv"
RAW_TRANS_CSV = PATHS["raw_dir"] / f"{PATHS.get('dataset', 'HI-Small')}_Trans.csv"
MODEL_ID, SEED = "gine", 1

pytestmark = pytest.mark.skipif(
    not (PREDS_CSV.exists() and TEST_PARQUET.exists() and ACCOUNTS_CSV.exists() and RAW_TRANS_CSV.exists()),
    reason="dry-run inputs not on disk",
)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("scored") / f"scored_edges_{MODEL_ID}_{SEED}_dryrun.parquet"
    log = make_scored_edges(PREDS_CSV, TEST_PARQUET, ACCOUNTS_CSV, MODEL_ID, SEED, out, dry_run=True)
    return {"out": out, "log": log, "df": pd.read_parquet(out), "labels": pd.read_parquet(log["labels_path"])}


@pytest.fixture(scope="module")
def preds_sample(run):
    preds = pd.read_csv(PREDS_CSV)
    return preds[preds["EdgeID"].isin(run["df"]["edge_id"])].sort_values("EdgeID").reset_index(drop=True)


@pytest.fixture(scope="module")
def test_rows(run):
    t = pd.read_parquet(TEST_PARQUET)
    return t[t["EdgeID"].isin(run["df"]["edge_id"])].sort_values("EdgeID").reset_index(drop=True)


# 7. exact contract columns, contract order, dtypes ----------------------------
def test_columns_are_exactly_the_contract_in_order(run):
    assert list(run["df"].columns) == SCORED_EDGES_ORDER


def test_dtypes_match_contract(run):
    got = {c: str(run["df"][c].dtype) for c in run["df"].columns}
    for col, want in pandas_dtypes(SCORED_EDGES_COLUMNS).items():
        if want == "string":
            assert got[col].startswith("str"), (col, got[col])
        else:
            assert got[col] == want, (col, got[col], want)


# --dry-run processes 1% of rows, deterministically -----------------------------
def test_dry_run_is_one_percent_and_unique(run, preds_sample):
    n_all = run["log"]["n_rows_predictions"]
    assert n_all == 863_900
    assert len(run["df"]) == round(DRY_RUN_FRAC * n_all)
    assert run["df"]["edge_id"].is_unique
    assert len(preds_sample) == len(run["df"])  # every output EdgeID exists in the input


def test_dry_run_is_deterministic(run, tmp_path):
    out2 = tmp_path / "again.parquet"
    make_scored_edges(PREDS_CSV, TEST_PARQUET, ACCOUNTS_CSV, MODEL_ID, SEED, out2, dry_run=True)
    df2 = pd.read_parquet(out2)
    pd.testing.assert_frame_equal(run["df"], df2)


# 1. predictions header is asserted ---------------------------------------------
def test_wrong_predictions_columns_raise(tmp_path):
    bad = pd.read_csv(PREDS_CSV, nrows=50).drop(columns="predicted_label")
    p = tmp_path / "bad.csv"
    bad.to_csv(p, index=False)
    with pytest.raises(AssertionError, match="unexpected predictions columns"):
        make_scored_edges(p, TEST_PARQUET, ACCOUNTS_CSV, MODEL_ID, SEED, tmp_path / "x.parquet")


def test_predictions_header_constant_matches_file():
    assert pd.read_csv(PREDS_CSV, nrows=0).columns.tolist() == PREDICTIONS_WITH_IDS_COLUMNS


# 2. join on EdgeID; from_id / to_id / Timestamp agree on 100% of rows ------------
def test_join_agrees_with_test_parquet(run, test_rows, preds_sample):
    df = run["df"]
    assert (df["edge_id"].values == test_rows["EdgeID"].values).all()
    assert (df["from_id"].values == test_rows["from_id"].values).all()
    assert (df["to_id"].values == test_rows["to_id"].values).all()
    assert (df["from_id"].values == preds_sample["from_id"].values).all()
    assert (df["to_id"].values == preds_sample["to_id"].values).all()
    assert "true_label" not in df.columns  # PR-50: no ground truth in the contract file
    labels = run["labels"]
    assert list(labels.columns) == LABELS_ORDER
    assert (labels["edge_id"].values == df["edge_id"].values).all()
    assert (labels["true_label"].values == test_rows["Is Laundering"].values).all()
    assert (labels["true_label"].values == preds_sample["true_label"].values).all()
    # timestamp is the test-parquet one; the model's differs by one global constant
    assert (df["timestamp"].values == test_rows["Timestamp"].values).all()
    offset = df["timestamp"].values - preds_sample["Timestamp"].values
    assert len(np.unique(offset)) == 1
    assert int(offset[0]) == run["log"]["timestamp_offset_seconds"] == PATHS["legacy_csv_time_offset_s"] == 10


def test_edge_id_indexes_formatted_transactions(run):
    """EdgeID is the arange index format_kaggle_files.py assigned after sorting by
    Timestamp, i.e. the row number of data/raw/formatted_transactions.csv."""
    fmt_csv = PATHS["raw_dir"] / "formatted_transactions.csv"
    if not fmt_csv.exists():
        pytest.skip("formatted_transactions.csv not on disk")
    df = run["df"].sample(n=200, random_state=SEED)
    rows = set(df["edge_id"].tolist())
    fmt = pd.read_csv(fmt_csv, skiprows=lambda i: i != 0 and (i - 1) not in rows).set_index("EdgeID")
    fmt = fmt.loc[df["edge_id"].values]
    assert (fmt["from_id"].values == df["from_id"].values).all()
    assert (fmt["to_id"].values == df["to_id"].values).all()
    assert (fmt["Timestamp"].values == df["timestamp"].values).all()
    assert np.allclose(fmt["Amount Sent"].values, df["amount_sent"].values)
    assert np.allclose(fmt["Amount Received"].values, df["amount_received"].values)
    assert (fmt["Is Laundering"].values == run["labels"].set_index("edge_id").loc[df["edge_id"], "true_label"].values).all()


# 3. banks via the account map; tenant_id = from_bank ------------------------------
def test_bank_map_reproduces_loader_account_map(tmp_path):
    """build_account_bank_map must assign the same id to every account as the
    loader's rebuild_account_map (run here on the first 20k raw rows)."""
    from preprocessing.account_bank import build_account_bank_map
    from preprocessing.amlworld_loader import rebuild_account_map
    prefix = tmp_path / "prefix.csv"
    pd.read_csv(RAW_TRANS_CSV, nrows=20_000).to_csv(prefix, index=False)
    loader_map, _ = rebuild_account_map(prefix)
    ours = build_account_bank_map(prefix, accounts_csv=ACCOUNTS_CSV)
    ours_map = dict(zip(ours["bank_code"].astype(str) + ours["account_number"], ours["account_id"]))
    assert ours_map == loader_map


def test_cached_map_covers_every_account_in_output(run):
    amap = pd.read_parquet(ACCOUNT_MAP).set_index("account_id")
    assert amap.index.equals(pd.RangeIndex(len(amap)))
    df = run["df"]
    assert (amap.loc[df["from_id"], "bank_code"].values == df["from_bank"].values).all()
    assert (amap.loc[df["to_id"], "bank_code"].values == df["to_bank"].values).all()


def test_bank_map_agrees_with_accounts_csv():
    amap = pd.read_parquet(ACCOUNT_MAP)
    acc = pd.read_csv(ACCOUNTS_CSV)
    acc["key"] = acc["Bank ID"].astype(str) + acc["Account Number"].astype(str)
    amap["key"] = amap["bank_code"].astype(str) + amap["account_number"].astype(str)
    chk = amap.merge(acc[["key", "Bank ID"]], on="key", how="left")
    assert chk["Bank ID"].notna().all()
    assert (chk["Bank ID"].astype("int64") == chk["bank_code"]).all()


def test_tenant_id_is_from_bank(run):
    assert (run["df"]["tenant_id"] == run["df"]["from_bank"]).all()
    assert run["df"]["from_bank"].notna().all() and run["df"]["to_bank"].notna().all()


# 4. renamed columns carry the test-parquet values ---------------------------------
def test_renamed_columns_match_test_parquet(run, test_rows):
    df = run["df"]
    pairs = {
        "amount_sent": "Amount Sent", "amount_received": "Amount Received",
        "currency_sent": "Sent Currency", "currency_received": "Received Currency",
        "payment_format": "Payment Format",
    }
    for new, old in pairs.items():
        assert (df[new].values == test_rows[old].values).all(), new


# 5./6. scores and NaN handling -----------------------------------------------------
def test_scores_and_seed_flags(run, preds_sample):
    df = run["df"]
    nan = preds_sample["pred_prob"].isna().values
    assert nan.sum() == run["log"]["n_nan_pred_prob"] > 0, "dry-run sample should contain NaN rows"
    assert df["score_raw"].isna().values.tolist() == nan.tolist()
    assert np.allclose(df.loc[~nan, "score_raw"].values, preds_sample.loc[~nan, "pred_prob"].values)
    pd.testing.assert_series_equal(df["score_calibrated"], df["score_raw"], check_names=False)
    want = ((preds_sample["predicted_label"] == 1) & ~preds_sample["pred_prob"].isna()).values
    assert df["is_seed"].values.tolist() == want.tolist()
    assert not df.loc[nan, "is_seed"].any()
    assert df["is_seed"].dtype == bool


def test_model_id_and_seed_columns(run):
    assert (run["df"]["model_id"] == MODEL_ID).all()
    assert (run["df"]["seed"] == SEED).all()


# log + CLI ------------------------------------------------------------------------
def test_log_json_written(run):
    log_path = Path(str(run["out"]) + ".log.json")
    assert log_path.exists()
    log = json.loads(log_path.read_text())
    for k in ("git_commit", "model_id", "seed", "dry_run", "n_rows_predictions", "n_rows_out",
              "n_nan_pred_prob", "n_is_seed", "timestamp_offset_seconds", "columns", "inputs"):
        assert k in log, k
    assert log["columns"] == SCORED_EDGES_ORDER
    assert log["n_rows_out"] == len(run["df"])
    assert len(log["git_commit"]) == 40


def test_cli_requires_seed_and_model_id(capsys):
    with pytest.raises(SystemExit):
        main(["--preds", str(PREDS_CSV), "--dry-run"])
    assert "--seed" in capsys.readouterr().err


def test_cli_dry_run_writes_default_path(tmp_path):
    out = tmp_path / "cli.parquet"
    main(["--preds", str(PREDS_CSV), "--model-id", MODEL_ID, "--seed", str(SEED), "--dry-run", "--out", str(out)])
    assert out.exists() and Path(str(out) + ".log.json").exists()
