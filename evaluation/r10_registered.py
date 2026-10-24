"""R10 as registered in docs/TENANT_SIZES.md (2026-10-22): what a bank loses by seeing only its own edges.

    python evaluation/r10_registered.py                  # all rows, 5 seeds
    python evaluation/r10_registered.py --seeds 1        # quick check

Unit: a tenant-ring pair. A truth ring in scope of the primary window (days 8-9, test_visible)
counts once for tenant T when at least one of its scored members has home bank T
(data/processed/account_bank.parquet). Each pair is "recovered" by a ring set when one of its rings
matches it at Jaccard >= 0.5 (evaluation/ring_metrics.match_rings, greedy one-to-one against the
tenant's pairs). The pooled comparison matches the pooled rings against the same pairs, so the
difference is the cross-bank blind spot. Matched indicators are averaged over seeds inside each
pair; the 95 % CI is a bootstrap over rings, 10,000 resamples, each ring resampled together with
all of its tenant pairs. Per-tenant numbers are descriptive.

Rows:
  primary         tenants 1, 20, 11, 118, 12; tenant-visible scores, GFP and embeddings (option b),
                  seeds = score_raw above the pooled cutoff q of that seed
  pooled_scores   secondary (a): pooled scores restricted to the tenant's visible edges, same cutoff
  budget_matched  secondary: tenant-visible scores, seed count = the pooled seed count on the same
                  visible edges (top-n by score_raw)
  robustness      tenants 70, 12, 11, 1, 10 with the primary option; reported as degenerate
                  (bank 70 has no visible ring laundering edge), computed exactly as registered

Ring sets are cached under experiments/R10_registered/runs/; outputs are
results/tables/r10_registered.json and .md.
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
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from evaluation.ring_metrics import match_rings  # noqa: E402
from jobs.build_tenant_rings import build_edge_subset, seed_fraction_for_cutoff  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

MODEL_ID = "gine_causal"
SEEDS = (1, 2, 3, 4, 5)
PRIMARY = (1, 20, 11, 118, 12)
ROBUSTNESS = (70, 12, 11, 1, 10)
JACCARD = 0.5
N_BOOT = 10_000
RUNS = REPO_ROOT / "experiments" / "R10_registered" / "runs"
TRUTH = REPO_ROOT / "data" / "processed" / "amlworld_ring_ground_truth.parquet"
ACCOUNT_MAP = REPO_ROOT / "data" / "processed" / "account_bank.parquet"
POOLED_GFP = REPO_ROOT / "data" / "processed" / "amlworld_gfp_features_test.parquet"
VISIBLE = REPO_ROOT / "data" / "tenant_visible"


def pooled_scores(seed: int) -> Path:
    return REPO_ROOT / "contract" / "out" / f"scored_edges_{MODEL_ID}_{seed}.parquet"


def pooled_cutoff(seed: int) -> float:
    log = json.loads(Path(str(pooled_scores(seed)) + ".log.json").read_text(encoding="utf-8"))
    return float(log["seed_rule"]["q"])


def model_dir(seed: int) -> Path:
    return REPO_ROOT / "models" / "artifacts" / f"full_{MODEL_ID}_seed{seed}"


def visible_scores(tenant: int, seed: int) -> Path:
    return VISIBLE / f"scored_edges_visible_{tenant}_{MODEL_ID}_{seed}.parquet"


def run_rings(*, scores: Path, seed: int, gfp: Path, embeddings: Path, out: Path,
              subset: Path | None = None, tenant: int | None = None, seed_frac_pct: float | None = None) -> Path:
    """One `ringshield run` with the shipped full model of this detector seed; cached by output path."""
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "ringshield", "run", "--scores", str(scores), "--model-dir", str(model_dir(seed)),
           "--aggregator", "full", "--gfp", str(gfp), "--embeddings", str(embeddings), "--out", str(out)]
    if subset is not None:
        cmd += ["--edge-subset", str(subset), "--tenant-id", str(tenant)]
    if seed_frac_pct is not None:
        cmd += ["--seed-frac-pct", repr(seed_frac_pct)]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    return out


def tenant_rings(variant: str, tenant: int, seed: int, q: float) -> Path:
    """Ring set for one tenant view: primary (option b), pooled_scores (a) or budget_matched."""
    run_dir = RUNS / variant / f"T{tenant}" / f"seed{seed}"
    out = run_dir / "rings.parquet"
    if out.is_file():
        return out
    visible = visible_scores(tenant, seed)
    subset = run_dir / "edge_subset.parquet"
    if variant == "pooled_scores":
        scores = pooled_scores(seed)
        n_visible = build_edge_subset(scores, tenant, subset)
        ids = set(pq.read_table(subset)["edge_id"].to_pylist())
        values = pd.read_parquet(scores, columns=["edge_id", "score_raw"]).loc[lambda d: d["edge_id"].isin(ids), "score_raw"]
        pct = seed_fraction_for_cutoff(values.to_numpy(float), q)
        gfp, emb = POOLED_GFP, REPO_ROOT / "experiments" / f"R1_{MODEL_ID}" / f"embeddings_test_seed{seed}.parquet"
    else:
        scores = visible
        n_visible = build_edge_subset(scores, tenant, subset)
        values = pd.read_parquet(scores, columns=["score_raw"])["score_raw"].to_numpy(float)
        if variant == "primary":
            pct = seed_fraction_for_cutoff(values, q)
        else:  # budget_matched: top-n visible edges, n = pooled seeds on the same visible edges
            ids = set(pq.read_table(subset)["edge_id"].to_pylist())
            pooled = pd.read_parquet(pooled_scores(seed), columns=["edge_id", "score_raw"]).loc[lambda d: d["edge_id"].isin(ids)]
            n = int((pooled["score_raw"] > q).sum())
            ordered = np.sort(values[np.isfinite(values)])[::-1]
            if n >= len(ordered):
                raise ValueError(f"budget n={n} is not below the {len(ordered)} visible edges of tenant {tenant}")
            # Cut halfway between the n-th and (n+1)-th score: a cut exactly on a score is not
            # reproducible through the CLI's linear percentile. A tie there keeps both (logged).
            pct = 0.0 if n == 0 else seed_fraction_for_cutoff(values, float(ordered[n - 1] + ordered[n]) / 2)
        gfp = VISIBLE / f"T{tenant}" / "processed" / "amlworld_gfp_features_test.parquet"
        emb = VISIBLE / f"embeddings_visible_{tenant}_{MODEL_ID}_{seed}_test.parquet"
    run_rings(scores=scores, seed=seed, gfp=gfp, embeddings=emb, out=out, subset=subset, tenant=tenant,
              seed_frac_pct=pct)
    (run_dir / "seed_rule.json").write_text(json.dumps(
        {"variant": variant, "tenant": tenant, "seed": seed, "pooled_q": q, "seed_frac_pct": pct,
         "n_visible_edges": n_visible, "scores": str(scores.relative_to(REPO_ROOT))}, indent=2), encoding="utf-8")
    return out


def restricted_members(rings_path: Path, edges: pd.DataFrame, lo: int, hi: int) -> list[set]:
    """Predicted member sets restricted to the window: endpoints of in-window member_edges."""
    in_win = edges[(edges["timestamp"] >= lo) & (edges["timestamp"] <= hi)]
    frm, to = in_win["from_id"], in_win["to_id"]
    out = []
    for member_edges in pq.read_table(rings_path, columns=["member_edges"])["member_edges"].to_pylist():
        keep = [e for e in member_edges if e in frm.index]
        if keep:
            out.append(set(frm.loc[keep].tolist()) | set(to.loc[keep].tolist()))
    return out


def recovered(pred: list[set], truth_subset: dict) -> set:
    matches, _, _ = match_rings(pred, truth_subset, JACCARD)
    return {m.truth_id for m in matches}


def bootstrap(pairs: pd.DataFrame, seed: int = 0) -> dict:
    """Pooled tenant-ring-pair recall for tenant and pooled views, and their difference, with a
    bootstrap over rings (a ring is resampled with all of its tenant pairs)."""
    rings = pairs["ring_id"].unique()
    by_ring = pairs.groupby("ring_id")[["tenant", "pooled"]].agg(["sum", "count"])
    t_sum, p_sum = by_ring[("tenant", "sum")].reindex(rings).to_numpy(), by_ring[("pooled", "sum")].reindex(rings).to_numpy()
    n = by_ring[("tenant", "count")].reindex(rings).to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(rings), size=(N_BOOT, len(rings)))
    tw, pw, nw = t_sum[idx].sum(1), p_sum[idx].sum(1), n[idx].sum(1)
    stats = {"tenant": tw / nw, "pooled": pw / nw, "difference": (pw - tw) / nw}
    point = {"tenant": pairs["tenant"].mean(), "pooled": pairs["pooled"].mean()}
    point["difference"] = point["pooled"] - point["tenant"]
    return {k: {"value": round(float(point[k]), 4), "low": round(float(np.percentile(v, 2.5)), 4),
                "high": round(float(np.percentile(v, 97.5)), 4)} for k, v in stats.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=list(SEEDS))
    a = ap.parse_args(argv)

    window = load_windows()["primary"]
    lo, hi = window.bounds
    truth, patterns = load_ground_truth(TRUTH, lo, hi, "test_visible", verbose=False)
    banks = pd.read_parquet(ACCOUNT_MAP).set_index("account_id")["bank_code"]
    ring_banks = {rid: {int(banks.get(acc, -1)) for acc in members} for rid, members in truth.items()}
    cross_bank = sum(len(b - {-1}) > 1 for b in ring_banks.values())

    rows, per_tenant = {}, []
    specs = {"primary": ("primary", PRIMARY), "pooled_scores": ("pooled_scores", PRIMARY),
             "budget_matched": ("budget_matched", PRIMARY), "robustness": ("primary", ROBUSTNESS)}
    for row, (variant, tenants) in specs.items():
        indicators = []
        for seed in a.seeds:
            q = pooled_cutoff(seed)
            edges = pd.read_parquet(pooled_scores(seed), columns=["edge_id", "from_id", "to_id", "timestamp"]
                                    ).set_index("edge_id")
            pooled_rings = run_rings(scores=pooled_scores(seed), seed=seed, gfp=POOLED_GFP,
                                     embeddings=REPO_ROOT / "experiments" / f"R1_{MODEL_ID}" / f"embeddings_test_seed{seed}.parquet",
                                     out=RUNS / "pooled" / f"seed{seed}" / "rings.parquet")
            pooled_pred = restricted_members(pooled_rings, edges, lo, hi)
            for tenant in tenants:
                subset = {rid: truth[rid] for rid, b in ring_banks.items() if tenant in b}
                tenant_pred = restricted_members(tenant_rings(variant, tenant, seed, q), edges, lo, hi)
                got_t, got_p = recovered(tenant_pred, subset), recovered(pooled_pred, subset)
                indicators += [{"seed": seed, "tenant_id": tenant, "ring_id": rid, "tenant": rid in got_t,
                                "pooled": rid in got_p} for rid in subset]
        df = pd.DataFrame(indicators)
        pairs = df.groupby(["tenant_id", "ring_id"], as_index=False)[["tenant", "pooled"]].mean()
        rows[row] = {"tenants": list(tenants), "n_pairs": int(len(pairs)), "n_rings": int(pairs["ring_id"].nunique()),
                     **bootstrap(pairs)}
        for tenant, g in pairs.groupby("tenant_id"):
            per_tenant.append({"row": row, "tenant_id": int(tenant), "n_rings": int(len(g)),
                               "tenant_recall": round(float(g["tenant"].mean()), 4),
                               "pooled_recall": round(float(g["pooled"].mean()), 4)})

    result = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds,
              "window": window.as_dict(), "scope": "test_visible", "jaccard": JACCARD, "n_boot": N_BOOT,
              "n_in_scope_rings": len(truth), "cross_bank_rings": cross_bank,
              "cross_bank_fraction": round(cross_bank / len(truth), 4),
              "mean_banks_per_ring": round(float(np.mean([len(b - {-1}) for b in ring_banks.values()])), 3),
              "rows": rows, "per_tenant": per_tenant}
    out = REPO_ROOT / "results" / "tables" / "r10_registered.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(render(result), encoding="utf-8")
    print(render(result))
    return 0


def render(r: dict) -> str:
    def ci(x):
        return f"{x['value']:.3f} [{x['low']:.3f}, {x['high']:.3f}]"
    lines = ["# R10: per-tenant vs pooled ring recall (registered in docs/TENANT_SIZES.md)", "",
             f"Primary window (days 8-9), `test_visible`, Jaccard {r['jaccard']}, seeds {r['seeds']}, unit = tenant-ring "
             f"pair, 95 % CI = bootstrap over rings ({r['n_boot']:,}). Created {r['created_utc']}.", "",
             f"Cross-bank rings: **{r['cross_bank_rings']} of {r['n_in_scope_rings']} ({r['cross_bank_fraction']:.1%})**; "
             f"mean banks per ring {r['mean_banks_per_ring']}.", "",
             "| row | tenants | pairs | rings | tenant recall | pooled recall | pooled − tenant |",
             "|---|---|---:|---:|---|---|---|"]
    for name, row in r["rows"].items():
        label = name + (" (degenerate: bank 70 has no visible ring laundering edge)" if name == "robustness" else "")
        lines.append(f"| {label} | {', '.join(map(str, row['tenants']))} | {row['n_pairs']} | {row['n_rings']} | "
                     f"{ci(row['tenant'])} | {ci(row['pooled'])} | {ci(row['difference'])} |")
    lines += ["", "Per tenant (descriptive only, no claim):", "", "| row | tenant | rings | tenant recall | pooled recall |",
              "|---|---:|---:|---:|---:|"]
    lines += [f"| {t['row']} | {t['tenant_id']} | {t['n_rings']} | {t['tenant_recall']:.3f} | {t['pooled_recall']:.3f} |"
              for t in r["per_tenant"]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
