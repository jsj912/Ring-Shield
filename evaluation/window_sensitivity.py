"""Step 3b-x (3): scoring-only sensitivity of R1 to the causal fallback window.

    python evaluation/window_sensitivity.py --score            # re-score val+test at W = 60 and 300 s
    python evaluation/window_sensitivity.py --metrics          # edge metrics for the side runs
    python evaluation/window_sensitivity.py --table            # results/tables/r1_window_sensitivity.csv + footnote

The five R1_gine_causal checkpoints are NOT retrained; they are re-scored with
models/score.py --window-s W into experiments/R1x_score_w<W>/ (a side directory, so R1's
own artefacts are untouched; not to be confused with experiments/R1x_gine_causal_w300, the
Step 3b-x training run), then evaluation/edge_metrics.py --no-table gives each side
run its metrics.json with the usual val-tuned threshold. --table joins them with the W = 1,800
row taken from experiments/R1_gine_causal/metrics.json into one per-seed table of val / test
F1 and AP, writes results/tables/r1_window_sensitivity.csv and the footnote file
results/tables/r1_edge_metrics.footnote.md that r1_edge_metrics.csv refers to.
--dry-run passes through to score.py (1% rows; pipeline check only).
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

R1 = REPO_ROOT / "experiments" / "R1_gine_causal_legacyfeat"  # the checkpoints the 3b-x analysis re-scored
SIDE = {60: REPO_ROOT / "experiments" / "R1x_score_w60",
        300: REPO_ROOT / "experiments" / "R1x_score_w300"}  # scoring only; R1x_gine_causal_w300 is the training run
WINDOWS = (60, 300, 1800)
SEEDS = [1, 2, 3, 4, 5]
TABLE = REPO_ROOT / "results" / "tables" / "r1_window_sensitivity.csv"
FOOTNOTE = REPO_ROOT / "results" / "tables" / "r1_edge_metrics.footnote.md"
PY = sys.executable


def run_dir_for(w: int) -> Path:
    return R1 if w == 1800 else SIDE[w]


def write_side_config(w: int, out_dir: Path):
    cfg = yaml.safe_load((R1 / "config.yaml").read_text(encoding="utf-8"))
    cfg.update({"experiment": out_dir.name, "loader_window_s": w,
                "scoring_only": True, "checkpoints_from": R1.name,
                "note": f"Step 3b-x: R1 checkpoints re-scored with --window-s {w}; no training"})
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")


def score(windows, seeds, dry_run: bool):
    for w in windows:
        out_dir = run_dir_for(w)
        assert out_dir != R1, "W = 1,800 s already exists in R1_gine_causal; not re-scored"
        write_side_config(w, out_dir)
        cmd = [PY, "-u", str(REPO_ROOT / "models" / "score.py"), "--run-dir", str(R1), "--seeds",
               *map(str, seeds), "--splits", "val", "test", "--window-s", str(w), "--out-dir", str(out_dir)]
        if dry_run:
            cmd.append("--dry-run")
        print("[window_sensitivity] $", " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def metrics(windows, seeds, dry_run: bool):
    dirs = [str(run_dir_for(w)) for w in windows if w != 1800]
    cmd = [PY, "-u", str(REPO_ROOT / "evaluation" / "edge_metrics.py"), "--run-dir", *dirs, "--seeds",
           *map(str, seeds), "--no-table"]
    if dry_run:
        cmd.append("--dry-run")
    print("[window_sensitivity] $", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def build_table(windows, seeds) -> pd.DataFrame:
    rows = []
    for w in windows:
        m = json.loads((run_dir_for(w) / "metrics.json").read_text(encoding="utf-8"))
        # metrics.json blocks since 3b-w apply: val / primary / tail / whole; this table keeps the
        # whole-split test numbers the 3b-x analysis was written with, plus the primary window
        per = {s: {r["seed"]: r for r in m["per_seed"][s]} for s in ("val", "whole", "primary")}
        per["test"] = per["whole"]
        for seed in seeds:
            if seed not in per["val"]:      # a window may have been capped before every seed was scored
                continue
            v, t = per["val"][seed], per["test"][seed]
            rows.append({"window_s": w, "seed": seed, "threshold": v["threshold"],
                         "val_f1": v["f1_minority"], "val_ap": v["average_precision"],
                         "test_f1": t["f1_minority"], "test_ap": t["average_precision"],
                         "test_auc": t["roc_auc"], "test_p_at_1000": t["precision_at_1000"],
                         "primary_f1": per["primary"][seed]["f1_minority"], "primary_ap": per["primary"][seed]["average_precision"],
                         "run_dir": run_dir_for(w).name, "metrics_created_utc": m["created_utc"]})
    df = pd.DataFrame(rows)
    return df


def markdown(df: pd.DataFrame, windows, seeds) -> str:
    lines = ["| seed | " + " | ".join(f"W={w} val F1 / AP" for w in windows) + " | " +
             " | ".join(f"W={w} test F1 / AP" for w in windows) + " |",
             "|---|" + "---|" * (2 * len(windows))]
    for seed in seeds + ["mean"]:
        cells = []
        for split in ("val", "test"):
            for w in windows:
                d = df[df.window_s == w]
                if seed == "mean":
                    f1, ap = d[f"{split}_f1"].mean(), d[f"{split}_ap"].mean()
                else:
                    r = d[d.seed == seed]
                    if r.empty:
                        cells.append("–")
                        continue
                    f1, ap = r.iloc[0][f"{split}_f1"], r.iloc[0][f"{split}_ap"]
                cells.append(f"{f1:.3f} / {ap:.3f}")
        lines.append(f"| {seed} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--metrics", action="store_true")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--windows", type=int, nargs="+", default=list(WINDOWS))
    ap.add_argument("--seeds", "--seed", dest="seeds", type=int, nargs="+", default=SEEDS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not (args.score or args.metrics or args.table):
        ap.error("give at least one of --score / --metrics / --table")
    side = [w for w in args.windows if w != 1800]
    if args.score:
        score(side, args.seeds, args.dry_run)
    if args.metrics:
        metrics(side, args.seeds, args.dry_run)
    if args.table:
        assert not args.dry_run, "the table is built from full runs only"
        df = build_table(args.windows, args.seeds)
        TABLE.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(TABLE, index=False)
        md = markdown(df, args.windows, args.seeds)
        print(md)
        summary = df.groupby("window_s")[["val_f1", "val_ap", "test_f1", "test_ap"]].agg(["mean", "std"])
        print(summary.round(4).to_string())
        foot = [
            f"# Footnote to r1_edge_metrics.csv — loader_window_s sensitivity (Step 3b-x, "
            f"{datetime.now(timezone.utc).date().isoformat()})", "",
            "test_* columns below are the WHOLE test split (as in the 3b-x analysis); primary_* columns are the "
            "days 8-9 primary window of configs/eval_window.yaml (3b-w). "
            "The `causal_legacyfeat` row in `r1_edge_metrics.csv` was scored with the causal fallback window "
            "W = 1,800 s (`loader_window_s`). The same checkpoints re-scored at W = 60 s and W = 300 s "
            "(scoring only, no retraining; side runs `experiments/R1x_score_w60`, `_w300`; threshold "
            "re-tuned on val per seed as usual) give (W = 60 s was capped at the seeds that had finished; "
            "the mean rows average the seeds present for each window):", "",
            md, "",
            "Mean ± sd over the seeds present (n per window: " +
            ", ".join(f"W={w}: {int((df.window_s == w).sum())}" for w in args.windows) + "):", "",
            "```", summary.round(4).to_string(), "```", "",
            f"Per-seed values: `{TABLE.relative_to(REPO_ROOT).as_posix()}`. Full analysis: `docs/CAUSAL_LEAK.md`.",
        ]
        FOOTNOTE.write_text("\n".join(foot) + "\n", encoding="utf-8")
        print(f"-> {TABLE}\n-> {FOOTNOTE}")


if __name__ == "__main__":
    main()
