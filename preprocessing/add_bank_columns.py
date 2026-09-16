"""Step 2.1: add from_bank / to_bank to the split Parquets and the ring ground truth.

    python preprocessing/add_bank_columns.py                # in place, data/processed/*
    python preprocessing/add_bank_columns.py --dry-run      # 1% of rows -> data/processed/dryrun/

Banks come from data/processed/account_bank.parquet (preprocessing/account_bank.py); the
loader itself is not modified. Idempotent: existing from_bank/to_bank columns are replaced.
Every file is written to a temp path and swapped in only after all assertions pass, and a
<file>.banks.log.json records the counts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.account_bank import bank_of_series, load_account_bank_map, load_paths  # noqa: E402

TARGETS = ["amlworld_train.parquet", "amlworld_val.parquet", "amlworld_test.parquet",
           "amlworld_ring_ground_truth.parquet"]
DRY_RUN_FRAC = 0.01


def add_bank_columns(df: pd.DataFrame, bank_of: pd.Series) -> pd.DataFrame:
    """Return df with from_bank/to_bank (int64) inserted right after to_id."""
    df = df.drop(columns=[c for c in ("from_bank", "to_bank") if c in df.columns])
    fb = bank_of.reindex(df["from_id"].values)
    tb = bank_of.reindex(df["to_id"].values)
    n_missing = int(fb.isna().sum() + tb.isna().sum())
    assert n_missing == 0, f"{n_missing} account ids have no bank_code in account_bank.parquet"
    pos = list(df.columns).index("to_id") + 1
    df.insert(pos, "from_bank", fb.values.astype("int64"))
    df.insert(pos + 1, "to_bank", tb.values.astype("int64"))
    return df


def process_file(src: Path, dst: Path, bank_of: pd.Series, *, frac: float | None, seed: int) -> dict:
    df = pd.read_parquet(src)
    n_in = len(df)
    if frac is not None:
        df = df.sample(frac=frac, random_state=seed).sort_index()
    out = add_bank_columns(df, bank_of)
    assert len(out) == len(df)
    assert list(out.columns)[:len(df.columns)] != list(df.columns) or "from_bank" in out.columns
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    pq.write_table(pa.Table.from_pandas(out, preserve_index=False), tmp)
    # verify the written file before swapping it in
    chk = pd.read_parquet(tmp, columns=["from_id", "to_id", "from_bank", "to_bank"])
    assert len(chk) == len(out)
    assert (bank_of.reindex(chk["from_id"].values).values == chk["from_bank"].values).all()
    assert (bank_of.reindex(chk["to_id"].values).values == chk["to_bank"].values).all()
    tmp.replace(dst)
    log = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "source": str(src), "output": str(dst), "dry_run": frac is not None,
        "n_rows_source": n_in, "n_rows_out": int(len(out)),
        "n_from_banks": int(out["from_bank"].nunique()), "n_to_banks": int(out["to_bank"].nunique()),
        "cross_bank_rows": int((out["from_bank"] != out["to_bank"]).sum()),
        "columns": list(out.columns),
    }
    with open(str(dst) + ".banks.log.json", "w") as f:
        json.dump(log, f, indent=2)
    return log


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def main(argv=None):
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--processed-dir", type=Path, default=paths["processed_dir"])
    ap.add_argument("--account-bank", type=Path, default=paths["account_bank_map"])
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="default: in place; with --dry-run default <processed-dir>/dryrun")
    ap.add_argument("--seed", type=int, default=None, help="dry-run sampling seed; default configs/seeds.yaml[0]")
    ap.add_argument("--dry-run", action="store_true", help=f"{DRY_RUN_FRAC:.0%} of rows, never in place")
    args = ap.parse_args(argv)

    if args.seed is None:
        import yaml
        with open(REPO_ROOT / "configs" / "seeds.yaml") as f:
            args.seed = int(yaml.safe_load(f)["seeds"][0])
    out_dir = args.out_dir or (args.processed_dir / "dryrun" if args.dry_run else args.processed_dir)
    bank_of = bank_of_series(load_account_bank_map(args.account_bank))
    for name in TARGETS:
        log = process_file(args.processed_dir / name, out_dir / name, bank_of,
                           frac=DRY_RUN_FRAC if args.dry_run else None, seed=args.seed)
        print(f"[add_bank_columns] {name}: {log['n_rows_out']:,} rows, "
              f"{log['n_from_banks']:,} from-banks, cross-bank rows {log['cross_bank_rows']:,} -> {log['output']}")


if __name__ == "__main__":
    main()
