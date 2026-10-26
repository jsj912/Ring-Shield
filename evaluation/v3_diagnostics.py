"""V3.0 -- two diagnostics on the shipped HI-Small artefacts. Measurement only; no new models.

    python evaluation/v3_diagnostics.py --dry-run     # seed 1, nothing written
    python evaluation/v3_diagnostics.py

(a) **Account-level reach.** The shipped `gine_causal` test scores, aggregated to accounts three
    ways (max edge score, sum of the top 3, count above the 1 % score quantile). How much of class
    (b) -- the untouched rings, `FINDINGS.md` B8 -- lands in the top 0.1 / 0.5 / 1 % of accounts
    and in a **budget-matched** tier (the number of accounts the shipped 0.1 % edge seeds already
    touch), against a null of licit accounts drawn to match the members' transaction counts.

(b) **Embedding grouping.** Cosine similarity between the shipped 198-dim edge embeddings of
    member edges of one ring that sit in **different connected components** of the ring's in-window
    edge graph (B13's disconnected pieces), against pairs from different rings and against
    score+timestamp-matched random non-ring pairs. AUC for "same ring vs different ring".

Nothing is chosen on test; both parts describe artefacts. The verdicts are pre-registered in
`docs/V3_DIAGNOSTICS.md` and were written before this file ran.

Outputs `results/tables/v3_account_reach.csv`, `results/tables/v3_embedding_grouping.csv`,
`results/tables/v3_ring_components.csv` and a combined `results/tables/v3_diagnostics.json`.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

ROOT = REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average"   # shipped `full` runs
SCORES = REPO_ROOT / "experiments" / "R1_gine_causal"
MODEL_ID = "gine_causal"
SEED_PCT = 0.1                 # the shipped seed budget, in per cent of edges
TIERS = (0.1, 0.5, 1.0)        # account tiers, in per cent of the account population
AGGS = ("max_score", "top3_sum", "n_above_q99")
MAX_PAIRS_PER_RING = 200       # cap on cross-component pairs drawn from one ring instance
N_NULL_DRAWS = 20              # repeats of the degree-matched licit null in (a)


# ----------------------------------------------------------------------------- shared

def in_window_edges(se: pd.DataFrame, W) -> pd.DataFrame:
    """The scored edges of the split that fall inside the evaluation window."""
    return se[W.mask(se["timestamp"].to_numpy())]


def edge_components(edges: pd.DataFrame) -> dict[int, int]:
    """{edge_id: component} over the ring's own edges; two edges adjacent when they share an
    account. Same construction as B13's control (`historical_bridge.in_window_disconnected`) --
    a component here is exactly a piece with no in-window path to the others."""
    parent: dict[int, int] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for e in edges["edge_id"]:
        parent[int(e)] = int(e)
    by_acct: dict[int, list[int]] = defaultdict(list)
    for r in edges.itertuples():
        by_acct[int(r.from_id)].append(int(r.edge_id))
        by_acct[int(r.to_id)].append(int(r.edge_id))
    for es in by_acct.values():
        for e in es[1:]:
            union(es[0], e)
    return {e: find(e) for e in parent}


# ----------------------------------------------------------------------------- (a)

def account_aggregates(ew: pd.DataFrame) -> pd.DataFrame:
    """Per-account max / top-3-sum / count-above-q99 over the account's in-window edges.

    An account's edges are the ones it sends *or* receives, so each edge contributes to two
    accounts."""
    s = ew[SELECT_COL].to_numpy(float)
    q99 = float(np.nanpercentile(s[~np.isnan(s)], 99.0))
    long = pd.concat([
        ew[["from_id", SELECT_COL]].rename(columns={"from_id": "account"}),
        ew[["to_id", SELECT_COL]].rename(columns={"to_id": "account"})], ignore_index=True)
    long = long.rename(columns={SELECT_COL: "score"}).dropna(subset=["score"])
    long["above"] = long["score"] > q99
    long = long.sort_values(["account", "score"], ascending=[True, False])
    g = long.groupby("account", sort=True)
    out = pd.DataFrame({
        "max_score": g["score"].max(),
        "top3_sum": g["score"].head(3).groupby(long["account"]).sum(),
        "n_above_q99": g["above"].sum().astype(int),
        "n_txn": g.size().astype(int)})
    return out.reset_index()


def rank_sets(acc: pd.DataFrame, tier_counts: dict[str, int]) -> dict[tuple[str, str], set]:
    """{(aggregate, tier): set of accounts}. Ties inside `n_above_q99` (mostly 0) break on
    `max_score` then account id, so the ranking is deterministic."""
    sets = {}
    for agg in AGGS:
        order = acc.sort_values([agg, "max_score", "account"], ascending=[False, False, True])
        ids = order["account"].to_numpy()
        for tname, n in tier_counts.items():
            sets[(agg, tname)] = set(ids[:n].tolist())
    return sets


def part_a(seeds, truth, patterns, W, pdir, rng):
    rows, meta = [], {}
    for s in seeds:
        se = build_scored_edges(SCORES / f"scores_test_seed{s}.parquet", "test",
                                model_id=MODEL_ID, seed=s, processed_dir=pdir)
        ew = in_window_edges(se, W)
        rings = read_rings_any(ROOT / f"seed{s}" / "rings.parquet")
        kl = classify(rings, se, truth, patterns, W)
        class_b = [int(t) for t in kl.loc[kl["klass"] == "b_untouched", "ring_id"]]

        acc = account_aggregates(ew)
        n_acc = len(acc)
        # SHIPPED convention: the quantile is taken over the WHOLE split (`run_partition` passes
        # all 863,900 test edges to `seed_mask_for_pct`), giving 864 seeds of which only ~463 fall
        # in the primary window -- the rest land in the day 10-17 tail, which holds 0.13 % of the
        # edges and 41 % of the positives (docs/TEST_TAIL.md). Selecting inside the window instead
        # would be a different, un-shipped rule; `under_covered.py` and `historical_bridge.py`
        # both use the whole-split mask intersected with the window, and so does this.
        mask_all = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), SEED_PCT)
        in_window_mask = W.mask(se["timestamp"].to_numpy())
        seed_edges = se[mask_all & in_window_mask]
        n_budget = len(set(seed_edges["from_id"]) | set(seed_edges["to_id"]))
        tier_counts = {f"top_{t}pct": max(1, int(round(n_acc * t / 100.0))) for t in TIERS}
        tier_counts["budget_matched"] = n_budget
        sets = rank_sets(acc, tier_counts)

        ring_accounts = {t: truth[t] for t in class_b}
        members = sorted({a for accs in ring_accounts.values() for a in accs})
        deg = acc.set_index("account")["n_txn"]
        ring_pool = {a for accs in truth.values() for a in accs}
        licit = acc[~acc["account"].isin(ring_pool)]
        by_deg = {int(d): g["account"].to_numpy() for d, g in licit.groupby("n_txn")}
        deg_keys = np.array(sorted(by_deg))

        def draw_matched(n_txn: int) -> int:
            """A licit account with the same in-window transaction count, or the nearest count."""
            d = int(n_txn)
            if d not in by_deg:
                d = int(deg_keys[np.abs(deg_keys - d).argmin()])
            pool = by_deg[d]
            return int(pool[rng.integers(len(pool))])

        seed_accounts = set(seed_edges["from_id"]) | set(seed_edges["to_id"])
        for (agg, tname), sel in sets.items():
            hit = np.array([1.0 if a in sel else 0.0 for a in members])
            per_ring = {t: sum(1 for a in accs if a in sel) for t, accs in ring_accounts.items()}
            n_ge3 = sum(1 for v in per_ring.values() if v >= 3)
            # ORACLE bound: if the tier's accounts for one ring were handed over as a perfect
            # prediction, purity is 1 by construction, so Jaccard == coverage. A ring clears the
            # 0.5 bar when >= 3 of its members are in the tier AND they are >= half the ring.
            n_oracle = sum(1 for t, v in per_ring.items()
                           if v >= 3 and v / len(ring_accounts[t]) >= 0.5)
            null_hits, null_ge3, null_oracle = [], [], []
            for _ in range(N_NULL_DRAWS):
                nh, ng, no, tot = 0, 0, 0, 0
                for t, accs in ring_accounts.items():
                    k = 0
                    for a in accs:
                        b = draw_matched(deg.get(a, 1))
                        tot += 1
                        if b in sel:
                            nh += 1
                            k += 1
                    if k >= 3:
                        ng += 1
                        if k / len(accs) >= 0.5:
                            no += 1
                null_hits.append(nh / max(tot, 1))
                null_ge3.append(ng)
                null_oracle.append(no)
            nh_mean = float(np.mean(null_hits))
            rows.append({
                "seed": s, "aggregate": agg, "tier": tname, "n_accounts_selected": len(sel),
                "n_accounts_total": n_acc, "n_class_b_rings": len(class_b),
                "n_member_accounts": len(members),
                "member_hit_rate": float(hit.mean()) if len(hit) else np.nan,
                "n_rings_ge3_in_tier": n_ge3,
                "share_rings_ge3": n_ge3 / max(len(class_b), 1),
                "n_rings_oracle_match": n_oracle,
                "share_rings_oracle_match": n_oracle / max(len(class_b), 1),
                "overlap_with_seed_accounts": len(sel & seed_accounts) / max(len(sel), 1),
                "null_hit_rate": nh_mean, "null_hit_rate_sd": float(np.std(null_hits)),
                "null_rings_ge3": float(np.mean(null_ge3)),
                "null_rings_oracle_match": float(np.mean(null_oracle)),
                "lift_over_null": (float(hit.mean()) / nh_mean) if nh_mean > 0 else np.inf})
        # how much of the seed set the aggregator keeps: an account can be an endpoint of a
        # selected edge and still reach no prediction, because `cc` drops components under
        # `min_size`. That gap is the whole of (a)'s mechanism, so it is recorded.
        ts = se.set_index("edge_id")["timestamp"]
        in_win = set(ts.index[W.mask(ts.values)].tolist())
        frm, to = se.set_index("edge_id")["from_id"], se.set_index("edge_id")["to_id"]
        inc = [e for r in rings for e in (r.seed_edges + r.expanded_edges) if e in in_win]
        pred_accounts = set(frm.loc[inc]) | set(to.loc[inc]) if inc else set()
        dropped = seed_accounts - pred_accounts
        meta[s] = {"n_accounts": int(n_acc), "n_seed_edges_whole_split": int(mask_all.sum()),
                   "n_seed_edges_in_window": int((mask_all & in_window_mask).sum()),
                   "n_budget_accounts": int(n_budget), "n_class_b": len(class_b),
                   "n_member_accounts": len(members),
                   "n_prediction_accounts": len(pred_accounts),
                   "n_seed_accounts_dropped": len(dropped),
                   # what the aggregator keeps vs throws away, by ring membership: the filter is
                   # not neutral, and the cost of relaxing it is on this line
                   "n_seed_accounts_in_a_ring": len(seed_accounts & ring_pool),
                   "n_kept_in_a_ring": len(pred_accounts & ring_pool),
                   "n_dropped_in_a_ring": len(dropped & ring_pool),
                   "n_dropped_class_b_members": len(dropped & set(members)),
                   "n_rings_touched_by_seed_accounts":
                       len({t for t, v in truth.items() if v & seed_accounts}),
                   "n_class_b_members_on_a_seed_edge": len(set(members) & seed_accounts),
                   "median_member_txn": float(np.median([deg.get(a, 0) for a in members])),
                   "tier_counts": {k: int(v) for k, v in tier_counts.items()}}
        print(f"  (a) seed {s}: {n_acc:,} accounts, "
              f"{int((mask_all & in_window_mask).sum())} of {int(mask_all.sum())} seed edges touch "
              f"{n_budget} accounts of which {len(pred_accounts)} reach a prediction; "
              f"class (b) {len(class_b)} rings / {len(members)} members, "
              f"{len(set(members) & seed_accounts)} of them on a seed edge", flush=True)
    return pd.DataFrame(rows), meta


# ----------------------------------------------------------------------------- (b)

def cosine(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    a = A / np.maximum(np.linalg.norm(A, axis=1, keepdims=True), 1e-12)
    b = B / np.maximum(np.linalg.norm(B, axis=1, keepdims=True), 1e-12)
    return np.einsum("ij,ij->i", a, b)


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(pos > neg) + 0.5 P(pos == neg), via ranks."""
    if not len(pos) or not len(neg):
        return float("nan")
    allv = np.concatenate([pos, neg])
    r = pd.Series(allv).rank().to_numpy()
    n1, n0 = len(pos), len(neg)
    return float((r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def load_embeddings(seed: int, edge_ids) -> dict[int, np.ndarray]:
    """{edge_id: vector} for the requested edges only. The parquet is one row group of 198
    float32 columns, so it is read once and the rows taken; the table is dropped before return."""
    import pyarrow.parquet as pq
    t = pq.read_table(SCORES / f"embeddings_test_seed{seed}.parquet")
    ids = t.column("edge_id").to_numpy()
    pos = pd.Series(np.arange(len(ids)), index=ids)
    take = pos.reindex(list(edge_ids)).dropna().astype(int)
    sub = t.take(take.to_numpy())
    cols = [c for c in sub.column_names if c.startswith("emb_")]
    M = np.column_stack([sub.column(c).to_numpy() for c in cols]).astype(np.float64)
    out = {int(e): M[i] for i, e in enumerate(take.index)}
    del t, sub, M
    gc.collect()
    return out


def part_b(seeds, truth, patterns, W, pdir, rng):
    te = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"])
    edge_ring = dict(zip(te["EdgeID"].astype(int), te["ring_id"].astype(int)))
    rows, comp_rows = [], []
    for s in seeds:
        se = build_scored_edges(SCORES / f"scores_test_seed{s}.parquet", "test",
                                model_id=MODEL_ID, seed=s, processed_dir=pdir)
        ew = in_window_edges(se, W).reset_index(drop=True)
        ew["ring_id"] = ew["edge_id"].map(edge_ring).fillna(0).astype(int)
        rings = read_rings_any(ROOT / f"seed{s}" / "rings.parquet")
        kl = classify(rings, se, truth, patterns, W).set_index("ring_id")
        pools = {"class_b": [int(t) for t in kl.index[kl["klass"] == "b_untouched"]],
                 "under_covered": [int(t) for t in kl.index[kl["klass"] == "c_under_covered"]]}

        # score-rank x hour bins over non-ring in-window edges, for the matched null
        nonring = ew[ew["ring_id"] <= 0]
        nr_rank = pd.Series(nonring[SELECT_COL].to_numpy(float)).rank(method="first")
        nr_rb = pd.qcut(nr_rank, 200, labels=False).to_numpy()
        nr_hb = ((nonring["timestamp"].to_numpy() - W.bounds[0]) // 3600).astype(int)
        nr_ids = nonring["edge_id"].to_numpy()
        frame = pd.DataFrame({"rb": nr_rb, "hb": nr_hb}, index=nr_ids)
        bins = {k: g.index.to_numpy() for k, g in frame.groupby(["rb", "hb"])}
        rb_only = {int(k): g.index.to_numpy() for k, g in frame.groupby("rb")}
        # the *target* edge's bin is read off the same non-ring rank scale, so a ring edge is
        # matched to non-ring edges of the same score rank, not of the same raw score
        nr_sorted = np.sort(nonring[SELECT_COL].to_numpy(float))
        all_sc = ew[SELECT_COL].to_numpy(float)
        tgt_rb = np.clip((np.searchsorted(nr_sorted, all_sc) / max(len(nr_sorted), 1) * 200)
                         .astype(int), 0, 199)
        tgt_hb = ((ew["timestamp"].to_numpy() - W.bounds[0]) // 3600).astype(int)
        eid_to_bin = dict(zip(ew["edge_id"].to_numpy(), zip(tgt_rb, tgt_hb)))

        def matched_draw(eid: int) -> int:
            rb, hb = eid_to_bin[int(eid)]
            pool = bins.get((int(rb), int(hb)))
            if pool is None or not len(pool):
                pool = rb_only.get(int(rb))
            if pool is None or not len(pool):
                return -1
            return int(pool[rng.integers(len(pool))])

        by_pool: dict[str, dict] = {}
        for pool_name, tids in pools.items():
            pos_pairs, samecomp_pairs = [], []
            ring_edge_lists: dict[int, list[int]] = {}
            for tid in tids:
                g = ew[ew["ring_id"] == tid]
                if len(g) < 2:
                    continue
                comp = edge_components(g[["edge_id", "from_id", "to_id"]])
                groups: dict[int, list[int]] = defaultdict(list)
                for e, c in comp.items():
                    groups[c].append(e)
                ring_edge_lists[tid] = sorted(comp)
                comp_rows.append({"seed": s, "pool": pool_name, "ring_id": tid,
                                  "pattern": patterns.get(tid, "?"), "n_edges": int(len(g)),
                                  "n_components": len(groups),
                                  "largest_component": max(len(v) for v in groups.values())})
                keys = sorted(groups)
                cross = [(x, y) for i, ka in enumerate(keys) for kb in keys[i + 1:]
                         for x in groups[ka] for y in groups[kb]]
                if len(cross) > MAX_PAIRS_PER_RING:
                    cross = [cross[i] for i in
                             rng.choice(len(cross), MAX_PAIRS_PER_RING, replace=False)]
                pos_pairs += [(tid, x, y) for x, y in cross]
                within = [(v[i], v[j]) for v in groups.values()
                          for i in range(len(v)) for j in range(i + 1, len(v))]
                if len(within) > MAX_PAIRS_PER_RING:
                    within = [within[i] for i in
                              rng.choice(len(within), MAX_PAIRS_PER_RING, replace=False)]
                samecomp_pairs += [(tid, x, y) for x, y in within]
            if not pos_pairs:
                print(f"  (b) seed {s} {pool_name}: no cross-component pairs", flush=True)
                continue
            # different-ring pairs: same marginal pool of ring edges, drawn across rings
            tid_list = [t for t, v in ring_edge_lists.items() if v]
            diff_pairs = []
            if len(tid_list) >= 2:
                for _ in range(len(pos_pairs)):
                    i, j = rng.choice(len(tid_list), 2, replace=False)
                    ta, tb = tid_list[i], tid_list[j]
                    diff_pairs.append((ta, int(rng.choice(ring_edge_lists[ta])),
                                       int(rng.choice(ring_edge_lists[tb]))))
            # score+time matched random non-ring pairs, one per positive pair
            rand_pairs = []
            for _, x, y in pos_pairs:
                fa, fb = matched_draw(x), matched_draw(y)
                if fa > 0 and fb > 0 and fa != fb:
                    rand_pairs.append((-1, fa, fb))

            by_pool[pool_name] = {"pos": pos_pairs, "same": samecomp_pairs,
                                  "diff": diff_pairs, "rand": rand_pairs}

        # one read of the 576 MB embedding parquet per seed, for both pools at once
        need = sorted({e for d in by_pool.values() for k in ("pos", "same", "diff", "rand")
                       for _, x, y in d[k] for e in (x, y)})
        if not need:
            continue
        emb = load_embeddings(s, need)
        for pool_name, d in by_pool.items():
            pos_pairs, samecomp_pairs = d["pos"], d["same"]
            diff_pairs, rand_pairs = d["diff"], d["rand"]

            def cos_of(pairs):
                pairs = [p for p in pairs if p[1] in emb and p[2] in emb]
                if not pairs:
                    return np.array([]), pairs
                A = np.stack([emb[x] for _, x, _ in pairs])
                B = np.stack([emb[y] for _, _, y in pairs])
                return cosine(A, B), pairs

            cp, pos_pairs = cos_of(pos_pairs)
            cs, samecomp_pairs = cos_of(samecomp_pairs)
            cd, diff_pairs = cos_of(diff_pairs)
            cr, rand_pairs = cos_of(rand_pairs)
            for name, v, pairs in (("same_ring_cross_component", cp, pos_pairs),
                                   ("same_ring_same_component", cs, samecomp_pairs),
                                   ("different_ring", cd, diff_pairs),
                                   ("matched_random_nonring", cr, rand_pairs)):
                if not len(v):
                    continue
                rows.append({
                    "seed": s, "pool": pool_name, "population": name, "n_pairs": int(len(v)),
                    "n_rings": (len({t for t, _, _ in pairs})
                                if name != "matched_random_nonring" else np.nan),
                    "cos_mean": float(v.mean()), "cos_sd": float(v.std()),
                    "cos_p25": float(np.percentile(v, 25)), "cos_median": float(np.median(v)),
                    "cos_p75": float(np.percentile(v, 75)),
                    "auc_vs_different_ring": (auc(v, cd) if name != "different_ring" and len(cd)
                                              else np.nan),
                    "auc_vs_matched_random": (auc(v, cr) if name != "matched_random_nonring"
                                              and len(cr) else np.nan)})
            print(f"  (b) seed {s} {pool_name}: {len(pos_pairs)} cross-component pairs over "
                  f"{len({t for t, _, _ in pos_pairs})} rings", flush=True)
        del emb
        gc.collect()
    return pd.DataFrame(rows), pd.DataFrame(comp_rows)


# ----------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--window", default="primary")
    ap.add_argument("--parts", nargs="+", default=["a", "b"], choices=["a", "b"])
    ap.add_argument("--rng", type=int, default=20260930)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "results" / "tables")
    ap.add_argument("--dry-run", action="store_true", help="seed 1 only; nothing written")
    a = ap.parse_args(argv)
    seeds = a.seeds[:1] if a.dry_run else a.seeds
    rng = np.random.default_rng(a.rng)
    pdir = load_paths()["processed_dir"]
    W = load_windows()[a.window]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                        "test_visible", verbose=False)
    print(f"[v3] window {a.window} days {W.day_lo}-{W.day_hi}, {len(truth)} in-scope rings, "
          f"seeds {seeds}")

    A = B = COMP = None
    meta_a: dict = {}
    if "a" in a.parts:
        A, meta_a = part_a(seeds, truth, patterns, W, pdir, rng)
        print("\n== (a) account-level reach: class (b) member accounts inside the tier (%) ==")
        print((A.pivot_table(index="tier", columns="aggregate",
                             values="member_hit_rate") * 100).round(2).to_string())
        print(f"\n   class (b) rings with >= 3 members in the tier "
              f"(mean per seed, of {A['n_class_b_rings'].mean():.1f}):")
        print(A.pivot_table(index="tier", columns="aggregate",
                            values="n_rings_ge3_in_tier").round(2).to_string())
        print("\n   class (b) rings clearing the Jaccard 0.5 bar as an ORACLE on the tier:")
        print(A.pivot_table(index="tier", columns="aggregate",
                            values="n_rings_oracle_match").round(2).to_string())
        print("\n   share of the tier that is already a seed-edge endpoint:")
        print(A.pivot_table(index="tier", columns="aggregate",
                            values="overlap_with_seed_accounts").round(3).to_string())
        print("\n   degree-matched licit null, member hit rate (%):")
        print((A.pivot_table(index="tier", columns="aggregate",
                             values="null_hit_rate") * 100).round(2).to_string())
        print("\n   lift over null:")
        print(A.pivot_table(index="tier", columns="aggregate",
                            values="lift_over_null").round(2).to_string())
    if "b" in a.parts:
        B, COMP = part_b(seeds, truth, patterns, W, pdir, rng)
        print("\n== (b) embedding grouping: cosine similarity ==")
        print(B.groupby(["pool", "population"]).agg(
            n_pairs=("n_pairs", "sum"), cos_mean=("cos_mean", "mean"),
            cos_median=("cos_median", "mean"),
            auc_vs_diff=("auc_vs_different_ring", "mean"),
            auc_vs_rand=("auc_vs_matched_random", "mean")).round(4).to_string())
        if len(COMP):
            print("\n   component structure of the ring instances:")
            print(COMP.groupby("pool").agg(
                n=("ring_id", "size"), median_edges=("n_edges", "median"),
                median_components=("n_components", "median"),
                share_multi=("n_components", lambda v: float((v > 1).mean()))).round(3).to_string())

    if a.dry_run:
        print("\n[v3] DRY RUN -- nothing written")
        return A, B, COMP
    a.out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "window": a.window, "scope": "test_visible", "seeds": seeds,
               "model": MODEL_ID, "runs": ROOT.relative_to(REPO_ROOT).as_posix(),
               "rng_seed": a.rng, "max_pairs_per_ring": MAX_PAIRS_PER_RING,
               "note": "measurement only; no model trained, no parameter chosen on test"}
    if A is not None:
        A.to_csv(a.out_dir / "v3_account_reach.csv", index=False)
        payload["account_reach"] = json.loads(A.to_json(orient="records"))
        payload["account_reach_meta"] = meta_a
    if B is not None:
        B.to_csv(a.out_dir / "v3_embedding_grouping.csv", index=False)
        COMP.to_csv(a.out_dir / "v3_ring_components.csv", index=False)
        payload["embedding_grouping"] = json.loads(B.to_json(orient="records"))
        payload["ring_components"] = json.loads(COMP.to_json(orient="records"))
    (a.out_dir / "v3_diagnostics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n-> {a.out_dir / 'v3_diagnostics.json'}")
    return A, B, COMP


if __name__ == "__main__":
    main()
