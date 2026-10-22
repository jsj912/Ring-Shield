"""R7: what survives when a whole pattern type is held out of training (Step 11).

    python evaluation/r7_heldout.py
    python evaluation/r7_heldout.py --arms all_patterns l3_cycle --dry-run

Three arms, deliberately different in character (`docs/GENERALISATION.md`):

    all_patterns   the shipped pipeline, nothing held out                      (the reference)
    l3_bipartite   detector frozen; the ring layer never trained on BIPARTITE  (a no-op: BIPARTITE
                   contributes 0 of 244 positive policy rows, so there was nothing to withhold)
    l3_cycle       detector frozen; the ring layer never trained on CYCLE      (the informative arm:
                   36 of 244 positives removed, every positive row CYCLE had)

Every arm uses the same frozen `R1_gine_causal` scores, so any difference is the ring layer's.

The pre-specified reading (fixed in `docs/GENERALISATION.md` before these numbers existed): for
the held-out pattern, **quiet-member recall and added-member precision are the evidence, not
ring-F1**. If CYCLE's quiet recall survives at comparable added-member precision, the expansion
policy generalises to a topology it never saw because it reasons about flow and timing rather
than shape. If quiet recall collapses while overall ring-F1 barely moves, the policy was fitting
shape and the claim fails.

**Added-member precision is computed on the held-out pattern's own rings**, not pooled: for every
prediction that matched a truth ring of pattern P, the share of its expanded edges that are true
member edges of that same truth ring. Pooled added-member precision is reported too, since it is
the number r6 uses, but it cannot attribute a wrong edge to a pattern and so cannot answer this
question on its own.

Outputs: `results/tables/r7_heldout.csv` (per arm x method x pattern, with bootstrap CIs over the
truth rings of that pattern) and `r7_heldout.json` (provenance, the held-out label mass, and the
per-arm policy CV scores).
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

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_metrics import match_rings  # noqa: E402
from evaluation.ring_stats import metrics_from_evidence, ring_evidence  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.holdout import Holdout  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R3 = REPO_ROOT / "experiments" / "R3_expansion" / "runs"
R4 = REPO_ROOT / "experiments" / "R4_partition" / "runs"
R7B = REPO_ROOT / "experiments" / "R7_l3only_bipartite" / "runs"
R7C = REPO_ROOT / "experiments" / "R7_l3only_cycle" / "runs"
TABLES = REPO_ROOT / "results" / "tables"

ARMS = {
    "all_patterns": {"held_out": None, "expand": R3 / "proposed", "full": R4 / "average"},
    "l3_bipartite": {"held_out": "BIPARTITE", "expand": R7B / "expand", "full": R7B / "full"},
    "l3_cycle": {"held_out": "CYCLE", "expand": R7C / "expand", "full": R7C / "full"},
}


def kept_index_map(rings, se: pd.DataFrame, window):
    """restrict_rings drops out-of-window predictions; return (restricted, original index per entry)."""
    ts = se.set_index("edge_id")["timestamp"]
    in_win = set(ts.index[window.mask(ts.values)].tolist())
    kept = [i for i, r in enumerate(rings) if any(e in in_win for e in r.member_edges)]
    pred = restrict_rings(rings, se, window)
    assert len(kept) == len(pred), f"restriction map {len(kept)} != {len(pred)}"
    return pred, kept, in_win


def added_member_precision_by_pattern(rings, se, truth, patterns, window, ring_edges: dict) -> dict:
    """{pattern: (n_expanded_edges_that_are_members_of_the_matched_ring, n_expanded_edges)}.

    Scoped to predictions that matched a truth ring, so a wrong edge can be attributed to the
    pattern whose ring the prediction was recovering."""
    pred, kept, in_win = kept_index_map(rings, se, window)
    matches, _, _ = match_rings(pred, truth, 0.5)
    out: dict = {}
    for m in matches:
        ring = rings[kept[m.pred_idx]]
        pat = patterns.get(m.truth_id, "?")
        exp = [e for e in ring.expanded_edges if e in in_win]
        if not exp:
            out.setdefault(pat, [0, 0])
            continue
        members = ring_edges.get(m.truth_id, set())
        ok = sum(1 for e in exp if e in members)
        d = out.setdefault(pat, [0, 0])
        d[0] += ok
        d[1] += len(exp)
    return {k: tuple(v) for k, v in out.items()}


def boot_pattern(evs, ids, metric: str, n: int, seed: int) -> tuple[float, float, float]:
    """Bootstrap a metric over the truth rings of one pattern, seeds averaged inside each resample."""
    ids = list(ids)
    if not ids:
        return float("nan"), float("nan"), float("nan")
    point = float(np.nanmean([metrics_from_evidence(ev, truth_ids=ids)[metric] for ev in evs]))
    rng = np.random.default_rng(seed)
    draws = np.empty(n)
    for b in range(n):
        res = [ids[i] for i in rng.integers(0, len(ids), len(ids))]
        draws[b] = np.nanmean([metrics_from_evidence(ev, truth_ids=res)[metric] for ev in evs])
    return point, float(np.nanpercentile(draws, 2.5)), float(np.nanpercentile(draws, 97.5))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arms", nargs="*", default=list(ARMS))
    ap.add_argument("--methods", nargs="*", default=["expand", "full"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--window", default="primary")
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=TABLES / "r7_heldout.csv")
    ap.add_argument("--dry-run", action="store_true", help="2 seeds, 50 resamples, writes nothing")
    a = ap.parse_args(argv)
    t0 = time.time()
    if a.dry_run:
        a.seeds, a.n_boot = a.seeds[:2], 50
    pdir = load_paths()["processed_dir"]
    W = load_windows()[a.window]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, a.scope, verbose=False)
    gt = pd.read_parquet(pdir / "amlworld_ring_ground_truth.parquet")
    te = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"])
    ring_edges = {int(r): set(g["EdgeID"].astype(int)) for r, g in te[te["ring_id"] > 0].groupby("ring_id")}
    by_pattern: dict = {}
    for tid in truth:
        by_pattern.setdefault(patterns.get(tid, "?"), []).append(tid)
    print(f"[r7] window {a.window} {W.bounds}: {len(truth)} truth rings over "
          f"{len(by_pattern)} patterns, seeds {a.seeds}")

    se_cache = {}
    rows, prov = [], {}
    for arm in a.arms:
        spec = ARMS[arm]
        ho = Holdout.load(spec["held_out"], processed_dir=pdir)
        for method in a.methods:
            root = spec[method]
            seeds = [s for s in a.seeds if (root / f"seed{s}" / "rings.parquet").exists()]
            if not seeds:
                print(f"  [skip] {arm}/{method}: nothing under {root}")
                continue
            evs, amp_all, amp_pat = [], [0, 0], {}
            for s in seeds:
                if s not in se_cache:
                    se_cache[s] = build_scored_edges(R1 / f"scores_test_seed{s}.parquet", "test",
                                                     model_id="gine_causal", seed=s, processed_dir=pdir)
                se = se_cache[s]
                rings = read_rings_any(root / f"seed{s}" / "rings.parquet")
                mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.1)
                evs.append(ring_evidence(rings, se, truth, W, method=f"{arm}/{method}", seed=s,
                                         seed_mask=mask, patterns=patterns, causal=True, truth_edges=gt))
                d = added_member_precision_by_pattern(rings, se, truth, patterns, W, ring_edges)
                for pat, (ok, tot) in d.items():
                    e = amp_pat.setdefault(pat, [0, 0])
                    e[0] += ok
                    e[1] += tot
                    amp_all[0] += ok
                    amp_all[1] += tot
            prov[f"{arm}/{method}"] = {"run_dir": str(root), "held_out": spec["held_out"],
                                       "n_seeds": len(seeds), **ho.summary()}
            for pat in sorted(by_pattern) + ["ALL"]:
                ids = list(truth) if pat == "ALL" else by_pattern[pat]
                r, r_lo, r_hi = boot_pattern(evs, ids, "ring_recall", a.n_boot, 0)
                q, q_lo, q_hi = boot_pattern(evs, ids, "quiet_member_recall", a.n_boot, 0)
                m0 = [metrics_from_evidence(ev, truth_ids=ids) for ev in evs]
                ok, tot = (amp_all if pat == "ALL" else amp_pat.get(pat, [0, 0]))
                rows.append({
                    "arm": arm, "held_out": spec["held_out"] or "-", "method": method, "pattern": pat,
                    "is_held_out_pattern": pat == spec["held_out"],
                    "n_truth_rings": len(ids), "n_seeds": len(seeds),
                    "ring_recall": r, "ring_recall_lo": r_lo, "ring_recall_hi": r_hi,
                    "ring_f1": float(np.nanmean([m["ring_f1"] for m in m0])) if pat == "ALL" else np.nan,
                    "quiet_member_recall": q, "quiet_lo": q_lo, "quiet_hi": q_hi,
                    "n_quiet": float(np.mean([m["n_quiet"] for m in m0])),
                    "n_quiet_found": float(np.mean([m["n_quiet_found"] for m in m0])),
                    "added_member_precision": (ok / tot) if tot else np.nan,
                    "n_added_member": ok, "n_added_total": tot})
            keep = [r for r in rows if r["arm"] == arm and r["method"] == method]
            allrow = [r for r in keep if r["pattern"] == "ALL"][0]
            print(f"  {arm:13s} {method:6s}: ring-F1 {allrow['ring_f1']:.4f} | quiet {allrow['quiet_member_recall']:.4f} "
                  f"| added-member P {allrow['added_member_precision']:.4f} ({allrow['n_added_total']} edges)", flush=True)
            if spec["held_out"]:
                h = [r for r in keep if r["pattern"] == spec["held_out"]][0]
                print(f"      held-out {spec['held_out']}: recall {h['ring_recall']:.4f} "
                      f"[{h['ring_recall_lo']:.4f}, {h['ring_recall_hi']:.4f}] | quiet {h['quiet_member_recall']:.4f} "
                      f"[{h['quiet_lo']:.4f}, {h['quiet_hi']:.4f}] ({h['n_quiet_found']:.1f}/{h['n_quiet']:.1f}) "
                      f"| added-member P {h['added_member_precision']:.4f} "
                      f"({h['n_added_member']}/{h['n_added_total']})", flush=True)

    d = pd.DataFrame(rows)
    if a.dry_run:
        print("\n[r7] DRY RUN -- nothing written")
        print(d[d["pattern"].isin(["ALL", "CYCLE", "BIPARTITE"])].to_string(index=False))
        return d
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
            "step": "11 (R7 held-out pattern)", "window": a.window, "scope": a.scope, "seeds": a.seeds,
            "n_bootstrap": a.n_boot, "detector": "R1_gine_causal (frozen in every arm)",
            "added_member_precision_definition":
                "per prediction that matched a truth ring of pattern P, the share of its in-window expanded "
                "edges that are member edges of that same truth ring; pooled over seeds",
            "pre_specified_reading": "docs/GENERALISATION.md -- for the held-out pattern the evidence is "
                                     "quiet-member recall and added-member precision, not ring-F1",
            "provenance": prov}
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    print(f"\n-> {a.out}  ({time.time() - t0:.0f}s)")
    return d


if __name__ == "__main__":
    main()
