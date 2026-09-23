"""Step 9 driver: evidence for every run, then the CI / p-value / quiet-member / TTD tables.

    python evaluation/step9_tables.py                       # everything
    python evaluation/step9_tables.py --windows primary      # one window, for a quick check

For every method below and every detector seed, the run's `rings.parquet` is re-evaluated on each
evaluation window (val, primary, tail, whole) into a `RingEvidence` record
(`evaluation/ring_stats.py`), and from those:

    results/tables/r9_quiet_members.csv   quiet-member recall per method / window / pattern, with
                                          bootstrap CIs on the primary window (amendment b)
    results/tables/r9_ttd.csv             causal time-to-detection, median / IQR, primary window
    results/tables/r9_significance.csv    the five pre-registered comparisons: mean delta, CI,
                                          raw p and Holm-adjusted p (amendments c, f)
    results/tables/r{2,3,4,5}_*_ci.csv    bootstrap CIs for every row of every ring table (d)
    results/tables/r{2,3,4}_*_appendix.csv  the same rows at Jaccard 0.3 and 0.7 (item 5)
    results/tables/r{3,4}_*_pvalues.csv   per-table companions of the significance table

Methods (each maps to a directory of <seed>/rings.parquet plus the scores that built it):
    b0            experiments/R2_b0/gine_causal        cc at k*
    gfpxgb        experiments/R2_b0/gfpxgb             cc at k* on the GFP+XGBoost scores
    density       experiments/R2_b0/density            cc at k* on the density proxy
    b1 / b1b      experiments/R3_expansion/runs/...    expansion rule baselines
    proposed      experiments/R3_expansion/runs/proposed   expansion policy (expand + cc)
    <ablations>   experiments/R3_expansion/runs/...
    b2..average   experiments/R4_partition/runs/...    partition methods on the same subgraph
    full          experiments/R4_partition/runs/average    the shipped pipeline (alias)
    cc_partition  experiments/R4_sweep/cc_partition    partition without expansion
    b5            experiments/R4_partition/runs/b5     CSGM (one run, no detector seed)

Nothing is chosen here: every run already fixed its parameters on val in its own step.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_stats import (RATE_METRICS, bootstrap_over_rings, holm, metrics_from_evidence,  # noqa: E402
                                   paired_permutation, quiet_member_recall_per_pattern, ring_evidence,
                                   time_to_detection)
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.rings import Ring, read_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R2 = REPO_ROOT / "experiments" / "R2_b0"
R3 = REPO_ROOT / "experiments" / "R3_expansion" / "runs"
R4 = REPO_ROOT / "experiments" / "R4_partition" / "runs"
SWEEP = REPO_ROOT / "experiments" / "R4_sweep"
TABLES = REPO_ROOT / "results" / "tables"

# method -> (runs dir, scores template, table it belongs to)
METHODS = {
    "b0": (R2 / "gine_causal", "gine", "r2"),
    "gfpxgb": (R2 / "gfpxgb", "gfpxgb", "r2"),
    "density": (R2 / "density", "density", "r2"),
    "b1": (R3 / "b1", "gine", "r3"),
    "b1b": (R3 / "b1b", "gine", "r3"),
    "proposed": (R3 / "proposed", "gine", "r3"),
    "no_detector": (R3 / "no_detector", "gine", "r3"),
    "no_account_state": (R3 / "no_account_state", "gine", "r3"),
    "no_embedding": (R3 / "no_embedding", "gine", "r3"),
    "hop1": (R3 / "hop1", "gine", "r3"),
    "b2": (R4 / "b2", "gine", "r4"),
    "b3": (R4 / "b3", "gine", "r4"),
    "b4": (R4 / "b4", "gine", "r4"),
    "pivot": (R4 / "pivot", "gine", "r4"),
    "average": (R4 / "average", "gine", "r4"),
    "b5": (R4 / "b5", "gine", "r4"),
    "cc_partition": (SWEEP / "cc_partition", "gine", "r4"),
}
FULL_ALIAS = "average"          # the shipped pipeline: expansion + partition at the val-chosen cut
COMPARISONS = [("proposed_vs_b1b", "proposed", "b1b"), ("proposed_vs_b0", "proposed", "b0"),
               ("full_vs_b2", FULL_ALIAS, "b2"), ("cc_partition_vs_b0", "cc_partition", "b0"),
               ("full_vs_b1b", FULL_ALIAS, "b1b")]


def read_rings_any(path: Path) -> list[Ring]:
    """Read a rings parquet written before or after the Step 8 contract bump.

    `ringshield.rings.read_rings_parquet` is deliberately strict -- a contract file must carry
    every column -- so it raises on the R2 / R3 / R4 run artefacts, which were written before
    `expanded_edge_probs` existed. Those runs are evidence, not contract deliverables, and
    re-running them would change nothing they contain, so this reader fills the columns a pre-v1
    file lacks with the defaults the schema gives them ([] / NaN / UNKNOWN / uniform). The strict
    reader is untouched and is what the contract path still uses."""
    import pyarrow.parquet as pq
    from contract.schema import RINGS_ORDER, TOPOLOGY_TYPES
    rows = pq.read_table(path).to_pylist()
    default = {"expanded_edges": [], "expanded_edge_probs": [], "conservation_closure": float("nan"),
               "topology_type": "UNKNOWN", "topology_probs": [1.0 / len(TOPOLOGY_TYPES)] * len(TOPOLOGY_TYPES),
               "source_accounts": [], "sink_accounts": [], "mule_accounts": []}
    out = []
    for row in rows:
        vals = {}
        for c in RINGS_ORDER:
            if c in row:
                vals[c] = row[c]
            elif c in default:
                vals[c] = list(default[c]) if isinstance(default[c], list) else default[c]
            else:
                raise KeyError(f"{path}: missing column {c!r} with no schema default")
        out.append(Ring(**vals))
    return out


def scores_path(kind: str, seed: int, split: str) -> Path:
    if kind == "gine":
        return R1 / f"scores_{split}_seed{seed}.parquet"
    if kind == "gfpxgb":
        return R2 / "gfpxgb_scores" / f"scores_{split}_seed{seed}.parquet"
    if kind == "density":
        return R2 / "density_scores" / f"scores_{split}_seed{seed}.parquet"
    raise ValueError(kind)


def collect(methods: dict, windows: dict, seeds: list[int], scope: str = "test_visible") -> dict:
    """{(method, window): [RingEvidence per seed]} -- one pass over the run artefacts."""
    paths = load_paths()
    pdir = paths["processed_dir"]
    gt = pd.read_parquet(pdir / "amlworld_ring_ground_truth.parquet")
    r1_cfg = yaml.safe_load((R1 / "config.yaml").read_text(encoding="utf-8"))
    causal = bool(r1_cfg.get("causal_sampling"))
    if not causal:
        raise ValueError(f"{R1}/config.yaml: causal_sampling is false -- time-to-detection would be meaningless")
    truth_cache, se_cache = {}, {}
    out: dict = {}
    for method, (root, kind, _) in methods.items():
        run_seeds = [s for s in seeds if (root / f"seed{s}" / "rings.parquet").exists()]
        if not run_seeds:
            print(f"  [skip] {method}: no rings.parquet under {root}")
            continue
        cfg_any = yaml.safe_load((root / f"seed{run_seeds[0]}" / "config.yaml").read_text(encoding="utf-8"))
        k_raw = (cfg_any.get("chosen") or {}).get("seed_frac_pct")
        # B5 (CSGM) uses no detector and therefore has no seed set: quiet-member recall and
        # time-to-detection are undefined for it and are left empty rather than measured against
        # another model's seeds.
        k_pct = float(k_raw) if k_raw is not None else None
        for s in run_seeds:
            rings = read_rings_any(root / f"seed{s}" / "rings.parquet")
            key = (kind, s)
            if key not in se_cache:
                se_cache[key] = build_scored_edges(scores_path(kind, s, "test"), "test", model_id=kind, seed=s,
                                                   processed_dir=pdir)
            se = se_cache[key]
            mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct) if k_pct is not None else None
            for wname, w in windows.items():
                if w.split != "test":
                    continue
                if wname not in truth_cache:
                    truth_cache[wname] = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *w.bounds,
                                                           scope, verbose=False)
                truth, patterns = truth_cache[wname]
                ev = ring_evidence(rings, se, truth, w, method=method, seed=s, seed_mask=mask, patterns=patterns,
                                   causal=causal, truth_edges=gt if mask is not None else None)
                out.setdefault((method, wname), []).append(ev)
        print(f"  {method}: {len(run_seeds)} seeds x {len([w for w in windows.values() if w.split == 'test'])} windows "
              f"(k*={k_pct if k_pct is not None else 'n/a (no detector seeds)'})", flush=True)
    return out


def ci_rows(evidence: dict, n_boot: int, seed: int) -> pd.DataFrame:
    rows = []
    for (method, window), evs in sorted(evidence.items()):
        ci = bootstrap_over_rings(evs, n_resamples=n_boot, seed=seed)
        row = {"method": method, "window": window, "n_seeds": len(evs), "n_truth_rings": ci["_meta"]["n_truth_rings"],
               "n_resamples": n_boot}
        for m in RATE_METRICS:
            row[f"{m}"] = ci[m]["point"]
            row[f"{m}_lo"] = ci[m]["lo"]
            row[f"{m}_hi"] = ci[m]["hi"]
        rows.append(row)
    return pd.DataFrame(rows)


def val_point_rows(methods: dict, seeds: list[int]) -> pd.DataFrame:
    """Val-window point estimates carried from each run's metrics.json.

    Amendment (a) asks for every window. The val ring metrics exist in every run's
    `val_at_chosen` block, but ring-level bootstrap CIs need the val PREDICTIONS, and no step
    saved a val rings.parquet (each runner built them in memory to choose its cell). Rather than
    re-run four pipelines to put an interval on a number that chose nothing, the val row carries
    the point estimates with empty CI columns and `ci_source = 'not resampled (val rings not
    materialised)'`."""
    rows = []
    for method, (root, _, _) in methods.items():
        vals = []
        for s in seeds:
            mp = root / f"seed{s}" / "metrics.json"
            if mp.exists():
                v = json.loads(mp.read_text(encoding="utf-8")).get("val_at_chosen")
                if v:
                    vals.append(v)
        if not vals:
            continue
        row = {"method": method, "window": "val", "n_seeds": len(vals), "n_truth_rings": vals[0].get("n_truth"),
               "n_resamples": 0, "ci_source": "not resampled (val rings not materialised)"}
        for m in RATE_METRICS:
            row[m] = float(np.nanmean([v.get(m, np.nan) for v in vals])) if m in vals[0] else np.nan
            row[f"{m}_lo"] = np.nan
            row[f"{m}_hi"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def quiet_rows(evidence: dict, ci_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (method, window), evs in sorted(evidence.items()):
        per = quiet_member_recall_per_pattern(evs)
        tot_q = sum(d["n_quiet"] for d in per.values())
        tot_f = sum(d["n_found"] for d in per.values())
        c = ci_df[(ci_df["method"] == method) & (ci_df["window"] == window)]
        rows.append({"method": method, "window": window, "pattern": "ALL", "n_seeds": len(evs),
                     "n_quiet": tot_q / len(evs), "n_found": tot_f / len(evs),
                     "quiet_member_recall": (tot_f / tot_q) if tot_q else np.nan,
                     "ci_lo": float(c["quiet_member_recall_lo"].iloc[0]) if len(c) else np.nan,
                     "ci_hi": float(c["quiet_member_recall_hi"].iloc[0]) if len(c) else np.nan})
        for pat, d in sorted(per.items()):
            rows.append({"method": method, "window": window, "pattern": pat, "n_seeds": len(evs),
                         "n_quiet": d["n_quiet"] / len(evs), "n_found": d["n_found"] / len(evs),
                         "quiet_member_recall": d["recall"], "ci_lo": np.nan, "ci_hi": np.nan})
    return pd.DataFrame(rows)


def ttd_rows(evidence: dict) -> pd.DataFrame:
    rows = []
    for (method, window), evs in sorted(evidence.items()):
        t = time_to_detection(evs)
        rows.append({"method": method, "window": window, "n_seeds": len(evs), **t})
    return pd.DataFrame(rows)


def significance(evidence: dict, window: str, n_perm: int, seed: int) -> pd.DataFrame:
    raw, rows = [], []
    for name, a, b in COMPARISONS:
        ea, eb = evidence.get((a, window)), evidence.get((b, window))
        if not ea or not eb:
            print(f"  [skip] {name}: missing evidence")
            continue
        seeds = sorted({e.seed for e in ea} & {e.seed for e in eb})
        ea = [e for e in ea if e.seed in seeds]
        eb = [e for e in eb if e.seed in seeds]
        m = paired_permutation(ea, eb, metric="matched", n_permutations=n_perm, seed=seed)
        q = paired_permutation(ea, eb, metric="quiet_found", n_permutations=n_perm, seed=seed)
        rows.append({"comparison": name, "a": a, "b": b, "window": window, "n_seeds": len(seeds),
                     "n_truth_rings": m["n_rings"], "metric": "ring_matched",
                     "mean_delta": m["mean_delta"], "delta_ci_lo": m["delta_ci"][0], "delta_ci_hi": m["delta_ci"][1],
                     "n_differing_rings": m["n_differing_rings"], "p_raw": m["p_value"],
                     "quiet_mean_delta": q["mean_delta"], "quiet_p_raw": q["p_value"],
                     "quiet_delta_ci_lo": q["delta_ci"][0], "quiet_delta_ci_hi": q["delta_ci"][1]})
        raw.append((name, m["p_value"]))
    adj = {d["comparison"]: d for d in holm(raw)}
    qadj = {d["comparison"]: d for d in holm([(r["comparison"], r["quiet_p_raw"]) for r in rows])}
    for r in rows:
        r["p_holm"] = adj[r["comparison"]]["p_holm"]
        r["reject_at_05"] = adj[r["comparison"]]["reject_at_05"]
        r["quiet_p_holm"] = qadj[r["comparison"]]["p_holm"]
        r["quiet_reject_at_05"] = qadj[r["comparison"]]["reject_at_05"]
    return pd.DataFrame(rows)


def appendix_rows(methods: dict, windows: dict, seeds: list[int], taus=(0.3, 0.7), scope: str = "test_visible") -> pd.DataFrame:
    """Every ring row again at Jaccard 0.3 and 0.7 (item 5)."""
    paths = load_paths()
    pdir = paths["processed_dir"]
    rows = []
    se_cache, truth_cache = {}, {}
    for method, (root, kind, table) in methods.items():
        run_seeds = [s for s in seeds if (root / f"seed{s}" / "rings.parquet").exists()]
        for tau in taus:
            per_seed = []
            for s in run_seeds:
                rings = read_rings_any(root / f"seed{s}" / "rings.parquet")
                key = (kind, s)
                if key not in se_cache:
                    se_cache[key] = build_scored_edges(scores_path(kind, s, "test"), "test", model_id=kind, seed=s,
                                                       processed_dir=pdir)
                se = se_cache[key]
                for wname, w in windows.items():
                    if w.split != "test":
                        continue
                    if wname not in truth_cache:
                        truth_cache[wname] = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *w.bounds,
                                                               scope, verbose=False)
                    truth, patterns = truth_cache[wname]
                    ev = ring_evidence(rings, se, truth, w, method=method, seed=s, patterns=patterns, threshold=tau)
                    per_seed.append((wname, metrics_from_evidence(ev)))
            for wname in {w for w, _ in per_seed}:
                vals = [m for w, m in per_seed if w == wname]
                rows.append({"method": method, "table": table, "window": wname, "tau": tau, "n_seeds": len(vals),
                             **{k: float(np.nanmean([v[k] for v in vals])) for k in
                                ("ring_precision", "ring_recall", "ring_f1", "member_coverage", "mean_jaccard", "ring_recall_ge3")}})
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--windows", nargs="*", default=None, help="default: every test window of configs/eval_window.yaml")
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--n-permutations", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--skip-appendix", action="store_true")
    ap.add_argument("--out-dir", type=Path, default=TABLES)
    args = ap.parse_args(argv)
    t0 = time.time()
    W = load_windows()
    windows = {k: w for k, w in W.items() if (args.windows is None or k in args.windows)}
    print(f"[step9] windows {[k for k, w in windows.items() if w.split == 'test']}, seeds {args.seeds}")
    evidence = collect(METHODS, windows, args.seeds)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    ci = ci_rows(evidence, args.n_bootstrap, args.seed)
    ci["ci_source"] = f"bootstrap over truth rings, {args.n_bootstrap} resamples"
    ci = pd.concat([ci, val_point_rows(METHODS, args.seeds)], ignore_index=True)
    ci.to_csv(args.out_dir / "r9_ring_ci.csv", index=False)
    for table in ("r2", "r3", "r4"):
        keep = {m for m, (_, _, t) in METHODS.items() if t == table}
        ci[ci["method"].isin(keep)].to_csv(args.out_dir / f"{table}_ci.csv", index=False)
    quiet = quiet_rows(evidence, ci)
    quiet.to_csv(args.out_dir / "r9_quiet_members.csv", index=False)
    ttd = ttd_rows(evidence)
    ttd.to_csv(args.out_dir / "r9_ttd.csv", index=False)
    sig = significance(evidence, "primary", args.n_permutations, args.seed)
    sig.to_csv(args.out_dir / "r9_significance.csv", index=False)
    for table, keep in (("r3", {"proposed_vs_b1b", "proposed_vs_b0"}), ("r4", {"full_vs_b2", "cc_partition_vs_b0", "full_vs_b1b"})):
        sig[sig["comparison"].isin(keep)].to_csv(args.out_dir / f"{table}_pvalues.csv", index=False)
    if not args.skip_appendix:
        app = appendix_rows(METHODS, windows, args.seeds)
        app.to_csv(args.out_dir / "r9_tau_appendix.csv", index=False)
        for table in ("r2", "r3", "r4"):
            app[app["table"] == table].to_csv(args.out_dir / f"{table}_appendix.csv", index=False)

    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
            "seeds": args.seeds, "windows": [k for k, w in windows.items() if w.split == "test"],
            "n_bootstrap": args.n_bootstrap, "n_permutations": args.n_permutations, "rng_seed": args.seed,
            "methods": {m: str(r) for m, (r, _, _) in METHODS.items()},
            "comparisons": [c[0] for c in COMPARISONS], "full_alias": FULL_ALIAS,
            "quiet_member_rule": "scored members of an in-scope truth ring with no incident SEED edge inside the window",
            "bootstrap_unit": "truth ring, with replacement; seeds averaged inside each resample",
            "permutation": "paired sign-flip on per-ring matched indicators (seeds averaged per ring), Holm across the table",
            "seconds": round(time.time() - t0, 1)}
    (args.out_dir / "r9_significance.log.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    prim = ci[ci["window"] == "primary"].set_index("method")
    print("\n== primary window: quiet-member recall (point [95 % CI]) ==")
    for m in ("b0", "b1b", "proposed", "average", "cc_partition"):
        if m in prim.index:
            r = prim.loc[m]
            print(f"  {m:13s} {r['quiet_member_recall']:.4f}  [{r['quiet_member_recall_lo']:.4f}, {r['quiet_member_recall_hi']:.4f}]"
                  f"   ring-F1 {r['ring_f1']:.4f} [{r['ring_f1_lo']:.4f}, {r['ring_f1_hi']:.4f}]")
    print("\n== significance (primary, ring-matched indicator) ==")
    if len(sig):
        print(sig[["comparison", "n_truth_rings", "n_differing_rings", "mean_delta", "delta_ci_lo", "delta_ci_hi",
                   "p_raw", "p_holm", "reject_at_05"]].round(4).to_string(index=False))
    print(f"\n-> {args.out_dir}  ({meta['seconds']} s)")


if __name__ == "__main__":
    main()
