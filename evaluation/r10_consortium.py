"""R10 consortium-size curve (deep-analysis #3): how many banks must pool edges to recover pooled recall?

    python evaluation/r10_consortium.py --src ../RS-testing1 --out results/tables/r10_consortium

Same unit, window, matching and bootstrap as evaluation/r10_registered.py (tenant-ring pairs of the
registered primary tenants 1, 20, 11, 118, 12; primary window, test_visible, Jaccard 0.5; matched
indicators averaged over seeds inside a pair; 10,000 resamples over rings, each ring with all its
pairs). The denominator is FIXED: the same 68 pairs at every k.

Consortium of size k for a pair (T, r): T plus the first k-1 OTHER primary tenants in registered
order. Rings are built with the registered `pooled_scores` option (secondary (a)): pooled scores,
pooled GFP and embeddings, restricted to the edges with either endpoint in a consortium bank, seeds
= score_raw above the pooled cutoff q of that seed. So k = 1 is exactly the registered
pooled_scores row (0.121) and k = 5 is the five-bank union for every tenant. `pooled` (all 30,470
banks) is the registered ceiling (0.359).

Inputs (scores, shipped models, embeddings, R10 caches) are read from --src; new ring sets are
cached under <repo>/experiments/R10_consortium/runs/C<banks>/seed<S>/.
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
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from evaluation.r10_registered import N_BOOT, PRIMARY, recovered, restricted_members  # noqa: E402
from jobs.build_tenant_rings import seed_fraction_for_cutoff  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

MODEL_ID = "gine_causal"
RUNS = REPO_ROOT / "experiments" / "R10_consortium" / "runs"


def consortium(tenant: int, k: int) -> tuple[int, ...]:
    others = [t for t in PRIMARY if t != tenant]
    return tuple(sorted([tenant] + others[:k - 1]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="checkout holding contract/out, models/artifacts, R1 embeddings, R10 caches")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r10_consortium")
    a = ap.parse_args(argv)
    src = a.src.resolve()
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = REPO_ROOT / "data" / "processed"
    W = load_windows()["primary"]
    lo, hi = W.bounds
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", lo, hi, "test_visible", verbose=False)
    banks = pd.read_parquet(pdir / "account_bank.parquet").set_index("account_id")["bank_code"]
    ring_banks = {rid: {int(banks.get(acc, -1)) for acc in m} for rid, m in truth.items()}
    gfp = pdir / "amlworld_gfp_features_test.parquet"

    def scores(s):
        return src / "contract" / "out" / f"scored_edges_{MODEL_ID}_{s}.parquet"

    def rings_for(C: tuple, s: int, q: float, sc: pd.DataFrame) -> Path:
        if len(C) == 1:                       # registered pooled_scores cache
            cached = src / "experiments" / "R10_registered" / "runs" / "pooled_scores" / f"T{C[0]}" / f"seed{s}" / "rings.parquet"
            if cached.is_file():
                return cached
        run_dir = RUNS / ("C" + "-".join(map(str, C))) / f"seed{s}"
        out = run_dir / "rings.parquet"
        if out.is_file():
            return out
        run_dir.mkdir(parents=True, exist_ok=True)
        vis = sc[sc["from_bank"].isin(C) | sc["to_bank"].isin(C)]
        subset = run_dir / "edge_subset.parquet"
        pq.write_table(pa.table({"edge_id": pa.array(np.sort(vis["edge_id"].to_numpy()), type=pa.int64())}), subset)
        pct = seed_fraction_for_cutoff(vis["score_raw"].to_numpy(float), q)
        cmd = [sys.executable, "-m", "ringshield", "run", "--scores", str(scores(s)),
               "--model-dir", str(src / "models" / "artifacts" / f"full_{MODEL_ID}_seed{s}"), "--aggregator", "full",
               "--gfp", str(gfp), "--embeddings", str(src / "experiments" / f"R1_{MODEL_ID}" / f"embeddings_test_seed{s}.parquet"),
               "--out", str(out), "--edge-subset", str(subset), "--tenant-id", str(C[0]), "--seed-frac-pct", repr(pct)]
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, stdout=subprocess.DEVNULL)
        (run_dir / "seed_rule.json").write_text(json.dumps({"banks": list(C), "seed": s, "pooled_q": q, "seed_frac_pct": pct,
                                                            "n_visible_edges": int(len(vis))}, indent=2), encoding="utf-8")
        print(f"    built C{'-'.join(map(str, C))} seed {s}: {len(vis):,} visible edges", flush=True)
        return out

    ind = []
    for s in a.seeds:
        q = float(json.loads(Path(str(scores(s)) + ".log.json").read_text(encoding="utf-8"))["seed_rule"]["q"])
        sc = pd.read_parquet(scores(s), columns=["edge_id", "from_id", "to_id", "timestamp", "from_bank", "to_bank", "score_raw"])
        edges = sc.set_index("edge_id")[["from_id", "to_id", "timestamp"]]
        pooled_path = src / "experiments" / "R10_registered" / "runs" / "pooled" / f"seed{s}" / "rings.parquet"
        pooled_pred = restricted_members(pooled_path, edges, lo, hi)
        for T in PRIMARY:
            sub = {rid: truth[rid] for rid, b in ring_banks.items() if T in b}
            got_p = recovered(pooled_pred, sub)
            for k in range(1, len(PRIMARY) + 1):
                C = consortium(T, k)
                got = recovered(restricted_members(rings_for(C, s, q, sc), edges, lo, hi), sub)
                ind += [{"seed": s, "tenant_id": T, "ring_id": r, "k": k, "hit": r in got, "pooled": r in got_p} for r in sub]
        print(f"  seed {s} done", flush=True)

    df = pd.DataFrame(ind)
    pairs = df.groupby(["tenant_id", "ring_id", "k"], as_index=False)[["hit", "pooled"]].mean()
    wide = pairs.pivot_table(index=["tenant_id", "ring_id"], columns="k", values="hit").reset_index()
    wide["pooled"] = pairs.groupby(["tenant_id", "ring_id"])["pooled"].first().to_numpy()
    ks = list(range(1, len(PRIMARY) + 1))
    cols = ks + ["pooled"]
    rings = wide["ring_id"].unique()
    per_ring = wide.groupby("ring_id")[cols].sum().reindex(rings)
    n_ring = wide.groupby("ring_id").size().reindex(rings).to_numpy()
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(rings), size=(N_BOOT, len(rings)))
    nw = n_ring[idx].sum(1)
    draws = {c: per_ring[c].to_numpy()[idx].sum(1) / nw for c in cols}

    def ci(v):
        return [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]
    curve = []
    for c in cols:
        pt = float(wide[c].mean())
        row = {"k": c, "recall": round(pt, 4), "ci": ci(draws[c]),
               "gain_vs_k1": round(pt - float(wide[1].mean()), 4), "gain_vs_k1_ci": ci(draws[c] - draws[1]),
               "share_of_pooled_gap": round((pt - float(wide[1].mean())) / (float(wide["pooled"].mean()) - float(wide[1].mean())), 4),
               "gap_to_pooled": round(float(wide["pooled"].mean()) - pt, 4), "gap_to_pooled_ci": ci(draws["pooled"] - draws[c])}
        curve.append(row)
    steps = [{"step": f"{k}->{k + 1}", "delta": round(float((wide[k + 1] - wide[k]).mean()), 4), "ci": ci(draws[k + 1] - draws[k]),
              "n_pairs_down": int((wide[k + 1] < wide[k]).sum())} for k in ks[:-1]]
    mono = all(s["delta"] >= 0 for s in steps)
    per_tenant = wide.groupby("tenant_id")[cols].mean().round(4).reset_index().to_dict(orient="records")
    res = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds, "src": str(src),
           "tenants_order": list(PRIMARY), "n_pairs": int(len(wide)), "n_rings": int(len(rings)), "n_boot": N_BOOT,
           "curve": curve, "steps": steps, "monotone_point": mono,
           "k5_excludes_k1": curve[4]["gain_vs_k1_ci"][0] > 0, "per_tenant": per_tenant}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    Path(str(a.out) + ".json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    wide.to_csv(str(a.out) + "_pairs.csv", index=False)
    for r in curve:
        print(f"  k={r['k']!s:6s} recall {r['recall']:.3f} {r['ci']} | gain vs k1 {r['gain_vs_k1']:+.3f} {r['gain_vs_k1_ci']} "
              f"| share of gap {r['share_of_pooled_gap']:.2f}")
    for s_ in steps:
        print(f"  step {s_['step']}: {s_['delta']:+.4f} {s_['ci']} (pairs down {s_['n_pairs_down']})")
    print(f"monotone {mono}; k5 interval excludes k1: {res['k5_excludes_k1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
