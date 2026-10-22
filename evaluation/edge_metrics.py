"""Edge-level metrics for a scoring run (Step 3b.5).

    python evaluation/edge_metrics.py --run-dir experiments/R1_gine_causal --seeds 1 2 3 4 5
    python evaluation/edge_metrics.py --run-dir experiments/R1_gine_noncausal --seeds 1 42 123
    python evaluation/edge_metrics.py --table   # rebuild results/tables/r1_edge_metrics.csv from all runs

Per run, per seed, per evaluation block -- `val` (the validation split) and the test windows
of configs/eval_window.yaml (`primary` = test days 8-9, `tail` = days 10-17, `whole` = the
full split; Step 3b-w, docs/TEST_TAIL.md): minority F1 / precision / recall at the
VALIDATION-chosen threshold, average precision, MCC, ROC-AUC, precision@500/1000/2000, and
two prevalence-free columns so detector rows stay comparable across splits whose base rates
differ (val 0.107 %, test 0.186 %): `ap_over_prevalence` = AP / positive rate (lift of the
PR-AUC over a random ranker) and `precision_at_recall_50` = the highest precision on the PR
curve at recall >= 0.5. The threshold is chosen per seed on the val scores by the same sweep
models/tgn.py uses (np.arange(0.05, 0.95, 0.01), max minority F1) and then applied
unchanged to test.

Labels come from contract/out/labels_<split>.parquet (contract/make_labels.py), never from
a scores file. Scores come from <run-dir>/scores_<split>_seed<S>.parquet (models/score.py).
Every score row must have a label and vice versa; zero NaN.

Aggregation over seeds (the unit of replication): mean, sample std (ddof=1) and a 95%
percentile bootstrap CI of the mean over seeds (B=10,000, seed 0). With 3 seeds the CI is
coarse and is reported as such. Writes <run-dir>/metrics.json and replaces the run's row in
results/tables/r1_edge_metrics.csv: ONE row per run, columns label / sampler / feature_set
and val_* / test_* metric aggregates (Step 3b-z layout). --feature-set tags metrics.json
(`trailing_closescycle` = GFP parquets regenerated in Step 3b-z, `legacy_forwardcycle` =
the pre-3b-z parquets); --label overrides the derived row label
(causal | causal_legacyfeat | noncausal_legacyfeat ...). Calibration is Step 3c and is not
touched here.
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
from sklearn.metrics import (average_precision_score, f1_score, matthews_corrcoef, precision_recall_curve,
                             precision_score, recall_score, roc_auc_score)

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

LABELS_DIR = REPO_ROOT / "contract" / "out"
TABLE = REPO_ROOT / "results" / "tables" / "r1_edge_metrics.csv"
SPLITS = ("val", "test")
K_LIST = (500, 1000, 2000)
from ringshield.windows import load_windows  # noqa: E402

WINDOWS = load_windows()                      # val, primary, tail, whole (report order)
BLOCKS = list(WINDOWS)                        # evaluation blocks; "val" is the whole val split
RECALL_FIXED = 0.5
THRESH_GRID = np.arange(0.05, 0.95, 0.01)
METRICS = ["f1_minority", "precision_minority", "recall_minority", "average_precision", "ap_over_prevalence",
           "precision_at_recall_50", "mcc", "roc_auc"] + [f"precision_at_{k}" for k in K_LIST]
BOOT_B, BOOT_SEED = 10_000, 0
FEATURE_SETS = ("trailing_closescycle", "legacy_forwardcycle")
FEATURE_SET_DEFAULT = "trailing_closescycle"


def sampler_name(cfg: dict) -> str:
    if not cfg.get("causal_sampling"):
        return "non-causal"
    w = cfg.get("loader_window_s")
    return f"causal_{cfg.get('loader_route', 'fallback')}_W{w}" if w else f"causal_{cfg.get('loader_route', '?')}"


def derive_label(cfg: dict, feature_set: str) -> str:
    base = "causal" if cfg.get("causal_sampling") else "noncausal"
    return base + ("_legacyfeat" if feature_set.startswith("legacy") else "")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def load_scores_with_labels(run_dir: Path, seed: int, split: str, labels_dir: Path = LABELS_DIR,
                            suffix: str = "") -> pd.DataFrame:
    sc = pd.read_parquet(run_dir / f"scores_{split}_seed{seed}{suffix}.parquet")
    lab = pd.read_parquet(labels_dir / f"labels_{split}{suffix}.parquet")
    assert list(sc.columns)[:3] == ["edge_id", "timestamp", "score_raw"] and         set(sc.columns) <= {"edge_id", "timestamp", "score_raw", "score_calibrated"}, sc.columns.tolist()
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


def precision_at_recall(y: np.ndarray, s: np.ndarray, r: float = RECALL_FIXED) -> float:
    """Highest precision on the PR curve at recall >= r (threshold-free, prevalence-insensitive)."""
    p, rc, _ = precision_recall_curve(y, s)
    return float(p[rc >= r].max())


def metrics_at(y: np.ndarray, s: np.ndarray, thr: float) -> dict:
    pred = (s >= thr).astype(int)
    prevalence = float(y.mean())
    ap = float(average_precision_score(y, s))
    out = {
        "f1_minority": float(f1_score(y, pred, pos_label=1, zero_division=0)),
        "precision_minority": float(precision_score(y, pred, pos_label=1, zero_division=0)),
        "recall_minority": float(recall_score(y, pred, pos_label=1, zero_division=0)),
        "average_precision": ap,
        "prevalence": prevalence,
        "ap_over_prevalence": ap / prevalence if prevalence else float("nan"),
        "precision_at_recall_50": precision_at_recall(y, s, RECALL_FIXED),
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


def evaluate_run(run_dir: Path, seeds: list[int], labels_dir: Path = LABELS_DIR, suffix: str = "",
                 feature_set: str = FEATURE_SET_DEFAULT, label: str | None = None) -> dict:
    run_dir = Path(run_dir)
    per_seed = {b: {} for b in BLOCKS}
    thresholds = {}
    for seed in seeds:
        val = load_scores_with_labels(run_dir, seed, "val", labels_dir, suffix)
        thr, val_f1 = choose_threshold(val["true_label"].values, val["score_raw"].values)
        thresholds[seed] = {"threshold": thr, "val_f1_at_threshold": val_f1}
        test = load_scores_with_labels(run_dir, seed, "test", labels_dir, suffix)
        for block, w in WINDOWS.items():
            df = val if w.split == "val" else test
            m = w.mask(df["timestamp"].values)
            if w.split == "val" and not m.all():
                m = np.ones(len(df), dtype=bool)  # the val block is the whole val split (dry-run samples included)
            per_seed[block][seed] = {"seed": seed, "threshold": thr, "window": w.as_dict(),
                                     **metrics_at(df["true_label"].values[m], df["score_raw"].values[m], thr)}
        v, t, u = per_seed["val"][seed], per_seed["primary"][seed], per_seed["whole"][seed]
        print(f"  seed {seed}: thr {thr:.2f} | val F1 {v['f1_minority']:.4f} AP {v['average_precision']:.4f} "
              f"AP/prev {v['ap_over_prevalence']:.0f} P@R50 {v['precision_at_recall_50']:.3f} | "
              f"PRIMARY F1 {t['f1_minority']:.4f} AP {t['average_precision']:.4f} AP/prev {t['ap_over_prevalence']:.0f} "
              f"P@R50 {t['precision_at_recall_50']:.3f} AUC {t['roc_auc']:.4f} | whole F1 {u['f1_minority']:.4f} "
              f"AP {u['average_precision']:.4f} | tail F1 {per_seed['tail'][seed]['f1_minority']:.4f}")

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
        "label": label or derive_label(cfg, feature_set),
        "sampler": sampler_name(cfg), "feature_set": feature_set,
        "threshold_rule": "per seed, argmax minority-F1 over np.arange(0.05, 0.95, 0.01) on the VAL scores; "
                          "applied unchanged to test",
        "labels": {s: str(labels_dir / f"labels_{s}.parquet") for s in SPLITS},
        "eval_windows": {b: w.as_dict() for b, w in WINDOWS.items()},
        "blocks": BLOCKS, "primary_block": "primary",
        "aggregation": "mean, sample std (ddof=1), 95% percentile bootstrap CI of the mean over seeds "
                       f"(B={BOOT_B}, rng seed {BOOT_SEED}); seeds are the unit",
        "run_config": {k: cfg.get(k) for k in ("causal_sampling", "loader_route", "loader_window_s", "adaptations",
                                                 "num_neighbors", "n_hidden", "git_commit")},
        "score_logs": score_logs,
        "thresholds": thresholds,
        "per_seed": {b: [per_seed[b][seed] for seed in seeds] for b in BLOCKS},
        "aggregate": {b: aggregate([per_seed[b][seed] for seed in seeds]) for b in BLOCKS},
    }
    out = run_dir / f"metrics{suffix}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[edge_metrics] {run_dir.name}: wrote {out}")
    return result


def table_row(result: dict) -> dict:
    """One row per run: label / sampler / feature set, then one column group per block
    (val_*, primary_*, tail_*, whole_*)."""
    cfg = result.get("run_config", {})
    feature_set = result.get("feature_set", "unknown")
    row = {"label": result.get("label") or derive_label(cfg, feature_set),
           "run": result["run"],
           "sampler": result.get("sampler") or sampler_name(cfg),
           "feature_set": feature_set,
           "n_seeds": result["aggregate"]["primary"]["n_seeds"],
           "seeds": " ".join(str(s) for s in result["seeds"]),
           "threshold_mean": float(np.mean([t["threshold"] for t in result["thresholds"].values()]))}
    for block in result.get("blocks", BLOCKS):
        agg = result["aggregate"][block]
        for m in METRICS:
            for stat in ("mean", "std", "ci95_lo", "ci95_hi"):
                row[f"{block}_{m}_{stat}"] = agg[m][stat]
    return row


LABEL_ORDER = ["noncausal_legacyfeat", "causal_legacyfeat", "causal"]


def update_table(results: list[dict], table: Path = TABLE) -> pd.DataFrame:
    new = pd.DataFrame([table_row(res) for res in results])
    if table.exists():
        old = pd.read_csv(table)
        if "label" in old.columns and "split" not in old.columns:      # same layout: keep other runs
            old = old[~old["run"].isin(new["run"])]
            new = pd.concat([old, new], ignore_index=True)
        # else: pre-3b-z per-split layout -> rebuilt from scratch by the caller (--table)
    order = {l: i for i, l in enumerate(LABEL_ORDER)}
    new = new.assign(_o=new["label"].map(lambda l: order.get(l, len(order)))).sort_values(["_o", "label"]) \
             .drop(columns="_o").reset_index(drop=True)
    table.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(table, index=False)
    print(f"[edge_metrics] table -> {table} ({len(new)} rows: {', '.join(new['label'])})")
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, nargs="*", default=[])
    ap.add_argument("--seeds", type=int, nargs="*", default=None,
                    help="default: every scores_test_seed*.parquet in the run dir")
    ap.add_argument("--labels-dir", type=Path, default=LABELS_DIR)
    ap.add_argument("--table", action="store_true", help="also rebuild the table from every run's metrics.json")
    ap.add_argument("--dry-run", action="store_true", help="use *_dryrun score/label files")
    ap.add_argument("--no-table", action="store_true",
                    help="write metrics.json only; leave results/tables/r1_edge_metrics.csv untouched "
                         "(sensitivity / side runs)")
    ap.add_argument("--feature-set", choices=FEATURE_SETS, default=FEATURE_SET_DEFAULT,
                    help="which GFP parquets the scored checkpoints were trained / scored with (tag in metrics.json)")
    ap.add_argument("--label", default=None, help="row label override (default derived from sampler + feature set)")
    args = ap.parse_args(argv)
    results = []
    for rd in args.run_dir:
        seeds = args.seeds or sorted(int(p.stem.split("seed")[-1].replace("_dryrun", ""))
                                     for p in rd.glob("scores_test_seed*.parquet")
                                     if ("dryrun" in p.stem) == args.dry_run)
        assert seeds, f"no scores in {rd}"
        print(f"[edge_metrics] {rd.name} seeds {seeds}")
        results.append(evaluate_run(rd, seeds, args.labels_dir, "_dryrun" if args.dry_run else "",
                                    feature_set=args.feature_set, label=args.label))
    if args.table:
        for p in (REPO_ROOT / "experiments").glob("R1_*/metrics.json"):
            j = json.loads(p.read_text(encoding="utf-8"))
            if j.get("run") not in {r["run"] for r in results} and "aggregate" in j:
                assert "feature_set" in j and "primary" in j.get("aggregate", {}), \
                    f"{p}: metrics.json predates --feature-set / eval windows; re-run edge_metrics on it"
                results.append(j)
        if TABLE.exists():
            TABLE.unlink()  # --table rebuilds the whole file from every R1_*/metrics.json
    if results and not args.dry_run and not args.no_table:
        update_table(results)


if __name__ == "__main__":
    main()
