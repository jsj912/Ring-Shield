"""account_id -> bank_code table, built once and used everywhere (Step 2.1).

    python preprocessing/account_bank.py            # writes data/processed/account_bank.parquet
    python preprocessing/account_bank.py --dry-run  # first 1% of raw rows -> account_bank_dryrun.parquet

The loader (preprocessing/amlworld_loader.py::rebuild_account_map) builds account ids by
concatenating str(bank) + str(account) and numbering keys in order of first appearance,
from-account before to-account within a row. This module reproduces that vectorised, keeps
the bank part, and validates every key against HI-Small_accounts.csv.

Columns: account_id (int64, 0..n-1), bank_code (int64), account_number (string).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

ACCOUNT_BANK_COLUMNS = ["account_id", "bank_code", "account_number"]
DRY_RUN_FRAC = 0.01


NON_PATH_KEYS = {"dataset"}


def load_paths(paths_yaml: Path | None = None) -> dict:
    """configs/paths.yaml with path-valued entries resolved against the repo root.

    Step 11 (R7): with no explicit file, `$RINGSHIELD_PATHS` selects the paths file, so a second
    dataset runs the *same commands* against its own raw / processed directories instead of
    overwriting the first one's. Unset (the default) means `configs/paths.yaml`, exactly as before.
    """
    if paths_yaml is None:
        import os
        env = os.environ.get("RINGSHIELD_PATHS")
        paths_yaml = Path(env) if env else REPO_ROOT / "configs" / "paths.yaml"
        if not Path(paths_yaml).is_absolute():
            paths_yaml = REPO_ROOT / paths_yaml
    with open(paths_yaml) as f:
        cfg = yaml.safe_load(f)
    # `dataset` is a release NAME, not a path, so it must not be resolved against the repo root.
    return {k: (REPO_ROOT / v if isinstance(v, str) and k not in NON_PATH_KEYS else v)
            for k, v in cfg.items()}


def raw_file(suffix: str, paths: dict | None = None) -> Path:
    """<raw_dir>/<dataset><suffix>, e.g. raw_file("_Trans.csv"). `dataset` defaults to HI-Small,
    so a paths file written before Step 11 resolves exactly as it always did."""
    paths = paths or load_paths()
    return paths["raw_dir"] / f"{paths.get('dataset', 'HI-Small')}{suffix}"


def build_account_bank_map(raw_trans_csv: Path, accounts_csv: Path | None = None,
                           nrows: int | None = None) -> pd.DataFrame:
    """Rebuild the loader's account_map and attach the bank code of every account.

    Returns a DataFrame with ACCOUNT_BANK_COLUMNS, one row per account id 0..n-1.
    If accounts_csv is given, every (bank, account) key must exist there with the
    same bank code; otherwise an AssertionError is raised.
    """
    raw = pd.read_csv(raw_trans_csv, usecols=[1, 2, 3, 4], nrows=nrows)
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
        "bank_code": banks[first_idx[order]],
        "account_number": accs[first_idx[order]],
        "key": uniq[order],
    })

    if accounts_csv is not None:
        acc = pd.read_csv(accounts_csv)
        acc["key"] = acc["Bank ID"].astype(str) + acc["Account Number"].astype(str)
        chk = amap.merge(acc[["key", "Bank ID"]], on="key", how="left")
        n_missing = int(chk["Bank ID"].isna().sum())
        assert n_missing == 0, f"{n_missing} accounts from the Trans CSV are absent in {accounts_csv}"
        n_disagree = int((chk["Bank ID"].astype(np.int64) != chk["bank_code"]).sum())
        assert n_disagree == 0, f"{n_disagree} accounts have a different bank code in {accounts_csv}"

    return amap[ACCOUNT_BANK_COLUMNS].astype({"account_id": "int64", "bank_code": "int64", "account_number": "string"})


def load_account_bank_map(path: Path | None = None, *, raw_trans_csv: Path | None = None,
                          accounts_csv: Path | None = None) -> pd.DataFrame:
    """Read data/processed/account_bank.parquet, building it first if absent."""
    paths = load_paths()
    path = Path(path) if path else paths["account_bank_map"]
    if not path.exists():
        raw_trans_csv = Path(raw_trans_csv) if raw_trans_csv else raw_file("_Trans.csv", paths)
        accounts_csv = Path(accounts_csv) if accounts_csv else raw_file("_accounts.csv", paths)
        amap = build_account_bank_map(raw_trans_csv, accounts_csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        amap.to_parquet(path, index=False)
    amap = pd.read_parquet(path)
    assert list(amap.columns) == ACCOUNT_BANK_COLUMNS, f"{path} has columns {list(amap.columns)}"
    return amap


def bank_of_series(amap: pd.DataFrame) -> pd.Series:
    """account_id-indexed Series of bank_code, for .reindex()/.loc lookups."""
    return amap.set_index("account_id")["bank_code"]


def main(argv=None):
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-trans-csv", type=Path, default=raw_file("_Trans.csv", paths))
    ap.add_argument("--accounts-csv", type=Path, default=raw_file("_accounts.csv", paths))
    ap.add_argument("--out", type=Path, default=paths["account_bank_map"])
    ap.add_argument("--dry-run", action="store_true", help=f"first {DRY_RUN_FRAC:.0%} of raw rows")
    args = ap.parse_args(argv)

    nrows = None
    out = args.out
    if args.dry_run:
        with open(args.raw_trans_csv, "rb") as f:
            n_total = sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 24), b"")) - 1
        nrows = max(1, int(DRY_RUN_FRAC * n_total))
        out = out.with_name(out.stem + "_dryrun" + out.suffix)
    amap = build_account_bank_map(args.raw_trans_csv, args.accounts_csv, nrows=nrows)
    out.parent.mkdir(parents=True, exist_ok=True)
    amap.to_parquet(out, index=False)
    print(f"[account_bank] {len(amap):,} accounts, {amap['bank_code'].nunique():,} banks -> {out}")


if __name__ == "__main__":
    main()
