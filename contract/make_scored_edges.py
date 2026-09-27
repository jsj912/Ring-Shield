"""Build the scored_edges contract parquet from a predictions_with_ids.csv (Step 1) or, since
Step 3c, from a calibrated models/score.py scores parquet.

Usage (PowerShell):

    python contract/make_scored_edges.py ^
        --preds experiments/E6_tgn/predictions_with_ids.csv ^
        --model-id gine --seed 1

    python contract/make_scored_edges.py ^
        --scores experiments/R1_gine_causal/scores_test_seed1.parquet --split test ^
        --model-id gine_causal --seed 1 --k-from experiments/R2_b0/gine_causal/seed1/config.yaml

The --scores form (Step 3c) joins the split parquet (edge attributes, banks) with the scores
file, requires a `score_calibrated` column (models/calibrate.py must have run), sets
is_seed from the seed-fraction rule in configs/threshold_rule.yaml (strict quantile on
score_raw within the split at k* = --seed-frac-pct, or the chosen cell of a
ringshield/run_rings.py config given with --k-from), and writes exactly SCORED_EDGES_COLUMNS
(no labels; labels_<split>.parquet come from contract/make_labels.py).

Defaults for --test-parquet, --accounts-csv, --raw-trans-csv and --out come from
configs/paths.yaml. Add --dry-run to process a deterministic 1% sample of the
prediction rows (sampled with random_state=--seed).

Outputs:
    <out>                    scored_edges parquet (columns / order: contract/schema.py)
    <out>.log.json           row counts, NaN count, timestamp offset, inputs, git commit
    <out_dir>/labels_test.parquet   edge_id, true_label  -- internal only (PR-50); with
                             --dry-run it is written as labels_test_dryrun.parquet

The account -> bank map comes from preprocessing/account_bank.py
(paths.yaml:account_bank_map, built on first use).
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

from preprocessing.account_bank import (bank_of_series, load_account_bank_map,  # noqa: E402,F401
                                        load_paths, raw_file)
from contract.schema import (  # noqa: E402
    LABELS_COLUMNS,
    LABELS_ORDER,
    PREDICTIONS_WITH_IDS_COLUMNS,
    SCORED_EDGES_COLUMNS,
    SCORED_EDGES_ORDER,
    TEST_PARQUET_RENAMES,
    pandas_dtypes,
)

DRY_RUN_FRAC = 0.01


# `load_paths` used to be defined here as a second copy, which meant the ten modules importing it
# from this file did NOT honour $RINGSHIELD_PATHS and resolved the `dataset` key as a path. It is now
# re-exported from the single definition in preprocessing/account_bank.py; the import site
# `from contract.make_scored_edges import load_paths` still works unchanged. (Step 11, 2026-09-27)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def write_log(out_path: Path, log: dict) -> Path:
    log = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "git_commit": git_commit(), **log}
    p = Path(str(out_path) + ".log.json")
    with open(p, "w") as f:
        json.dump(log, f, indent=2)
    return p


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
    labels_path: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Convert predictions_with_ids.csv + test parquet into the scored_edges contract.

    Also writes labels_test.parquet (edge_id, true_label) next to out_path.
    Returns the log dict that is also written to <out_path>.log.json.
    """
    preds_csv, test_parquet, accounts_csv, out_path = map(Path, (preds_csv, test_parquet, accounts_csv, out_path))
    paths = load_paths()
    raw_trans_csv = Path(raw_trans_csv) if raw_trans_csv else raw_file("_Trans.csv", paths)
    account_map_cache = Path(account_map_cache) if account_map_cache else paths["account_bank_map"]
    labels_path = Path(labels_path) if labels_path else out_path.parent / (
        "labels_test_dryrun.parquet" if dry_run else "labels_test.parquet")
    expected_offset = int(paths["legacy_csv_time_offset_s"])

    # 1. predictions ---------------------------------------------------------
    preds = pd.read_csv(preds_csv)
    assert list(preds.columns) == PREDICTIONS_WITH_IDS_COLUMNS, (
        f"unexpected predictions columns {list(preds.columns)}; expected {PREDICTIONS_WITH_IDS_COLUMNS}")
    assert preds["EdgeID"].is_unique, "EdgeID is not unique in predictions"
    n_in = len(preds)
    if dry_run:
        preds = preds.sample(frac=DRY_RUN_FRAC, random_state=seed).sort_values("EdgeID").reset_index(drop=True)

    # 2. join on EdgeID ------------------------------------------------------
    test_cols = ["EdgeID", "from_id", "to_id", "Is Laundering"] + [
        c for c in TEST_PARQUET_RENAMES if c != "EdgeID"]
    test = pd.read_parquet(test_parquet, columns=test_cols)
    assert test["EdgeID"].is_unique, "EdgeID is not unique in test parquet"
    m = preds.merge(test, on="EdgeID", how="left", suffixes=("", "_test"), validate="one_to_one")
    n_unmatched = int(m["from_id_test"].isna().sum())
    assert n_unmatched == 0, f"{n_unmatched} prediction EdgeIDs not found in {test_parquet}"
    assert (m["from_id"] == m["from_id_test"]).all(), "from_id disagrees between predictions and test parquet"
    assert (m["to_id"] == m["to_id_test"]).all(), "to_id disagrees between predictions and test parquet"
    # The model script re-based Timestamp to df.Timestamp.min(); the loader re-based to
    # (first day 00:00 - 10 s). The two differ by one global constant (paths.yaml).
    ts_offset = (m["Timestamp_test"] - m["Timestamp"]).unique()
    assert len(ts_offset) == 1, (
        f"Timestamp offset between predictions and test parquet is not constant: {ts_offset[:5]}")
    ts_offset = int(ts_offset[0])
    assert ts_offset == expected_offset, (
        f"observed timestamp offset {ts_offset}s != configs/paths.yaml legacy_csv_time_offset_s={expected_offset}")
    assert (m["true_label"] == m["Is Laundering"]).all(), "true_label disagrees with 'Is Laundering'"

    # 3. banks ----------------------------------------------------------------
    amap = load_account_bank_map(account_map_cache, raw_trans_csv=raw_trans_csv, accounts_csv=accounts_csv)
    bank_of = bank_of_series(amap)
    m["from_bank"] = bank_of.reindex(m["from_id"].values).values
    m["to_bank"] = bank_of.reindex(m["to_id"].values).values
    assert not m["from_bank"].isna().any() and not m["to_bank"].isna().any(), (
        "account id missing from account->bank map")
    m["tenant_id"] = m["from_bank"]

    # 4. renames --------------------------------------------------------------
    m = m.drop(columns=["Timestamp", "from_id_test", "to_id_test", "Is Laundering"]).rename(
        columns={**TEST_PARQUET_RENAMES, "Timestamp_test": "timestamp"})

    # 5./6. scores -------------------------------------------------------------
    nan_mask = m["pred_prob"].isna()
    n_nan = int(nan_mask.sum())
    m["score_raw"] = m["pred_prob"].astype("float64")
    m["score_calibrated"] = m["score_raw"]  # Step 3 replaces this
    m["is_seed"] = (m["predicted_label"] == 1) & ~nan_mask
    m["model_id"] = model_id
    m["seed"] = seed

    # 7. write ------------------------------------------------------------------
    out = m[SCORED_EDGES_ORDER].astype(pandas_dtypes(SCORED_EDGES_COLUMNS))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    labels = m[LABELS_ORDER].astype(pandas_dtypes(LABELS_COLUMNS))
    labels.to_parquet(labels_path, index=False)

    log = {
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
        "n_true_label_positive": int(labels["true_label"].sum()),
        "timestamp_offset_seconds": ts_offset,
        "columns": SCORED_EDGES_ORDER,
        "out_path": str(out_path),
        "labels_path": str(labels_path),
    }
    write_log(out_path, log)
    print(f"[make_scored_edges] wrote {len(out):,} rows -> {out_path}  "
          f"(NaN pred_prob kept: {n_nan}, is_seed: {log['n_is_seed']}, ts offset: {ts_offset}s); "
          f"labels -> {labels_path}")
    return log


def make_scored_edges_from_scores(scores_parquet: Path, split: str, model_id: str, seed: int, out_path: Path,
                                  *, seed_frac_pct: float, k_source: str, dry_run: bool = False) -> dict:
    """Step 3c: contract parquet from a calibrated scores parquet + the seed-fraction rule."""
    import yaml
    from ringshield.aggregators.cc import seed_mask_for_pct, threshold_for_pct
    from ringshield.scored_edges import build_scored_edges
    scores_parquet, out_path = Path(scores_parquet), Path(out_path)
    sc_cols = pd.read_parquet(scores_parquet).columns
    assert "score_calibrated" in sc_cols, f"{scores_parquet}: no score_calibrated column -- run models/calibrate.py first"
    se = build_scored_edges(scores_parquet, split, model_id=model_id, seed=seed)
    if dry_run:
        se = se.sample(frac=DRY_RUN_FRAC, random_state=seed).sort_values("edge_id").reset_index(drop=True)
    rule = yaml.safe_load((REPO_ROOT / "configs" / "threshold_rule.yaml").read_text(encoding="utf-8"))
    assert rule.get("cut") == "strict" and rule.get("selection_column") == "score_raw", rule
    raw = se["score_raw"].to_numpy(float)
    q = threshold_for_pct(raw, seed_frac_pct)
    se["is_seed"] = seed_mask_for_pct(raw, seed_frac_pct)
    n_nan = int(np.isnan(raw).sum())
    assert not se["score_calibrated"].isna().any(), "NaN in score_calibrated"
    assert n_nan == 0, f"{n_nan} NaN score_raw rows: the seed-mask fix should have removed them"
    assert "true_label" not in se.columns
    out = se[SCORED_EDGES_ORDER].astype(pandas_dtypes(SCORED_EDGES_COLUMNS))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    log = {"model_id": model_id, "seed": seed, "split": split, "dry_run": dry_run,
           "inputs": {"scores_parquet": str(scores_parquet), "split_parquet": f"amlworld_{split}.parquet",
                      "threshold_rule": "configs/threshold_rule.yaml", "k_source": k_source},
           "seed_rule": {"seed_frac_pct": seed_frac_pct, "cut": "strict (score_raw > q)", "q": q,
                         "quantile_scope": "this split", "n_on_boundary": int((raw == q).sum())},
           "n_rows_out": int(len(out)), "n_nan_score_raw": n_nan, "n_nan_score_calibrated": 0,
           "n_is_seed": int(out["is_seed"].sum()), "calibrated": bool(not out["score_calibrated"].equals(out["score_raw"])),
           "columns": SCORED_EDGES_ORDER, "out_path": str(out_path)}
    write_log(out_path, log)
    print(f"[make_scored_edges] wrote {len(out):,} rows -> {out_path}  (is_seed: {log['n_is_seed']:,} at "
          f"{seed_frac_pct}% [q={q:.6f}, {log['seed_rule']['n_on_boundary']} tied], NaN 0)")
    return log


def main(argv=None):
    paths = load_paths()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preds", type=Path, default=None, help="predictions_with_ids.csv (Step 1 form)")
    ap.add_argument("--scores", type=Path, default=None, help="calibrated models/score.py scores parquet (Step 3c form)")
    ap.add_argument("--split", choices=["val", "test"], default="test", help="--scores form: which split the file scores")
    ap.add_argument("--seed-frac-pct", type=float, default=None, help="--scores form: k* (top %% of edges are seeds)")
    ap.add_argument("--k-from", type=Path, default=None,
                    help="--scores form: a ringshield/run_rings.py config.yaml; k* = its chosen seed_frac_pct")
    ap.add_argument("--model-id", required=True, help="e.g. gine")
    ap.add_argument("--seed", type=int, required=True, help="seed the predictions were produced with")
    ap.add_argument("--test-parquet", type=Path, default=paths["processed_dir"] / "amlworld_test.parquet")
    ap.add_argument("--accounts-csv", type=Path, default=raw_file("_accounts.csv", paths))
    ap.add_argument("--raw-trans-csv", type=Path, default=raw_file("_Trans.csv", paths))
    ap.add_argument("--out", type=Path, default=None,
                    help="default contract/out/scored_edges_<model>_<seed>.parquet")
    ap.add_argument("--dry-run", action="store_true", help=f"process a {DRY_RUN_FRAC:.0%} sample of rows")
    args = ap.parse_args(argv)

    suffix = "_dryrun" if args.dry_run else ""
    out = args.out or (REPO_ROOT / "contract" / "out" / f"scored_edges_{args.model_id}_{args.seed}{suffix}.parquet")
    if args.scores is not None:
        if args.seed_frac_pct is None:
            assert args.k_from is not None, "--scores needs --seed-frac-pct or --k-from"
            import yaml
            cfg = yaml.safe_load(Path(args.k_from).read_text(encoding="utf-8"))
            k, k_src = float(cfg["chosen"]["seed_frac_pct"]), f"{args.k_from} (chosen on val)"
        else:
            k, k_src = float(args.seed_frac_pct), "--seed-frac-pct"
        make_scored_edges_from_scores(args.scores, args.split, args.model_id, args.seed, out,
                                      seed_frac_pct=k, k_source=k_src, dry_run=args.dry_run)
        return
    assert args.preds is not None, "give --preds (Step 1 form) or --scores (Step 3c form)"
    make_scored_edges(args.preds, args.test_parquet, args.accounts_csv, args.model_id, args.seed, out,
                      raw_trans_csv=args.raw_trans_csv, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
