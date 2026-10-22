"""Map old EdgeID -> new EdgeID after regenerating formatted_transactions.csv (Step 3a).

    python scripts/remap_edge_ids.py --old <backup formatted_transactions.csv> \
        --new data/raw/formatted_transactions.csv \
        --apply-gfp data/processed --apply-preds experiments/E6_tgn/predictions_with_ids.csv

The stable sort renumbers rows that share a timestamp. Two rows are the same transaction
iff every content column is equal; within a group of identical duplicate payments the
k-th old row is paired with the k-th new row. The map is a bijection over all rows and is
written to data/processed/edge_id_remap.parquet (old_edge_id, new_edge_id) with a log.

--apply-gfp rewrites amlworld_gfp_features_{train,val,test}.parquet: EdgeID -> new id and
rows re-sorted into the new split order (they are read positionally by models/tgn.py).
--apply-preds rewrites a predictions_with_ids.csv in place (a *_pre_remap copy is kept next
to it) and asserts from_id/to_id/Timestamp still agree with the new CSV.
--dry-run maps the first 1% of rows only and writes nothing but the log.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from preprocessing.account_bank import load_paths  # noqa: E402

CONTENT = ["from_id", "to_id", "Timestamp", "Amount Sent", "Sent Currency",
           "Amount Received", "Received Currency", "Payment Format", "Is Laundering"]
DRY_RUN_FRAC = 0.01


def build_remap(old_csv: Path, new_csv: Path, nrows: int | None = None) -> pd.DataFrame:
    old = pd.read_csv(old_csv, nrows=nrows)
    new = pd.read_csv(new_csv, nrows=nrows)
    assert list(old.columns) == list(new.columns) == ["EdgeID"] + CONTENT, old.columns.tolist()
    if nrows is not None:  # prefix dry run: keep only complete timestamp groups in both files
        t_cut = min(old["Timestamp"].max(), new["Timestamp"].max())
        old = old[old["Timestamp"] < t_cut]
        new = new[new["Timestamp"] < t_cut]
    assert len(old) == len(new), (len(old), len(new))
    old = old.sort_values("EdgeID"); new = new.sort_values("EdgeID")
    old["_k"] = old.groupby(CONTENT, sort=False).cumcount()
    new["_k"] = new.groupby(CONTENT, sort=False).cumcount()
    m = old[["EdgeID"] + CONTENT + ["_k"]].merge(
        new[["EdgeID"] + CONTENT + ["_k"]], on=CONTENT + ["_k"], how="outer",
        suffixes=("_old", "_new"), validate="one_to_one", indicator=True)
    n_bad = int((m["_merge"] != "both").sum())
    assert n_bad == 0, f"{n_bad} rows could not be paired between old and new CSV"
    remap = (m[["EdgeID_old", "EdgeID_new"]].rename(columns={"EdgeID_old": "old_edge_id", "EdgeID_new": "new_edge_id"})
             .sort_values("old_edge_id").reset_index(drop=True).astype("int64"))
    assert remap["old_edge_id"].is_unique and remap["new_edge_id"].is_unique
    return remap


def apply_gfp(processed_dir: Path, remap: pd.DataFrame, new_csv: Path) -> dict:
    """Re-key the GFP parquets and re-sort them into the new split (EdgeID) order."""
    old_to_new = remap.set_index("old_edge_id")["new_edge_id"]
    new_ids = pd.read_csv(new_csv, usecols=["EdgeID"])["EdgeID"]
    out = {}
    for split in ("train", "val", "test"):
        p = processed_dir / f"amlworld_gfp_features_{split}.parquet"
        gfp = pd.read_parquet(p)
        assert "EdgeID" in gfp.columns, p
        mapped = old_to_new.reindex(gfp["EdgeID"].values)
        assert not mapped.isna().any(), f"{p}: EdgeIDs not in remap"
        gfp["EdgeID"] = mapped.values.astype("int64")
        gfp = gfp.sort_values("EdgeID").reset_index(drop=True)
        # the split parquet, once regenerated, lists exactly these ids in this order
        sp = processed_dir / f"amlworld_{split}.parquet"
        if sp.exists():
            sp_ids = pd.read_parquet(sp, columns=["EdgeID"])["EdgeID"].values
            assert np.array_equal(sp_ids, gfp["EdgeID"].values), f"{p}: order differs from {sp}"
        shutil.copy(p, p.with_name(p.stem + "_pre_remap" + p.suffix)) if not p.with_name(p.stem + "_pre_remap" + p.suffix).exists() else None
        gfp.to_parquet(p, index=False)
        out[split] = {"rows": int(len(gfp)), "n_changed_ids": int((remap.set_index("new_edge_id").loc[gfp["EdgeID"], "old_edge_id"].values != gfp["EdgeID"].values).sum())}
    return out


def apply_preds(preds_csv: Path, remap: pd.DataFrame, new_csv: Path) -> dict:
    old_to_new = remap.set_index("old_edge_id")["new_edge_id"]
    preds = pd.read_csv(preds_csv)
    mapped = old_to_new.reindex(preds["EdgeID"].values)
    assert not mapped.isna().any(), "prediction EdgeIDs not in remap"
    n_changed = int((mapped.values != preds["EdgeID"].values).sum())
    preds["EdgeID"] = mapped.values.astype("int64")
    # from_id / to_id must agree with the new CSV row (Timestamp is the CSV basis - 10 s)
    new = pd.read_csv(new_csv, usecols=["EdgeID", "from_id", "to_id", "Timestamp"]).set_index("EdgeID")
    ref = new.loc[preds["EdgeID"].values]
    assert (ref["from_id"].values == preds["from_id"].values).all()
    assert (ref["to_id"].values == preds["to_id"].values).all()
    off = np.unique(ref["Timestamp"].values - preds["Timestamp"].values)
    assert len(off) == 1, off
    backup = preds_csv.with_name(preds_csv.stem + "_pre_remap" + preds_csv.suffix)
    if not backup.exists():
        shutil.copy(preds_csv, backup)
    preds.sort_values("EdgeID").to_csv(preds_csv, index=False)
    return {"rows": int(len(preds)), "n_changed_ids": n_changed, "timestamp_offset": int(off[0]),
            "backup": str(backup)}


def main(argv=None):
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", type=Path, required=True, help="formatted_transactions.csv before the change")
    ap.add_argument("--new", type=Path, default=paths["raw_dir"] / "formatted_transactions.csv")
    ap.add_argument("--out", type=Path, default=paths["processed_dir"] / "edge_id_remap.parquet")
    ap.add_argument("--apply-gfp", type=Path, default=None, help="processed dir whose GFP parquets to re-key")
    ap.add_argument("--apply-preds", type=Path, nargs="*", default=[], help="predictions_with_ids.csv files to re-key")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    nrows = None
    if args.dry_run:
        with open(args.new, "rb") as f:
            n_total = sum(ch.count(b"\n") for ch in iter(lambda: f.read(1 << 24), b"")) - 1
        nrows = max(1, int(DRY_RUN_FRAC * n_total))
    remap = build_remap(args.old, args.new, nrows=nrows)
    n_changed = int((remap["old_edge_id"] != remap["new_edge_id"]).sum())
    log = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "old_csv": str(args.old), "new_csv": str(args.new), "dry_run": args.dry_run,
           "n_rows": int(len(remap)), "n_changed_ids": n_changed,
           "fraction_changed": n_changed / len(remap)}
    print(f"[remap_edge_ids] {len(remap):,} rows, {n_changed:,} ids changed ({log['fraction_changed']:.1%})")
    if args.dry_run:
        print(json.dumps(log, indent=2))
        return remap
    args.out.parent.mkdir(parents=True, exist_ok=True)
    remap.to_parquet(args.out, index=False)
    if args.apply_gfp:
        log["gfp"] = apply_gfp(args.apply_gfp, remap, args.new)
        print(f"  GFP re-keyed: {log['gfp']}")
    for p in args.apply_preds:
        log.setdefault("preds", {})[str(p)] = apply_preds(p, remap, args.new)
        print(f"  predictions re-keyed: {p} {log['preds'][str(p)]}")
    Path(str(args.out) + ".log.json").write_text(json.dumps(log, indent=2))
    return remap


if __name__ == "__main__":
    main()
