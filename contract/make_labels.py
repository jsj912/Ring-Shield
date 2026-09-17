"""Write contract/out/labels_<split>.parquet (edge_id, true_label) for train / val / test.

    python contract/make_labels.py            # all three splits
    python contract/make_labels.py --dry-run  # 1% rows -> labels_<split>_dryrun.parquet

Labels are `Is Laundering` from data/processed/amlworld_<split>.parquet, keyed by edge_id.
These files are INTERNAL (PR-50): evaluation reads labels from here, never from a scores
file, and they are never shipped with scored_edges. labels_test.parquet is the same file
make_scored_edges.py writes (identical content; asserted here when it exists).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from contract.schema import LABELS_COLUMNS, LABELS_ORDER, pandas_dtypes  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402

SPLITS = ("train", "val", "test")
DRY_RUN_FRAC = 0.01


def make_labels(split: str, processed_dir: Path, out_dir: Path, *, dry_run: bool = False, seed: int = 1) -> Path:
    df = pd.read_parquet(processed_dir / f"amlworld_{split}.parquet", columns=["EdgeID", "Is Laundering"])
    if dry_run:
        # the same 1% models/tgn.py::load_data keeps: sample(frac, random_state=seed) over the
        # rows of formatted_transactions.csv, so dry-run scores and dry-run labels line up
        fmt = load_paths()["raw_dir"] / "formatted_transactions.csv"
        ids = pd.read_csv(fmt, usecols=["EdgeID"]).sample(frac=DRY_RUN_FRAC, random_state=seed)["EdgeID"]
        df = df[df["EdgeID"].isin(ids)]
    lab = (df.rename(columns={"EdgeID": "edge_id", "Is Laundering": "true_label"})[LABELS_ORDER]
           .sort_values("edge_id").reset_index(drop=True).astype(pandas_dtypes(LABELS_COLUMNS)))
    assert lab["edge_id"].is_unique
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"labels_{split}{'_dryrun' if dry_run else ''}.parquet"
    if out.exists() and not dry_run:
        old = pd.read_parquet(out)
        pd.testing.assert_frame_equal(old.sort_values("edge_id").reset_index(drop=True), lab,
                                      check_dtype=False)
    lab.to_parquet(out, index=False)
    print(f"[make_labels] {split}: {len(lab):,} rows, {int(lab['true_label'].sum()):,} positive -> {out}")
    return out


def main(argv=None):
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS))
    ap.add_argument("--processed-dir", type=Path, default=paths["processed_dir"])
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    ap.add_argument("--seed", type=int, default=1, help="dry-run sampling seed")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    for s in args.splits:
        make_labels(s, args.processed_dir, args.out_dir, dry_run=args.dry_run, seed=args.seed)


if __name__ == "__main__":
    main()
