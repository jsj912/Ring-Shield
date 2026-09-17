"""Edge-level metrics for a scoring run (Step 3b.5).

    python evaluation/edge_metrics.py --run-dir experiments/R1_gine_causal --seeds 1 2 3 4 5
    python evaluation/edge_metrics.py --run-dir experiments/R1_gine_noncausal --seeds 1 42 123
    python evaluation/edge_metrics.py --table   # rebuild results/tables/r1_edge_metrics.csv from all runs

Per run, per seed, per split (val, test): minority F1 / precision / recall at the
VALIDATION-chosen threshold, average precision, MCC, ROC-AUC, precision@500/1000/2000.
The threshold is chosen per seed on the val scores by the same sweep models/tgn.py uses
(np.arange(0.05, 0.95, 0.01), max minority F1) and then applied unchanged to test.

Labels come from contract/out/labels_<split>.parquet (contract/make_labels.py), never from
a scores file. Scores come from <run-dir>/scores_<split>_seed<S>.parquet (models/score.py).
Every score row must have a label and vice versa; zero NaN.

Aggregation over seeds (the unit of replication): mean, sample std (ddof=1) and a 95%
percentile bootstrap CI of the mean over seeds (B=10,000, seed 0). With 3 seeds the CI is
coarse and is reported as such. Writes <run-dir>/metrics.json and appends / replaces the
run's rows in results/tables/r1_edge_metrics.csv (one row per run x split). Calibration is
Step 3c and is not touched here.
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
from sklearn.metrics import (average_precision_score, f1_score, matthews_corrcoef, precision_score,
                             recall_score, roc_auc_score)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LABELS_DIR = REPO_ROOT / "contract" / "out"
TABLE = REPO_ROOT / "results" / "tables" / "r1_edge_metrics.csv"
SPLITS = ("val", "test")
K_LIST = (500, 1000, 2000)
THRESH_GRID = np.arange(0.05, 0.95, 0.01)
METRICS = ["f1_minority", "precision_minority", "recall_minority", "average_precision", "mcc", "roc_auc"] + \
          [f"precision_at_{k}" for k in K_LIST]
BOOT_B, BOOT_SEED = 10_000, 0


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def load_scores_with_labels(run_dir: Path, seed: int, split: str, labels_dir: Path = LABELS_DIR,
                            suffix: str = "") -> pd.DataFrame:
    sc = pd.read_parquet(run_dir / f"scores_{split}_seed{seed}{suffix}.parquet")
    lab = pd.read_parquet(labels_dir / f"labels_{split}{suffix}.parquet")
    assert list(sc.columns) == ["edge_id", "timestamp", "score_raw"], sc.columns.tolist()
    m = sc.merge(lab, on="edge_id", how="outer", indicator=True, validate="one_to_one")
    n_bad = int((m["_merge"] != "both").sum())
    assert n_bad == 0, f"{run_dir.name} seed {seed} {split}: {n_bad} edges without score or without label"
    assert not m["score_raw"].isna().any(), "NaN score"
    return m.drop(columns="_merge")


def choose_threshold(y: np.ndarray, s: np.ndarray) -> tuple[float, float]:
    """Same sweep as models/tgn.py::tune_threshold, on validation only."""
    best_f1, best_t = 0.0, 0.5
    for t in THRESH_GRID:
        f1 = f1_score(y, (s >= t).astype(int), pos_label=1, zero_division=0)
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t, best_f1


def precision_at_k(y: np.ndarray, s: np.ndarray, k: int) -> float:
    top = np.argsort(-s, kind="stable")[:k]
    return float(y[top].mean())


def metrics_at(y: np.ndarray, s: np.ndarray, thr: float) -> dict:
    pred = (s >= thr).astype(int)
    out = {
        "f1_minority": float(f1_score(y, pred, pos_label=1, zero_division=0)),
        "precision_minority": float(precision_score(y, pred, pos_label=1, zero_division=0)),
        "recall_minority": float(recall_score(y, pred, pos_label=1, zero_division=0)),
        "average_precision": float(average_precision_score(y, s)),
        "mcc": float(matthews_corrcoef(y, pred)),
        "roc_auc": float(roc_auc_score(y, s)),
        "n_edges": int(len(y)), "n_positive": int(y.sum()), "n_predicted_positive": int(pred.sum()),
    }
    for k in K_LIST:
        out[f"precision_at_{k}"] = precision_at_k(y, s, k)
    return out


def bootstrap_ci(values: np.ndarray, b: int = BOOT_B, seed: int = BOOT_SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(values)
    means = values[rng.integers(0, n, size=(b, n))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def aggregate(per_seed: list[dict]) -> dict:
    out = {"n_seeds": len(per_seed)}
    for m in METRICS:
        v = np.array([r[m] for r in per_seed], dtype=float)
        lo, hi = bootstrap_ci(v)
        out[m] = {"mean": float(v.mean()), "std": float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                  "ci95_lo": lo, "ci95_hi": hi, "values": v.tolist()}
    return out


def evaluate_run(run_dir: Path, seeds: list[int], labels_dir: Path = LABELS_DIR, suffix: str = "") -> dict:
    run_dir = Path(run_dir)
    per_seed = {s: {} for s in SPLITS}
    thresholds = {}
    for seed in seeds:
        val = load_scores_with_labels(run_dir, seed, "val", labels_dir, suffix)
        thr, val_f1 = choose_threshold(val["true_label"].values, val["score_raw"].values)
        thresholds[seed] = {"threshold": thr, "val_f1_at_threshold": val_f1}
        for split in SPLITS:
            df = val if split == "val" else load_scores_with_labels(run_dir, seed, split, labels_dir, suffix)
            per_seed[split][seed] = {"seed": seed, "threshold": thr,
                                     **metrics_at(df["true_label"].values, df["score_raw"].values, thr)}
        print(f"  seed {seed}: thr {thr:.2f} | val F1 {per_seed['val'][seed]['f1_minority']:.4f} "
              f"AP {per_seed['val'][seed]['average_precision']:.4f} | test F1 {per_seed['test'][seed]['f1_minority']:.4f} "
              f"AP {per_seed['test'][seed]['average_precision']:.4f} AUC {per_seed['test'][seed]['roc_auc']:.4f} "
              f"P@1000 {per_seed['test'][seed]['precision_at_1000']:.3f}")

    cfg_path = run_dir / "config.yaml"
    cfg = {}
    if cfg_path.exists():
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    score_logs = {}
    for seed in seeds:
        for split in SPLITS:
            p = run_dir / f"scores_{split}_seed{seed}.log.json"
            if p.exists():
                j = json.loads(p.read_text(encoding="utf-8"))
                score_logs[f"{split}_seed{seed}"] = {k: j.get(k) for k in ("causal", "loader_route", "checkpoint",
                                                                          "n_nan_scores", "git_commit")}
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "run": run_dir.name, "run_dir": str(run_dir), "seeds": seeds,
        "threshold_rule": "per seed, argmax minority-F1 over np.arange(0.05, 0.95, 0.01) on the VAL scores; "
                          "applied unchanged to test",
        "labels": {s: str(labels_dir / f"labels_{s}.parquet") for s in SPLITS},
        "aggregation": "mean, sample std (ddof=1), 95% percentile bootstrap CI of the mean over seeds "
                       f"(B={BOOT_B}, rng seed {BOOT_SEED}); seeds are the unit",
        "run_config": {k: cfg.get(k) for k in ("causal_sampling", "loader_route", "loader_window_s", "adaptations",
                                                 "num_neighbors", "n_hidden", "git_commit")},
        "score_logs": score_logs,
        "thresholds": thresholds,
        "per_seed": {s: [per_seed[s][seed] for seed in seeds] for s in SPLITS},
        "aggregate": {s: aggregate([per_seed[s][seed] for seed in seeds]) for s in SPLITS},
    }
    out = run_dir / f"metrics{suffix}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[edge_metrics] {run_dir.name}: wrote {out}")
    return result


def table_rows(result: dict) -> list[dict]:
    rows = []
    for split in SPLITS:
        agg = result["aggregate"][split]
        row = {"run": result["run"], "split": split, "n_seeds": agg["n_seeds"],
               "causal": result["run_config"].get("causal_sampling"),
               "loader_route": result["run_config"].get("loader_route"),
               "threshold_mean": float(np.mean([t["threshold"] for t in result["thresholds"].values()])),
               "seeds": " ".join(str(s) for s in result["seeds"])}
        for m in METRICS:
            row[f"{m}_mean"] = agg[m]["mean"]
            row[f"{m}_std"] = agg[m]["std"]
            row[f"{m}_ci95_lo"] = agg[m]["ci95_lo"]
            row[f"{m}_ci95_hi"] = agg[m]["ci95_hi"]
        rows.append(row)
    return rows


def update_table(results: list[dict], table: Path = TABLE) -> pd.DataFrame:
    new = pd.DataFrame([r for res in results for r in table_rows(res)])
    if table.exists():
        old = pd.read_csv(table)
        old = old[~old["run"].isin(new["run"])]
        new = pd.concat([old, new], ignore_index=True)
    new = new.sort_values(["run", "split"]).reset_index(drop=True)
    table.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(table, index=False)
    print(f"[edge_metrics] table -> {table} ({len(new)} rows)")
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, nargs="*", default=[])
    ap.add_argument("--seeds", type=int, nargs="*", default=None,
                    help="default: every scores_test_seed*.parquet in the run dir")
    ap.add_argument("--labels-dir", type=Path, default=LABELS_DIR)
    ap.add_argument("--table", action="store_true", help="also rebuild the table from every run's metrics.json")
    ap.add_argument("--dry-run", action="store_true", help="use *_dryrun score/label files")
    args = ap.parse_args(argv)
    results = []
    for rd in args.run_dir:
        seeds = args.seeds or sorted(int(p.stem.split("seed")[-1].replace("_dryrun", ""))
                                     for p in rd.glob("scores_test_seed*.parquet")
                                     if ("dryrun" in p.stem) == args.dry_run)
        assert seeds, f"no scores in {rd}"
        print(f"[edge_metrics] {rd.name} seeds {seeds}")
        results.append(evaluate_run(rd, seeds, args.labels_dir, "_dryrun" if args.dry_run else ""))
    if args.table:
        for p in (REPO_ROOT / "experiments").glob("R1_*/metrics.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("run") not in {r["run"] for r in results} and "aggregate" in j:
                results.append(j)
    if results and not args.dry_run:
        update_table(results)


if __name__ == "__main__":
    main()
