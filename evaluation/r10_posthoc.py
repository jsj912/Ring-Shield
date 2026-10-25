"""R10 extras, post-hoc and descriptive: computed after the registered result, from its ring sets.

    python evaluation/r10_posthoc.py

None of this was registered in docs/TENANT_SIZES.md, and none of it carries a claim. It reuses the
ring sets cached by evaluation/r10_registered.py (3156d75) under experiments/R10_registered/runs/;
it never builds a ring set, and stops if one is missing. Before computing anything it re-scores
those ring sets and checks that every registered recall row reproduces exactly.

Extras:
  member coverage   ring_metrics.coverage of each matched truth ring (|pred & truth| / |truth|),
                    averaged over matched (tenant-ring pair, seed) instances, as ring_metrics does;
                    for every registered row, tenant and pooled side, 95 % CI by the same bootstrap
                    over rings (10,000)
  (a) vs (b)        primary tenants: recall of pooled scores on own edges (a) minus own scores on
                    own edges (b), paired by tenant-ring pair, same bootstrap
  visible edges     per tenant, the in-scope rings with at least one laundering edge in the primary
                    window where from_bank or to_bank is the tenant

Output: experiments/R10/results.json, with the sha256 of every ring set reused.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation import r10_registered as r10  # noqa: E402
from evaluation.ring_metrics import match_rings  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

LABEL = "post-hoc, descriptive"
OUT = REPO_ROOT / "experiments" / "R10" / "results.json"
REGISTERED = REPO_ROOT / "results" / "tables" / "r10_registered.json"
SPECS = {"primary": ("primary", r10.PRIMARY), "pooled_scores": ("pooled_scores", r10.PRIMARY),
         "budget_matched": ("budget_matched", r10.PRIMARY), "robustness": ("primary", r10.ROBUSTNESS)}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(path: Path) -> str:
    """Of a text file with LF line endings, so a Windows checkout hashes as the committed blob."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def cached(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"ring set not cached, refusing to build it: {path}")
    return path


def match(pred: list[set], subset: dict) -> dict:
    """truth_id -> coverage of its matched prediction."""
    matches, _, _ = match_rings(pred, subset, r10.JACCARD)
    return {m.truth_id: m.coverage for m in matches}


def boot_ratio(frames: dict[str, pd.DataFrame], seed: int = 0) -> dict:
    """Ratio estimates sum(num) / sum(den) per frame, CIs by one bootstrap over the union of rings."""
    rings = np.unique(np.concatenate([f["ring_id"].to_numpy() for f in frames.values()]))
    idx = np.random.default_rng(seed).integers(0, len(rings), size=(r10.N_BOOT, len(rings)))
    out = {}
    for name, f in frames.items():
        g = f.groupby("ring_id")[["num", "den"]].sum().reindex(rings, fill_value=0.0)
        num, den = g["num"].to_numpy()[idx].sum(1), g["den"].to_numpy()[idx].sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            draws = num / den
        point = f["num"].sum() / f["den"].sum() if f["den"].sum() else float("nan")
        out[name] = {"value": round(float(point), 4), "low": round(float(np.nanpercentile(draws, 2.5)), 4),
                     "high": round(float(np.nanpercentile(draws, 97.5)), 4), "n": int(f["den"].sum())}
    return out


def main() -> int:
    started = datetime.now(timezone.utc)
    window = load_windows()["primary"]
    lo, hi = window.bounds
    truth, _ = load_ground_truth(r10.TRUTH, lo, hi, "test_visible", verbose=False)
    banks = pd.read_parquet(r10.ACCOUNT_MAP).set_index("account_id")["bank_code"]
    ring_banks = {rid: {int(banks.get(acc, -1)) for acc in members} for rid, members in truth.items()}
    registered = json.loads(REGISTERED.read_text(encoding="utf-8"))

    used, records = {}, []
    for row, (variant, tenants) in SPECS.items():
        for seed in registered["seeds"]:
            edges = pd.read_parquet(r10.pooled_scores(seed), columns=["edge_id", "from_id", "to_id", "timestamp"]
                                    ).set_index("edge_id")
            pooled_path = cached(r10.RUNS / "pooled" / f"seed{seed}" / "rings.parquet")
            pooled_pred = r10.restricted_members(pooled_path, edges, lo, hi)
            used[pooled_path] = None
            for tenant in tenants:
                path = cached(r10.RUNS / variant / f"T{tenant}" / f"seed{seed}" / "rings.parquet")
                used[path] = None
                subset = {rid: truth[rid] for rid, b in ring_banks.items() if tenant in b}
                got_t = match(r10.restricted_members(path, edges, lo, hi), subset)
                got_p = match(pooled_pred, subset)
                records += [{"row": row, "seed": seed, "tenant_id": tenant, "ring_id": rid,
                             "tenant": rid in got_t, "pooled": rid in got_p,
                             "tenant_cov": got_t.get(rid, np.nan), "pooled_cov": got_p.get(rid, np.nan)}
                            for rid in subset]
    df = pd.DataFrame(records)

    # The reused ring sets must reproduce every registered recall row exactly.
    for row in SPECS:
        pairs = df[df["row"] == row].groupby(["tenant_id", "ring_id"], as_index=False)[["tenant", "pooled"]].mean()
        again = r10.bootstrap(pairs)
        for part in ("tenant", "pooled", "difference"):
            if again[part] != registered["rows"][row][part]:
                raise SystemExit(f"{row}/{part} does not reproduce: {again[part]} vs {registered['rows'][row][part]}")

    def cov_frame(d: pd.DataFrame, side: str) -> pd.DataFrame:
        hit = d[d[side]]
        return pd.DataFrame({"ring_id": hit["ring_id"], "num": hit[f"{side}_cov"], "den": 1.0})

    rows, per_tenant = {}, []
    for row in SPECS:
        d = df[df["row"] == row]
        cov = boot_ratio({"tenant": cov_frame(d, "tenant"), "pooled": cov_frame(d, "pooled")})
        rows[row] = {"member_coverage_tenant": cov["tenant"], "member_coverage_pooled": cov["pooled"]}
        for tenant, g in d.groupby("tenant_id"):
            t, p = g[g["tenant"]], g[g["pooled"]]
            per_tenant.append({"row": row, "tenant_id": int(tenant),
                               "member_coverage_tenant": round(float(t["tenant_cov"].mean()), 4) if len(t) else None,
                               "member_coverage_pooled": round(float(p["pooled_cov"].mean()), 4) if len(p) else None,
                               "n_matched_tenant": int(len(t)), "n_matched_pooled": int(len(p))})

    # (a) vs (b): paired by tenant-ring pair, indicators averaged over seeds as registered.
    a = df[df["row"] == "pooled_scores"].groupby(["tenant_id", "ring_id"])["tenant"].mean().rename("a")
    b = df[df["row"] == "primary"].groupby(["tenant_id", "ring_id"])["tenant"].mean().rename("b")
    ab = pd.concat([a, b], axis=1).reset_index()
    diff = boot_ratio({"a": ab.assign(num=ab["a"], den=1.0), "b": ab.assign(num=ab["b"], den=1.0),
                       "a_minus_b": ab.assign(num=ab["a"] - ab["b"], den=1.0)})
    rows["a_vs_b"] = {"tenants": list(r10.PRIMARY), "n_pairs": int(len(ab)), "n_rings": int(ab["ring_id"].nunique()),
                      "a": diff["a"], "b": diff["b"], "difference": diff["a_minus_b"]}

    gt = pd.read_parquet(r10.TRUTH, columns=["ring_id", "from_bank", "to_bank", "timestamp_int"])
    gt = gt[gt["ring_id"].isin(truth) & gt["timestamp_int"].between(lo, hi)]
    visible = [{"tenant_id": t, "sets": [s for s, ts in (("primary", r10.PRIMARY), ("robustness", r10.ROBUSTNESS)) if t in ts],
                "in_scope_rings_with_visible_laundering_edge":
                    int(gt.loc[(gt["from_bank"] == t) | (gt["to_bank"] == t), "ring_id"].nunique()),
                "tenant_ring_pairs": int(sum(t in b for b in ring_banks.values()))}
               for t in sorted(set(r10.PRIMARY) | set(r10.ROBUSTNESS))]

    ring_sets = [{"path": p.relative_to(REPO_ROOT).as_posix(), "sha256": sha256(p)} for p in sorted(used)]
    manifest = hashlib.sha256("".join(f"{r['path']} {r['sha256']}\n" for r in ring_sets).encode()).hexdigest()
    result = {"label": LABEL, "created_utc": started.isoformat(timespec="seconds"),
              "wall_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
              "registered_result": {"path": REGISTERED.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_text(REGISTERED),
                                    "commit": "3156d75", "reproduced": True},
              "seeds": registered["seeds"], "window": window.as_dict(), "jaccard": r10.JACCARD, "n_boot": r10.N_BOOT,
              "rows": rows, "per_tenant": per_tenant, "visible_laundering": visible,
              "ring_sets": {"n": len(ring_sets), "manifest_sha256": manifest, "files": ring_sets}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("wall_seconds", "rows", "visible_laundering")}, indent=1))
    print("ring sets", len(ring_sets), "manifest", manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
