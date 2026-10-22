"""R6: does the ring layer depend on which detector feeds it? (Step 10.3)

    python evaluation/r6_detector_swap.py
    python evaluation/r6_detector_swap.py --detectors gine_causal mega --methods b0 full

Three detectors, each with the same L3 machinery downstream and every L3 parameter re-chosen on
val per detector per seed:

    gine_causal    our causal Multi-GINe (R1)                     policy/affinity: R3/R4, as shipped
    mega           MEGA-GNN MultiMPNN (R6, models/mega_adapter)   policy/affinity: R3/R4, unchanged
    mega_noembed   the same MEGA runs, policy/affinity with the embedding group dropped
    gfpxgb         GFP + XGBoost (R2 refit)                       policy/affinity trained on its own
                                                                  cross-scored train split, no embeddings

`mega_noembed` exists to settle a confound, not to add a method. The shipped policy learned its
two embedding-cosine thresholds in gine's 198-dim head space and would apply them to MEGA's
192-dim one; if MEGA's `full` row were weak, that alone could explain it. The two MEGA rows
bracket the question -- agreement means the embedding space is not doing the work, disagreement
means the `mega` row measures policy transfer as well as the detector, and both are reported.

Columns (primary window unless stated), each with a bootstrap CI over truth rings where it is a
rate: **edge F1** (val-tuned threshold, detector-level), **B0 ring-F1**, **full ring-F1**,
**quiet-member recall**, **added-member precision**, **class_b_rings**. The last is the count of
truth rings that no prediction touches at all (`evaluation/unmatched_rings.py`'s `b_untouched`):
it is the one column that says whether a different detector reaches *different rings* rather than
scoring the same ones better.

Outputs: `results/tables/r6_detector_swap.csv` (+ `.json` with the run provenance, the per-seed
k* cells, the loader route per detector and the policy/affinity provenance per row) and
`results/tables/r6_pvalues.csv` (pre-registered paired sign-flip tests, Holm-adjusted).

**Pre-registered before the table existed** (written here so the reading is not chosen after seeing the
numbers): *if* `mega/full` beats `gine_causal/full` on ring-F1 by more than the seed spread, the
explanation to test first is **not** "MEGA is better for rings" but "MEGA's seeds are spread more evenly
across rings at the same budget". Two columns decide it rather than the narrative:

    matched_per_seed_edge          matched truth rings / seed edges inside the window -- how much ring
                                   each seed edge buys. Rises if the seeds are better *placed*.
    seeds_per_touched_ring_*       mean / median / max / Gini of the number of seed edges falling on each
                                   truth ring that has any. A lower Gini at equal reach is the even-spread
                                   explanation; an unchanged Gini with more rings reached is not.

`seed_edges_off_ring_share` (seed edges belonging to no truth ring) is reported alongside, because a
detector can raise matched_per_seed_edge simply by wasting fewer seeds.

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
from sklearn.metrics import f1_score

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_stats import (bootstrap_over_rings, holm, metrics_from_evidence,  # noqa: E402
                                   paired_permutation, ring_evidence)
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R2 = REPO_ROOT / "experiments" / "R2_b0"
R4 = REPO_ROOT / "experiments" / "R4_partition" / "runs"
R6M = REPO_ROOT / "experiments" / "R6_mega"
R6B0 = REPO_ROOT / "experiments" / "R6_b0"
R6F = REPO_ROOT / "experiments" / "R6_full"
TABLES = REPO_ROOT / "results" / "tables"

# detector -> scores dir, model_id, per-method run dir, and the provenance the footnote needs
DETECTORS: dict[str, dict] = {
    "gine_causal": {"scores": R1, "model_id": "gine_causal",
                    "runs": {"b0": R2 / "gine_causal", "full": R4 / "average"},
                    "policy": "R3 policy_proposed (70 features)", "affinity": "R4 affinity (20 features)",
                    "sampling": "ours_causal (models/causal_loader.py)"},
    "mega": {"scores": R6M, "model_id": "mega",
             "runs": {"b0": R6B0 / "mega", "full": R6F / "mega"},
             "policy": "R3 policy_proposed, unchanged (embedding cosines computed in MEGA's 192-dim space)",
             "affinity": "R4 affinity, unchanged", "sampling": "ours_causal (models/causal_loader.py)"},
    "mega_noembed": {"scores": R6M, "model_id": "mega",
                     "runs": {"full": R6F / "mega_noembed"},
                     "policy": "R3 policy_no_embedding", "affinity": "R4 affinity_no_embedding",
                     "sampling": "ours_causal (models/causal_loader.py)"},
    "gfpxgb": {"scores": R2 / "gfpxgb_scores", "model_id": "gfpxgb",
               "runs": {"b0": R2 / "gfpxgb", "full": R6F / "gfpxgb"},
               "policy": "R6 policy_gfpxgb (own cross-scores, embedding group dropped)",
               "affinity": "R6 affinity_gfpxgb (own pairs, embedding group dropped)",
               "sampling": "n/a (no graph sampling; trailing GFP features)"},
}
# pre-registered, in this order; Holm is applied across exactly these
COMPARISONS = [("mega_full_vs_gine_full", ("mega", "full"), ("gine_causal", "full")),
               ("mega_b0_vs_gine_b0", ("mega", "b0"), ("gine_causal", "b0")),
               ("gfpxgb_full_vs_gine_full", ("gfpxgb", "full"), ("gine_causal", "full")),
               ("mega_noembed_vs_mega_full", ("mega_noembed", "full"), ("mega", "full"))]


def edge_f1(scores_dir: Path, seeds, labels_dir: Path, n_grid: int = 400) -> dict:
    """Test edge F1 at a threshold tuned on val -- nothing is chosen on test."""
    lab = {s: pd.read_parquet(labels_dir / f"labels_{s}.parquet").set_index("edge_id")["true_label"]
           for s in ("val", "test")}
    out = []
    for s in seeds:
        v = pd.read_parquet(scores_dir / f"scores_val_seed{s}.parquet")
        t = pd.read_parquet(scores_dir / f"scores_test_seed{s}.parquet")
        yv = lab["val"].reindex(v["edge_id"]).to_numpy()
        yt = lab["test"].reindex(t["edge_id"]).to_numpy()
        sv, st = v["score_raw"].to_numpy(), t["score_raw"].to_numpy()
        grid = np.quantile(sv, np.linspace(0.90, 0.99999, n_grid))
        _, thr = max(((f1_score(yv, (sv >= th).astype(int), pos_label=1, zero_division=0), th) for th in grid))
        out.append(f1_score(yt, (st >= thr).astype(int), pos_label=1, zero_division=0))
    a = np.array(out, dtype=float)
    return {"edge_f1": float(a.mean()), "edge_f1_std": float(a.std(ddof=1)) if len(a) > 1 else float("nan"),
            "edge_f1_per_seed": [round(float(x), 4) for x in a]}


def added_member_precision(rings, se: pd.DataFrame, ring_id_of: pd.Series, window) -> tuple[int, int]:
    """(expanded edges inside the window that are member edges of a truth ring, total expanded)."""
    ts = se.set_index("edge_id")["timestamp"]
    exp = sorted({e for r in rings for e in r.expanded_edges})
    exp = [e for e in exp if e in ts.index and window.mask(np.array([ts.loc[e]]))[0]]
    if not exp:
        return 0, 0
    return int((ring_id_of.reindex(exp).fillna(-1).to_numpy() > 0).sum()), len(exp)


def gini(x: np.ndarray) -> float:
    """Concentration of a non-negative vector; 0 = every ring gets the same number of seeds."""
    if len(x) == 0 or x.sum() <= 0:
        return float("nan")
    v = np.sort(np.asarray(x, dtype=float))
    n = len(v)
    return float((2.0 * np.arange(1, n + 1) - n - 1).dot(v) / (n * v.sum()))


def seed_distribution(se: pd.DataFrame, mask: np.ndarray, ring_id_of: pd.Series, truth: dict, window) -> dict:
    """How the seed budget is spread over truth rings (pre-registered, see the module docstring)."""
    ids = se.loc[mask, "edge_id"].to_numpy()
    ts = se.loc[mask, "timestamp"].to_numpy()
    ids = ids[window.mask(ts)]
    if len(ids) == 0:
        return {"n_seed_edges_window": 0}
    rid = ring_id_of.reindex(ids).fillna(-1).to_numpy()
    keys = set(truth)
    counts: dict = {}
    off = 0
    for r in rid:
        r = int(r)
        if r > 0 and r in keys:
            counts[r] = counts.get(r, 0) + 1
        else:
            off += 1
    c = np.array(sorted(counts.values()), dtype=float)
    return {"n_seed_edges_window": int(len(ids)),
            "rings_touched_by_seeds": int(len(c)),
            "seeds_per_touched_ring_mean": float(c.mean()) if len(c) else float("nan"),
            "seeds_per_touched_ring_median": float(np.median(c)) if len(c) else float("nan"),
            "seeds_per_touched_ring_max": float(c.max()) if len(c) else float("nan"),
            "seeds_per_touched_ring_gini": gini(c),
            "seed_edges_off_ring_share": float(off / len(ids))}


def boot_mean(x: np.ndarray, n: int, seed: int) -> tuple[float, float, float]:
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    d = x[rng.integers(0, len(x), (n, len(x)))].mean(axis=1)
    return float(x.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detectors", nargs="*", default=list(DETECTORS))
    ap.add_argument("--methods", nargs="*", default=["b0", "full"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--window", default="primary")
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--n-perm", type=int, default=10000)
    ap.add_argument("--labels-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    ap.add_argument("--out", type=Path, default=TABLES / "r6_detector_swap.csv")
    ap.add_argument("--dry-run", action="store_true", help="2 seeds, 50 resamples; pipeline check, writes nothing")
    a = ap.parse_args(argv)
    t0 = time.time()
    if a.dry_run:
        a.seeds, a.n_boot, a.n_perm = a.seeds[:2], 50, 200
    pdir = load_paths()["processed_dir"]
    W = load_windows()[a.window]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, a.scope, verbose=False)
    gt = pd.read_parquet(pdir / "amlworld_ring_ground_truth.parquet")
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    print(f"[r6] window {a.window} {W.bounds}, scope {a.scope}: {len(truth)} truth rings, seeds {a.seeds}")

    se_cache: dict = {}
    evidence: dict = {}
    rows, prov = [], {}
    for det in a.detectors:
        spec = DETECTORS[det]
        ef = edge_f1(spec["scores"], a.seeds, a.labels_dir)
        for method in a.methods:
            root = spec["runs"].get(method)
            if root is None:
                continue
            seeds = [s for s in a.seeds if (root / f"seed{s}" / "rings.parquet").exists()]
            if not seeds:
                print(f"  [skip] {det}/{method}: no rings.parquet under {root}")
                continue
            cells, evs, addp, classb, spread = [], [], [], [], []
            for s in seeds:
                cfg = yaml.safe_load((root / f"seed{s}" / "config.yaml").read_text(encoding="utf-8"))
                cells.append(cfg.get("chosen"))
                rings = read_rings_any(root / f"seed{s}" / "rings.parquet")
                key = (spec["model_id"], s, str(spec["scores"]))
                if key not in se_cache:
                    se_cache[key] = build_scored_edges(spec["scores"] / f"scores_test_seed{s}.parquet", "test",
                                                       model_id=spec["model_id"], seed=s, processed_dir=pdir)
                se = se_cache[key]
                k_pct = float((cfg.get("chosen") or {}).get("seed_frac_pct"))
                mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct)
                evs.append(ring_evidence(rings, se, truth, W, method=f"{det}/{method}", seed=s, seed_mask=mask,
                                         patterns=patterns, causal=True, truth_edges=gt))
                ok, tot = added_member_precision(rings, se, ring_id_of, W)
                addp.append((ok, tot))
                kl = classify(rings, se, truth, patterns, W)
                classb.append(int((kl["klass"] == "b_untouched").sum()))
                sd = seed_distribution(se, mask, ring_id_of, truth, W)
                sd["matched_per_seed_edge"] = (sum(evs[-1].matched.values()) / sd["n_seed_edges_window"]
                                               if sd["n_seed_edges_window"] else float("nan"))
                sd["matched_rings"] = int(sum(evs[-1].matched.values()))
                spread.append(sd)
            evidence[(det, method)] = evs
            ci = bootstrap_over_rings(evs, n_resamples=a.n_boot, seed=0)
            per_seed = [metrics_from_evidence(ev) for ev in evs]
            flags = np.concatenate([np.repeat([1.0, 0.0], [ok, tot - ok]) for ok, tot in addp if tot]) \
                if any(t for _, t in addp) else np.zeros(0)
            ap_mean, ap_lo, ap_hi = boot_mean(flags, a.n_boot, 0)
            cb = np.array(classb, dtype=float)
            row = {"detector": det, "method": method, "n_seeds": len(seeds), "n_truth_rings": len(truth),
                   **ef,
                   "ring_f1": ci["ring_f1"]["point"], "ring_f1_lo": ci["ring_f1"]["lo"], "ring_f1_hi": ci["ring_f1"]["hi"],
                   "ring_f1_seed_std": float(np.std([m["ring_f1"] for m in per_seed], ddof=1)) if len(evs) > 1 else np.nan,
                   "ring_precision": ci["ring_precision"]["point"], "ring_recall": ci["ring_recall"]["point"],
                   "quiet_member_recall": ci["quiet_member_recall"]["point"],
                   "quiet_member_recall_lo": ci["quiet_member_recall"]["lo"],
                   "quiet_member_recall_hi": ci["quiet_member_recall"]["hi"],
                   "added_member_precision": ap_mean, "added_member_precision_lo": ap_lo,
                   "added_member_precision_hi": ap_hi,
                   "n_added_edges": int(sum(t for _, t in addp)),
                   "class_b_rings": float(cb.mean()), "class_b_rings_std": float(cb.std(ddof=1)) if len(cb) > 1 else np.nan,
                   "class_b_share": float(cb.mean() / len(truth)),
                   **{k: float(np.mean([sp[k] for sp in spread])) for k in
                      ("n_seed_edges_window", "matched_rings", "matched_per_seed_edge", "rings_touched_by_seeds",
                       "seeds_per_touched_ring_mean", "seeds_per_touched_ring_median",
                       "seeds_per_touched_ring_max", "seeds_per_touched_ring_gini",
                       "seed_edges_off_ring_share")}}
            rows.append(row)
            prov[f"{det}/{method}"] = {"run_dir": str(root), "scores_dir": str(spec["scores"]),
                                       "policy": spec["policy"], "affinity": spec["affinity"],
                                       "sampling": spec["sampling"], "chosen_per_seed": cells,
                                       "class_b_per_seed": classb,
                                       "added_member_precision_per_seed": [f"{ok}/{tot}" for ok, tot in addp]}
            print(f"  {det:13s} {method:5s}: edge F1 {row['edge_f1']:.4f} | ring F1 {row['ring_f1']:.4f} "
                  f"[{row['ring_f1_lo']:.4f}, {row['ring_f1_hi']:.4f}] | quiet {row['quiet_member_recall']:.4f} "
                  f"| added-member P {ap_mean:.4f} ({row['n_added_edges']} edges) | class (b) {cb.mean():.1f}"
                  f" of {len(truth)} | matched/seed-edge {row['matched_per_seed_edge']:.4f} "
                  f"| seeds/touched-ring {row['seeds_per_touched_ring_mean']:.2f} "
                  f"(Gini {row['seeds_per_touched_ring_gini']:.3f}, off-ring "
                  f"{row['seed_edges_off_ring_share']:.3f})", flush=True)

    d = pd.DataFrame(rows)
    pv = []
    for name, ka, kb in COMPARISONS:
        if ka not in evidence or kb not in evidence:
            continue
        r = paired_permutation(evidence[ka], evidence[kb], metric="matched", n_permutations=a.n_perm, seed=0)
        pv.append({"comparison": name, "a": f"{ka[0]}/{ka[1]}", "b": f"{kb[0]}/{kb[1]}",
                   "mean_delta_matched": r["mean_delta"], "delta_lo": r["delta_ci"][0], "delta_hi": r["delta_ci"][1],
                   "p_raw": r["p_value"], "n_rings": r["n_rings"], "n_differing_rings": r["n_differing_rings"],
                   "n_permutations": a.n_perm})
    if pv:
        by = {x["comparison"]: x for x in holm([(q["comparison"], q["p_raw"]) for q in pv])}
        for q in pv:
            q["p_holm"] = by[q["comparison"]]["p_holm"]
            q["reject_at_05"] = by[q["comparison"]]["reject_at_05"]
    pvd = pd.DataFrame(pv)

    if a.dry_run:
        print("\n[r6] DRY RUN -- nothing written\n")
        print(d.to_string(index=False))
        print(pvd.to_string(index=False) if len(pvd) else "(no comparisons available)")
        return d
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    pvd.to_csv(TABLES / "r6_pvalues.csv", index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
            "step": "10.3 (R6 detector swap)", "window": a.window, "window_bounds": list(W.bounds),
            "scope": a.scope, "seeds": a.seeds, "n_truth_rings": len(truth),
            "n_bootstrap": a.n_boot, "n_permutations": a.n_perm,
            "edge_f1_rule": "threshold tuned on the val split over 400 quantiles of the val scores, applied to test",
            "class_b_definition": "truth rings with >= 3 visible members that no prediction's included edges touch "
                                  "(evaluation/unmatched_rings.py::classify, klass b_untouched)",
            "comparability_note": "policy CV AUC-PR values are NOT comparable across detectors -- each policy is "
                                  "scored on the candidate set its own detector generates (docs/EXPANSION.md)",
            "pre_registered_alternative_explanation": {
                "written": "before the table existed",
                "rule": "if mega/full beats gine_causal/full on ring_f1 by more than the seed spread "
                        "(ring_f1_seed_std), the first explanation to test is that MEGA's seeds are spread "
                        "more evenly across rings at the same budget, not that MEGA is better for rings",
                "decided_by": ["matched_per_seed_edge", "seeds_per_touched_ring_gini",
                               "seeds_per_touched_ring_mean", "seed_edges_off_ring_share"],
                "even_spread_signature": "lower seeds_per_touched_ring_gini at equal rings_touched_by_seeds",
                "genuine_reach_signature": "higher rings_touched_by_seeds at unchanged gini"},
            "provenance": prov}
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"\n-> {a.out}\n-> {TABLES / 'r6_pvalues.csv'}  ({time.time() - t0:.0f}s)")
    return d


if __name__ == "__main__":
    main()
