"""Build the scored_edges contract parquet from a predictions_with_ids.csv.

Usage (PowerShell):

    python contract/make_scored_edges.py ^
        --preds experiments/E6_tgn/predictions_with_ids.csv ^
        --model-id gine --seed 1

Defaults for --test-parquet, --accounts-csv, --raw-trans-csv and --out come from
configs/paths.yaml. Add --dry-run to process a deterministic 1% sample of the
prediction rows (sampled with random_state=--seed).

Outputs:
    <out>            the contract parquet (columns / order: contract/schema.py)
    <out>.log.json   row counts, NaN count, timestamp offset, inputs, git commit

The account -> bank map is rebuilt from the raw HI-Small_Trans.csv with exactly the
key rule the loader uses (str(bank) + str(account), ids in first-appearance order),
validated against HI-Small_accounts.csv, and cached at
<processed_dir>/amlworld_account_bank_map.parquet.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.schema import (  # noqa: E402
    PREDICTIONS_WITH_IDS_COLUMNS,
    SCORED_EDGES_COLUMNS,
    SCORED_EDGES_ORDER,
    TEST_PARQUET_RENAMES,
)

ACCOUNT_MAP_CACHE = "amlworld_account_bank_map.parquet"
DRY_RUN_FRAC = 0.01


def load_paths(paths_yaml: Path = REPO_ROOT / "configs" / "paths.yaml") -> dict:
    with open(paths_yaml) as f:
        cfg = yaml.safe_load(f)
    return {k: (REPO_ROOT / v) for k, v in cfg.items()}


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:  # pragma: no cover
        return "unknown"


# --------------------------------------------------------------------------- #
# account -> bank map
# --------------------------------------------------------------------------- #
def build_account_bank_map(raw_trans_csv: Path, accounts_csv: Path | None = None) -> pd.DataFrame:
    """Rebuild the loader's account_map and attach the bank id of every account.

    Reproduces preprocessing/amlworld_loader.py::rebuild_account_map vectorised:
    key = str(From Bank) + str(Account), ids assigned in order of first appearance,
    from-account before to-account within a row. Returns a DataFrame with columns
    [account_id, bank_id, account_number], one row per account id 0..n-1.

    If accounts_csv is given, every (bank, account) key must exist there with the
    same bank id; otherwise an AssertionError is raised.
    """
    raw = pd.read_csv(raw_trans_csv, usecols=[1, 2, 3, 4])
    raw.columns = ["from_bank", "from_acc", "to_bank", "to_acc"]

    n = len(raw)
    keys = np.empty(2 * n, dtype=object)
    keys[0::2] = (raw["from_bank"].astype(str) + raw["from_acc"].astype(str)).values
    keys[1::2] = (raw["to_bank"].astype(str) + raw["to_acc"].astype(str)).values
    banks = np.empty(2 * n, dtype=np.int64)
    banks[0::2] = raw["from_bank"].values
    banks[1::2] = raw["to_bank"].values
    accs = np.empty(2 * n, dtype=object)
    accs[0::2] = raw["from_acc"].astype(str).values
    accs[1::2] = raw["to_acc"].astype(str).values

    uniq, first_idx = np.unique(keys, return_index=True)
    order = np.argsort(first_idx)  # first-appearance order == loader id order
    amap = pd.DataFrame({
        "account_id": np.arange(len(uniq), dtype=np.int64),
        "bank_id": banks[first_idx[order]],
        "account_number": accs[first_idx[order]],
        "key": uniq[order],
    })

    if accounts_csv is not None:
        acc = pd.read_csv(accounts_csv)
        acc["key"] = acc["Bank ID"].astype(str) + acc["Account Number"].astype(str)
        chk = amap.merge(acc[["key", "Bank ID"]], on="key", how="left")
        n_missing = int(chk["Bank ID"].isna().sum())
        assert n_missing == 0, f"{n_missing} accounts from the Trans CSV are absent in {accounts_csv}"
        n_disagree = int((chk["Bank ID"].astype(np.int64) != chk["bank_id"]).sum())
        assert n_disagree == 0, f"{n_disagree} accounts have a different bank id in {accounts_csv}"

    return amap.drop(columns="key")


def load_account_bank_map(raw_trans_csv: Path, accounts_csv: Path | None, cache: Path) -> pd.DataFrame:
    if cache.exists():
        return pd.read_parquet(cache)
    amap = build_account_bank_map(raw_trans_csv, accounts_csv)
    cache.parent.mkdir(parents=True, exist_ok=True)
    amap.to_parquet(cache, index=False)
    return amap


# --------------------------------------------------------------------------- #
# main transformation
# --------------------------------------------------------------------------- #
def make_scored_edges(
    preds_csv: Path,
    test_parquet: Path,
    accounts_csv: Path,
    model_id: str,
    seed: int,
    out_path: Path,
    *,
    raw_trans_csv: Path | None = None,
    account_map_cache: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Convert predictions_with_ids.csv + test parquet into the scored_edges contract.

    Returns the log dict that is also written to <out_path>.log.json.
    """
    preds_csv, test_parquet, accounts_csv, out_path = map(Path, (preds_csv, test_parquet, accounts_csv, out_path))
    paths = load_paths()
    raw_trans_csv = Path(raw_trans_csv) if raw_trans_csv else paths["raw_dir"] / "HI-Small_Trans.csv"
    account_map_cache = Path(account_map_cache) if account_map_cache else paths["processed_dir"] / ACCOUNT_MAP_CACHE

    # 1. predictions ---------------------------------------------------------
    preds = pd.read_csv(preds_csv)
    assert list(preds.columns) == PREDICTIONS_WITH_IDS_COLUMNS, (
        f"unexpected predictions columns {list(preds.columns)}; expected {PREDICTIONS_WITH_IDS_COLUMNS}")
    assert preds["EdgeID"].is_unique, "EdgeID is not unique in predictions"
    n_in = len(preds)
    if dry_run:
        preds = preds.sample(frac=DRY_RUN_FRAC, random_state=seed).sort_values("EdgeID").reset_index(drop=True)

    # 2. join on EdgeID ------------------------------------------------------
    test_cols = ["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering"] + [
        c for c in TEST_PARQUET_RENAMES if c != "Timestamp"]
    test = pd.read_parquet(test_parquet, columns=test_cols)
    assert test["EdgeID"].is_unique, "EdgeID is not unique in test parquet"
    m = preds.merge(test, on="EdgeID", how="left", suffixes=("", "_test"), validate="one_to_one")
    n_unmatched = int(m["from_id_test"].isna().sum())
    assert n_unmatched == 0, f"{n_unmatched} prediction EdgeIDs not found in {test_parquet}"
    assert (m["from_id"] == m["from_id_test"]).all(), "from_id disagrees between predictions and test parquet"
    assert (m["to_id"] == m["to_id_test"]).all(), "to_id disagrees between predictions and test parquet"
    # The model script re-bases Timestamp to df.Timestamp.min(); the loader re-based to
    # (first day 00:00 - 10 s). The two therefore differ by one global constant.
    ts_offset = (m["Timestamp_test"] - m["Timestamp"]).unique()
    assert len(ts_offset) == 1, (
        f"Timestamp offset between predictions and test parquet is not constant: {ts_offset[:5]}")
    ts_offset = int(ts_offset[0])
    assert (m["true_label"] == m["Is Laundering"]).all(), "true_label disagrees with 'Is Laundering'"

    # 3. banks ----------------------------------------------------------------
    amap = load_account_bank_map(raw_trans_csv, accounts_csv, account_map_cache)
    bank_of = amap.set_index("account_id")["bank_id"]
    m["from_bank"] = bank_of.reindex(m["from_id"].values).values
    m["to_bank"] = bank_of.reindex(m["to_id"].values).values
    assert not m["from_bank"].isna().any() and not m["to_bank"].isna().any(), (
        "account id missing from account->bank map")
    m["tenant_id"] = m["from_bank"]

    # 4. renames --------------------------------------------------------------
    m = m.drop(columns=["Timestamp", "from_id_test", "to_id_test", "true_label"]).rename(
        columns={**TEST_PARQUET_RENAMES, "Timestamp_test": "timestamp", "Is Laundering": "true_label"})

    # 5./6. scores -------------------------------------------------------------
    nan_mask = m["pred_prob"].isna()
    n_nan = int(nan_mask.sum())
    m["score_raw"] = m["pred_prob"].astype("float64")
    m["score_calibrated"] = m["score_raw"]  # Step 3 replaces this
    m["is_seed"] = (m["predicted_label"] == 1) & ~nan_mask
    m["model_id"] = model_id
    m["seed"] = seed

    # 7. write ------------------------------------------------------------------
    out = m[SCORED_EDGES_ORDER].astype(SCORED_EDGES_COLUMNS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)

    log = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "model_id": model_id,
        "seed": seed,
        "dry_run": dry_run,
        "dry_run_frac": DRY_RUN_FRAC if dry_run else None,
        "inputs": {
            "preds_csv": str(preds_csv), "test_parquet": str(test_parquet),
            "accounts_csv": str(accounts_csv), "raw_trans_csv": str(raw_trans_csv),
            "account_map_cache": str(account_map_cache),
        },
        "n_rows_predictions": n_in,
        "n_rows_out": int(len(out)),
        "n_nan_pred_prob": n_nan,
        "n_is_seed": int(out["is_seed"].sum()),
        "n_true_positive_label": int(out["true_label"].sum()),
        "timestamp_offset_seconds": ts_offset,
        "columns": SCORED_EDGES_ORDER,
        "out_path": str(out_path),
    }
    with open(str(out_path) + ".log.json", "w") as f:
        json.dump(log, f, indent=2)
    print(f"[make_scored_edges] wrote {len(out):,} rows -> {out_path}  "
          f"(NaN pred_prob kept: {n_nan}, is_seed: {log['n_is_seed']}, ts offset: {ts_offset}s)")
    return log


def main(argv=None):
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preds", type=Path, required=True, help="predictions_with_ids.csv")
    ap.add_argument("--model-id", required=True, help="e.g. gine")
    ap.add_argument("--seed", type=int, required=True, help="seed the predictions were produced with")
    ap.add_argument("--test-parquet", type=Path, default=paths["processed_dir"] / "amlworld_test.parquet")
    ap.add_argument("--accounts-csv", type=Path, default=paths["raw_dir"] / "HI-Small_accounts.csv")
    ap.add_argument("--raw-trans-csv", type=Path, default=paths["raw_dir"] / "HI-Small_Trans.csv")
    ap.add_argument("--out", type=Path, default=None,
                    help="default contract/out/scored_edges_<model>_<seed>.parquet")
    ap.add_argument("--dry-run", action="store_true", help=f"process a {DRY_RUN_FRAC:.0%} sample of rows")
    args = ap.parse_args(argv)

    suffix = "_dryrun" if args.dry_run else ""
    out = args.out or (REPO_ROOT / "contract" / "out" / f"scored_edges_{args.model_id}_{args.seed}{suffix}.parquet")
    make_scored_edges(args.preds, args.test_parquet, args.accounts_csv, args.model_id, args.seed, out,
                      raw_trans_csv=args.raw_trans_csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
