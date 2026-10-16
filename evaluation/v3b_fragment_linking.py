"""V3.0b -- can the discarded fragments be linked? Measurement only; no linker is shipped.

    python evaluation/v3b_fragment_linking.py --dry-run     # seed 1, nothing written
    python evaluation/v3b_fragment_linking.py

Parts (a) and (b) of `docs/V3_DIAGNOSTICS.md` leave one question. The accounts of ~7.8 class (b)
rings per seed are already inside the shipped 0.1 % selection and are discarded because their
pieces do not connect; the shipped embedding cannot say which pieces belong together. This asks
whether anything else observable can.

(c1) **Where the discards go** -- the discarded seed-touched accounts attributed to the rule that
     drops them, with ring / non-ring composition per category.
(c2) **Validation reproduction** -- part (a)'s oracle bound recomputed on the val window, because
     any linker would be tuned there.
(c3) **Linking signals** -- a fragment is a dropped component. All fragment pairs within 72 h,
     labelled positive when both fragments belong to the same truth ring. Per-signal AUC against
     each negative type, then a grouped-CV gradient-boosted classifier on all signals.
(c4) **The pre-registered bars** -- combined AUC-PR against 5x the positive base rate, and a
     greedy linker at p >= 0.5 on the TRAINING window against >= 5 oracle rings at >= 80 % link
     precision. Both bars are read on the training window; nothing is chosen on test.

The pipeline is reproduced from the shipped configuration rather than approximated: `--verify`
asserts the rebuilt rings equal `rings.parquet` member-for-member before anything else runs.

Outputs `results/tables/v3b_discard_attribution.csv`, `v3b_val_oracle.csv`,
`v3b_signal_auc.csv`, `v3b_linker.csv` and `results/tables/v3b_fragment_linking.json`.
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
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_metrics import match_rings  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import (component_pairs, included_from_trajectories,  # noqa: E402
                                         partition_labels, rings_from_edge_clusters)
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

ROOT = REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average"
SCORES = REPO_ROOT / "experiments" / "R1_gine_causal"
POLICY_DIR = REPO_ROOT / "experiments" / "R3_expansion" / "policy_proposed"
AFFINITY_DIR = REPO_ROOT / "experiments" / "R4_partition" / "affinity"
INCLUDED_TRAIN = REPO_ROOT / "experiments" / "R4_partition" / "included_train.parquet"
MODEL_ID = "gine_causal"
SEED_PCT = 0.1
MIN_SIZE = 3
LINK_WINDOW_H = 72          # candidate pairs must be within this of each other
HOP_CAP = 4                 # undirected distance is reported capped here
NBR_CAP = 40_000            # max accounts kept in a fragment's 1- or 2-hop neighbourhood
NEG_CAP = 400_000           # max negatives kept per window (base rate restored by weighting)
GFP_COLS = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst",
            "scatter_gather", "gather_scatter", "temporal_cycle", "cycle_length"]

SIGNALS = ["neg_time_gap_h", "amount_ratio", "same_round_level", "min_round_level",
           "same_currency", "same_format", "bank_jaccard", "n_shared_counterparty",
           "neg_hop_distance", "gfp_cosine"]


# ============================================================ pipeline reproduction

def reproduce(split: str, seed: int, pdir: Path, cache: Path | None = None) -> dict:
    """Rebuild the shipped `full`/average pipeline for one split and detector seed.

    Returns the included-edge table (edge_id, component, cluster label, is_seed) and the ring
    member sets. Verified against `rings.parquet` on the test split by `--verify`."""
    tag = f"{split}_seed{seed}"
    if cache is not None and (cache / f"{tag}.parquet").exists():
        inc = pd.read_parquet(cache / f"{tag}.parquet")
        rings = json.loads((cache / f"{tag}.rings.json").read_text())
        return {"included": inc, "ring_members": [set(r) for r in rings]}

    cfg = yaml.safe_load((ROOT / f"seed{seed}" / "config.yaml").read_text(encoding="utf-8"))
    ch = cfg["chosen"]
    hc = cfg["context"][split]["head_constants"]
    df = build_scored_edges(SCORES / f"scores_{split}_seed{seed}.parquet", split,
                            model_id=MODEL_ID, seed=seed, processed_dir=pdir)
    ctx = build_context(df, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                        embeddings_parquet=SCORES / f"embeddings_{split}_seed{seed}.parquet",
                        head_constants=hc)
    pol, aff = Policy.load(POLICY_DIR), Affinity.load(AFFINITY_DIR)
    mask = seed_mask_for_pct(df[SELECT_COL].to_numpy(float), float(ch["seed_frac_pct"]))
    trajs = expand_all(df, mask, pol, ctx, delta_t_h=float(ch["delta_t_h"]),
                       p_floor=float(ch["p_min"]))
    inc_pos, is_seed = included_from_trajectories(df, mask, trajs, float(ch["p_min"]))
    comp = components_of(ctx.idx, inc_pos)
    P = component_pairs(ctx, inc_pos, is_seed, comp, aff)
    lab = partition_labels(ctx, inc_pos, is_seed, comp, method=ch["method"], pairs=P,
                           seed=int(cfg["cluster_seed"]), min_members=int(ch["min_size"]),
                           cut=float(ch["cut"]))
    rings = rings_from_edge_clusters(df, ctx.idx, inc_pos, is_seed, lab, int(ch["min_size"]))
    # idx.from_dense is a DENSE index into idx.acc_uniq, not an account id -- use idx.from_id
    inc = pd.DataFrame({"edge_id": ctx.idx.edge_id[inc_pos].astype(np.int64),
                        "component": comp.astype(np.int64), "label": lab.astype(np.int64),
                        "is_seed": is_seed.astype(bool),
                        "from_id": ctx.idx.from_id[inc_pos].astype(np.int64),
                        "to_id": ctx.idx.to_id[inc_pos].astype(np.int64),
                        "timestamp": ctx.idx.ts[inc_pos].astype(np.int64)})
    out = {"included": inc, "ring_members": [set(r.members) for r in rings],
           "n_seeds": int(mask.sum()), "chosen": ch}
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        inc.to_parquet(cache / f"{tag}.parquet", index=False)
        (cache / f"{tag}.rings.json").write_text(
            json.dumps([sorted(int(x) for x in m) for m in out["ring_members"]]))
    del df, ctx, trajs
    gc.collect()
    return out


def verify(seed: int, pdir: Path, cache: Path | None) -> bool:
    """The rebuilt test rings must equal the shipped `rings.parquet`, member set for member set."""
    got = reproduce("test", seed, pdir, cache)
    ship = read_rings_any(ROOT / f"seed{seed}" / "rings.parquet")
    a = sorted(tuple(sorted(m)) for m in got["ring_members"])
    b = sorted(tuple(sorted(r.members)) for r in ship)
    ok = a == b
    print(f"[verify] seed {seed}: rebuilt {len(a)} rings, shipped {len(b)} -- "
          f"{'MATCH' if ok else 'DIFFER'}")
    return ok


# ============================================================ (c1) discard attribution

def attribute_discards(seeds, truth, patterns, W, pdir, cache) -> pd.DataFrame:
    """Every seed-touched account that reaches no prediction, by the rule that drops it."""
    rows = []
    ring_pool = {a for accs in truth.values() for a in accs}
    for s in seeds:
        rep = reproduce("test", s, pdir, cache)
        inc, ring_members = rep["included"], rep["ring_members"]
        in_ring = {a for m in ring_members for a in m}
        se = build_scored_edges(SCORES / f"scores_test_seed{s}.parquet", "test",
                                model_id=MODEL_ID, seed=s, processed_dir=pdir)
        inw = W.mask(se["timestamp"].to_numpy())
        mask_all = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), SEED_PCT)
        sd = se[mask_all & inw]
        seed_accounts = set(sd["from_id"]) | set(sd["to_id"])

        # component / cluster geometry, per account
        comp_accounts, comp_pairs_n = defaultdict(set), defaultdict(set)
        for r in inc.itertuples():
            comp_accounts[r.component].update((r.from_id, r.to_id))
            comp_pairs_n[r.component].add((min(r.from_id, r.to_id), max(r.from_id, r.to_id)))
        lab_accounts = defaultdict(set)
        for r in inc.itertuples():
            if r.label >= 0:
                lab_accounts[r.label].update((r.from_id, r.to_id))
        acct_comp, acct_labs = {}, defaultdict(set)
        for r in inc.itertuples():
            for a in (r.from_id, r.to_id):
                acct_comp[a] = r.component
                acct_labs[a].add(r.label)

        for a in sorted(seed_accounts):
            if a in in_ring:
                continue
            c = acct_comp.get(a)
            if c is None:
                cat = "no_included_edge"          # seed edge dropped before the graph (cannot happen)
            elif len(comp_accounts[c]) < MIN_SIZE:
                cat = ("component_1edge_2accounts"
                       if len(comp_pairs_n[c]) == 1 and len(comp_accounts[c]) == 2
                       else "component_below_min_size_other")
            elif all(L < 0 for L in acct_labs[a]):
                cat = "partition_dropped_edge"
            elif max((len(lab_accounts[L]) for L in acct_labs[a] if L >= 0), default=0) < MIN_SIZE:
                cat = "cluster_below_min_size"
            else:
                cat = "other"
            rows.append({"seed": s, "account": int(a), "category": cat,
                         "in_ring": a in ring_pool,
                         "comp_accounts": len(comp_accounts.get(c, ())) if c is not None else 0,
                         "comp_pairs": len(comp_pairs_n.get(c, ())) if c is not None else 0})
        print(f"  (c1) seed {s}: {len(seed_accounts)} seed-touched accounts, "
              f"{sum(1 for a in seed_accounts if a not in in_ring)} discarded", flush=True)
    return pd.DataFrame(rows)


# ============================================================ (c2) validation oracle

def val_oracle(seeds, pdir, cache) -> pd.DataFrame:
    """Part (a)'s oracle bound on the val window: untouched val rings with >= 3 members and
    >= half the ring inside the seed-touched account set."""
    Wv = load_windows()["val"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *Wv.bounds,
                                        "test_visible", verbose=False)
    rows = []
    for s in seeds:
        rep = reproduce("val", s, pdir, cache)
        se = build_scored_edges(SCORES / f"scores_val_seed{s}.parquet", "val",
                                model_id=MODEL_ID, seed=s, processed_dir=pdir)
        inw = Wv.mask(se["timestamp"].to_numpy())
        mask_all = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), SEED_PCT)
        sd = se[mask_all & inw]
        seed_accounts = set(sd["from_id"]) | set(sd["to_id"])
        pred = [m for m in rep["ring_members"] if m]
        matched = {m.truth_id for m in match_rings(pred, truth, 0.5)[0]}
        touched = {a for m in pred for a in m}
        n_b, n_ge3, n_oracle = 0, 0, 0
        for tid, accs in truth.items():
            if tid in matched or len(accs) < MIN_SIZE or (accs & touched):
                continue
            n_b += 1
            k = len(accs & seed_accounts)
            if k >= MIN_SIZE:
                n_ge3 += 1
                if k / len(accs) >= 0.5:
                    n_oracle += 1
        rows.append({"seed": s, "window": "val", "n_truth_rings": len(truth),
                     "n_seed_edges_whole_split": int(mask_all.sum()),
                     "n_seed_edges_in_window": int((mask_all & inw).sum()),
                     "n_seed_accounts": len(seed_accounts), "n_predictions": len(pred),
                     "n_matched": len(matched), "n_class_b": n_b,
                     "n_class_b_ge3_in_seed_accounts": n_ge3, "n_class_b_oracle": n_oracle,
                     "share_class_b_oracle": n_oracle / max(n_b, 1)})
        print(f"  (c2) seed {s} val: {len(truth)} truth rings, {len(pred)} predictions, "
              f"class (b) {n_b}, oracle {n_oracle}", flush=True)
    return pd.DataFrame(rows)


# ============================================================ full-graph neighbourhoods

class FullGraph:
    """Undirected adjacency over all 18 days (train + val + test), CSR, atemporal."""

    def __init__(self, pdir: Path):
        cols = ["from_id", "to_id"]
        parts = []
        for sp in ("train", "val", "test"):
            d = pd.read_parquet(pdir / f"amlworld_{sp}.parquet", columns=["from_id", "to_id"])
            parts.append(d)
        e = pd.concat(parts, ignore_index=True)
        f = e["from_id"].to_numpy(np.int64)
        t = e["to_id"].to_numpy(np.int64)
        n = int(max(f.max(), t.max())) + 1
        src = np.concatenate([f, t])
        dst = np.concatenate([t, f])
        order = np.argsort(src, kind="stable")
        self.dst = dst[order]
        self.indptr = np.zeros(n + 1, dtype=np.int64)
        np.add.at(self.indptr, src + 1, 1)
        np.cumsum(self.indptr, out=self.indptr)
        self.n = n
        print(f"[graph] {len(e):,} edges over {n:,} account ids", flush=True)
        del e, parts, src, dst, order
        gc.collect()

    def nbrs(self, nodes: np.ndarray) -> np.ndarray:
        out = [self.dst[self.indptr[a]:self.indptr[a + 1]] for a in nodes if a < self.n]
        return np.unique(np.concatenate(out)) if out else np.zeros(0, np.int64)

    def hood(self, nodes, hops: int, cap: int = NBR_CAP) -> set:
        """Accounts within `hops` of `nodes`, inclusive, truncated at `cap`."""
        seen = np.unique(np.asarray(sorted(nodes), dtype=np.int64))
        frontier = seen
        for _ in range(hops):
            nxt = self.nbrs(frontier)
            nxt = nxt[~np.isin(nxt, seen)]
            if len(nxt) == 0:
                break
            seen = np.union1d(seen, nxt)
            if len(seen) > cap:
                return set(seen[:cap].tolist())
            frontier = nxt
        return set(seen.tolist())


# ============================================================ (c3) fragments and pairs

def round_level(x: float) -> int:
    """Trailing zeros of the amount in cents, capped at 6 -- how 'round' the figure is.

    Measured in cents because only 1.3 % of HI-Small amounts are whole currency units and
    0.014 % are multiples of 100, so a divisibility test on the unit scale is constant-zero on
    this data and carries no information at all."""
    v = int(round(float(x) * 100))
    if v <= 0:
        return 0
    k = 0
    while k < 6 and v % (10 ** (k + 1)) == 0:
        k += 1
    return k


def build_fragments(inc: pd.DataFrame, kept_accounts: set, attrs: pd.DataFrame,
                    gfp: pd.DataFrame) -> pd.DataFrame:
    """One row per DROPPED component: the accounts, times, amounts and attributes of its edges."""
    inc = inc.merge(attrs, on="edge_id", how="left", suffixes=("", "_a"))
    rows = []
    for c, g in inc.groupby("component"):
        accs = set(g["from_id"]) | set(g["to_id"])
        if accs & kept_accounts:                 # this component produced (part of) a ring
            continue
        rid = g.loc[g["ring_id"] > 0, "ring_id"]
        ring = int(rid.mode().iloc[0]) if len(rid) else 0
        gv = gfp.reindex(g["edge_id"].to_numpy())
        rows.append({
            "component": int(c), "accounts": sorted(int(a) for a in accs),
            "n_edges": len(g), "ring_id": ring,
            "t_min": int(g["timestamp"].min()), "t_max": int(g["timestamp"].max()),
            "amount": float(g["amount_received"].median()),
            "currencies": frozenset(g["currency_received"].dropna().astype(int)),
            "formats": frozenset(g["payment_format"].dropna().astype(int)),
            "banks": frozenset(pd.concat([g["from_bank"], g["to_bank"]]).dropna().astype(int)),
            "gfp": np.log1p(gv.to_numpy(float)).mean(axis=0) if len(gv) else np.zeros(len(GFP_COLS)),
        })
    return pd.DataFrame(rows)


def _incidence(lists: list, key_index: dict):
    """Sparse fragment x key incidence matrix."""
    from scipy.sparse import csr_matrix
    rows, cols = [], []
    for i, ks in enumerate(lists):
        for k in ks:
            j = key_index.get(k)
            if j is not None:
                rows.append(i)
                cols.append(j)
    return csr_matrix((np.ones(len(rows), np.int32), (rows, cols)),
                      shape=(len(lists), len(key_index)))


def _co_counts(lists: list, n: int, other: list | None = None, dtype=np.int32) -> np.ndarray:
    """n x n matrix counting, for each fragment pair, the keys they share.

    `lists[i]` is fragment i's key set (accounts, banks, ...). Computed as a sparse incidence
    product rather than per-pair set intersections, so a hub key sitting in a thousand
    fragments costs one column of a sparse matmul instead of a million intersections. With
    `other`, the count is over lists[i] x other[j] and the result is NOT symmetric."""
    keys = set()
    for ks in lists:
        keys |= set(ks)
    if other is not None:
        ok = set()
        for ks in other:
            ok |= set(ks)
        keys &= ok                                  # only keys that can contribute to a product
    key_index = {k: j for j, k in enumerate(sorted(keys))}
    if not key_index:
        return np.zeros((n, n), dtype=dtype)
    A = _incidence(lists, key_index)
    B = A if other is None else _incidence(other, key_index)
    return np.asarray((A @ B.T).todense()).astype(dtype)


def pair_table(frags: pd.DataFrame, G: FullGraph, rng) -> pd.DataFrame:
    """Every fragment pair within LINK_WINDOW_H, with every signal. No subsampling: all
    candidate pairs are kept, so the positive base rate and AUC-PR are those of the real
    candidate set and `weight` is 1 throughout."""
    n = len(frags)
    accs = frags["accounts"].tolist()
    print(f"  (c3) {n} fragments: building 1- and 2-hop neighbourhoods", flush=True)
    h1 = [G.hood(np.asarray(a, np.int64), 1) for a in accs]
    h2 = [G.hood(np.asarray(a, np.int64), 2) for a in accs]
    trunc = sum(1 for s in h2 if len(s) >= NBR_CAP)
    print(f"      |N1| median {int(np.median([len(s) for s in h1]))}, "
          f"|N2| median {int(np.median([len(s) for s in h2]))}, "
          f"{trunc} fragments hit the {NBR_CAP} cap", flush=True)

    own = [set(a) for a in accs]
    C11 = _co_counts(h1, n)                                   # shared 1-hop neighbours
    A_own_B1 = _co_counts(own, n, other=h1, dtype=np.int8)    # dist <= 1
    H21 = _co_counts(h2, n, other=h1, dtype=np.int8)          # dist <= 3
    H22 = _co_counts(h2, n, dtype=np.int8)                    # dist <= 4
    own_in_both = _co_counts(own, n, other=h1, dtype=np.int8)
    d1 = (A_own_B1 > 0) | (A_own_B1.T > 0)
    d2 = C11 > 0
    d3 = (H21 > 0) | (H21.T > 0)
    d4 = H22 > 0
    hop_m = np.full((n, n), HOP_CAP + 1, dtype=np.int8)
    hop_m[d4] = 4
    hop_m[d3] = 3
    hop_m[d2] = 2
    hop_m[d1] = 1
    shared_m = C11 - own_in_both - own_in_both.T              # exclude the fragments' own accounts
    bankM = _co_counts(frags["banks"].tolist(), n, dtype=np.int16)
    curM = _co_counts(frags["currencies"].tolist(), n, dtype=np.int16)
    fmtM = _co_counts(frags["formats"].tolist(), n, dtype=np.int16)
    nbank = np.array([len(b) for b in frags["banks"]], dtype=np.int32)

    tmin, tmax = frags["t_min"].to_numpy(np.int64), frags["t_max"].to_numpy(np.int64)
    ring = frags["ring_id"].to_numpy(np.int64)
    ia, ib = np.triu_indices(n, k=1)
    gap = np.maximum(0, np.maximum(tmin[ib] - tmax[ia], tmin[ia] - tmax[ib]))
    keep = gap <= LINK_WINDOW_H * 3600
    ia, ib, gap = ia[keep], ib[keep], gap[keep]
    pos = (ring[ia] > 0) & (ring[ia] == ring[ib])
    both = (ring[ia] > 0) & (ring[ib] > 0)
    kind = np.where(pos, "positive",
                    np.where(both, "different_ring",
                             np.where((ring[ia] > 0) | (ring[ib] > 0),
                                      "ring_nonring", "nonring_nonring")))
    print(f"  (c3) {len(ia):,} candidate pairs within {LINK_WINDOW_H} h; "
          f"{int(pos.sum())} positive (base rate {pos.mean():.3e})", flush=True)

    amt = frags["amount"].to_numpy(float)
    lvl = np.array([round_level(x) for x in amt])
    gfpm = np.nan_to_num(np.stack(frags["gfp"].to_numpy()))
    gnorm = gfpm / np.maximum(np.linalg.norm(gfpm, axis=1, keepdims=True), 1e-12)
    lo = np.minimum(amt[ia], amt[ib])
    hi = np.maximum(amt[ia], amt[ib])
    union_bank = np.maximum(nbank[ia] + nbank[ib] - bankM[ia, ib], 1)
    return pd.DataFrame({
        "i": ia, "j": ib, "ring_i": ring[ia], "ring_j": ring[ib],
        "label": pos, "kind": kind, "weight": 1.0,
        "neg_time_gap_h": -gap / 3600.0,
        "amount_ratio": np.where(hi > 0, lo / np.maximum(hi, 1e-12), 0.0),
        "same_round_level": ((lvl[ia] == lvl[ib]) & (lvl[ia] >= 2)).astype(float),
        "min_round_level": np.minimum(lvl[ia], lvl[ib]).astype(float),
        "same_currency": (curM[ia, ib] > 0).astype(float),
        "same_format": (fmtM[ia, ib] > 0).astype(float),
        "bank_jaccard": bankM[ia, ib] / union_bank,
        "n_shared_counterparty": np.maximum(shared_m[ia, ib], 0).astype(float),
        "neg_hop_distance": -hop_m[ia, ib].astype(float),
        "gfp_cosine": np.einsum("ij,ij->i", gnorm[ia], gnorm[ib]),
    })


def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    if not len(pos) or not len(neg):
        return float("nan")
    r = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    n1, n0 = len(pos), len(neg)
    return float((r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def weighted_pr_auc(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """Average precision with per-row weights, so a subsampled negative counts for the rows it
    stands in for. Returns (AUC-PR, positive base rate) on the reconstructed full candidate set."""
    o = np.argsort(-p, kind="stable")
    y, w = y[o].astype(float), w[o]
    tp = np.cumsum(y * w)
    fp = np.cumsum((1 - y) * w)
    prec = tp / np.maximum(tp + fp, 1e-12)
    total_pos = float((y * w).sum())
    if total_pos <= 0:
        return float("nan"), 0.0
    rec = tp / total_pos
    ap = float(np.sum(np.diff(np.concatenate([[0.0], rec])) * prec))
    base = total_pos / float(w.sum())
    return ap, base


# ============================================================ (c3) signals and model

def edge_attrs(split: str, pdir: Path) -> pd.DataFrame:
    """Edge attributes the signals need, keyed by edge_id."""
    d = pd.read_parquet(pdir / f"amlworld_{split}.parquet",
                        columns=["EdgeID", "from_bank", "to_bank", "Amount Received",
                                 "Received Currency", "Payment Format", "ring_id"])
    return d.rename(columns={"EdgeID": "edge_id", "Amount Received": "amount_received",
                             "Received Currency": "currency_received",
                             "Payment Format": "payment_format"})


def gfp_table(split: str, pdir: Path) -> pd.DataFrame:
    g = pd.read_parquet(pdir / f"amlworld_gfp_features_{split}.parquet")
    return g.set_index("EdgeID")[GFP_COLS]


def train_included(pdir: Path) -> tuple[pd.DataFrame, set]:
    """The training-window construction, built the same way from the cross-scored seeds:
    3,251 within-fold 0.1 % seeds + the out-of-fold expansion, in 2,009 components
    (`experiments/R4_partition/included_train.parquet`). No partition labels were stored for
    train, so a component reaching `min_size` accounts stands in for 'produced a ring' -- (c1)
    measures how much that approximation misses on test."""
    inc = pd.read_parquet(INCLUDED_TRAIN)
    tr = pd.read_parquet(pdir / "amlworld_train.parquet",
                         columns=["EdgeID", "from_id", "to_id", "Timestamp"]).rename(
        columns={"EdgeID": "edge_id", "Timestamp": "timestamp"})
    inc = inc.merge(tr, on="edge_id", how="left")
    kept = set()
    for _, g in inc.groupby("component"):
        accs = set(g["from_id"]) | set(g["to_id"])
        if len(accs) >= MIN_SIZE:
            kept |= accs
    return inc, kept


def fit_grouped(pairs: pd.DataFrame, rng, n_splits: int = 5):
    """Gradient-boosted classifier, grouped CV. A group is the ring the pair involves (the first
    ring id present), so no ring's pairs appear in both the fit and the held-out fold; non-ring
    pairs are spread round-robin. Returns out-of-fold probabilities and the per-fold AUCs."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold
    X = pairs[SIGNALS].to_numpy(float)
    y = pairs["label"].to_numpy(bool)
    w = pairs["weight"].to_numpy(float)
    grp = np.where(pairs["ring_i"].to_numpy() > 0, pairs["ring_i"].to_numpy(),
                   pairs["ring_j"].to_numpy())
    nonring = grp <= 0
    grp = grp.astype(np.int64).copy()
    grp[nonring] = -(1 + (np.arange(nonring.sum()) % (n_splits * 20)))
    oof = np.full(len(pairs), np.nan)
    folds = []
    gkf = GroupKFold(n_splits=n_splits)
    for f, (tr, te) in enumerate(gkf.split(X, y, groups=grp)):
        if y[tr].sum() == 0 or y[te].sum() == 0:
            folds.append({"fold": f, "n_train": len(tr), "n_test": len(te),
                          "n_pos_test": int(y[te].sum()), "auc": np.nan, "auc_pr": np.nan})
            continue
        m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_depth=4,
                                           l2_regularization=1.0, random_state=0)
        m.fit(X[tr], y[tr], sample_weight=w[tr])
        p = m.predict_proba(X[te])[:, 1]
        oof[te] = p
        ap, base = weighted_pr_auc(y[te], p, w[te])
        folds.append({"fold": f, "n_train": len(tr), "n_test": len(te),
                      "n_pos_test": int(y[te].sum()),
                      "auc": auc(p[y[te]], p[~y[te]]), "auc_pr": ap, "base_rate": base})
    return oof, pd.DataFrame(folds)


def greedy_link(pairs: pd.DataFrame, prob: np.ndarray, frags: pd.DataFrame, truth: dict,
                cut: float | None = 0.5, top_k: int | None = None) -> dict:
    """Accept pairs above `cut` (or the `top_k` highest-scoring pairs) in descending probability,
    union-find the fragments, then ask what the merged groups recover. Link precision is over
    accepted links; a group matches a truth ring at the usual Jaccard 0.5 bar over accounts."""
    valid = np.flatnonzero(~np.isnan(prob))
    if top_k is not None:
        ok = valid[np.argsort(-prob[valid], kind="stable")][:top_k]
    else:
        ok = np.flatnonzero(~np.isnan(prob) & (prob >= cut))
        ok = ok[np.argsort(-prob[ok], kind="stable")]
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    n_true = 0
    for k in ok:
        i, j = int(pairs["i"].iloc[k]), int(pairs["j"].iloc[k])
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a
        n_true += bool(pairs["label"].iloc[k])
    groups = defaultdict(set)
    accs = frags["accounts"].tolist()
    for i in range(len(frags)):
        groups[find(i)].add(i)
    preds = []
    for g in groups.values():
        s = set()
        for i in g:
            s |= set(accs[i])
        if len(s) >= MIN_SIZE and len(g) > 1:
            preds.append(s)
    matched, oracle_like = set(), set()
    for tid, t in truth.items():
        for P in preds:
            inter = len(P & t)
            if inter and inter / len(P | t) >= 0.5:
                matched.add(tid)
            if inter >= MIN_SIZE and inter / len(t) >= 0.5:
                oracle_like.add(tid)
    return {"n_links": int(len(ok)), "n_links_true": int(n_true),
            "link_precision": float(n_true / len(ok)) if len(ok) else float("nan"),
            "n_merged_groups": int(len(preds)),
            "n_rings_matched_j50": int(len(matched)),
            "n_rings_oracle_like": int(len(oracle_like))}


def window_fragments(name, inc, kept, attrs, gfp, G, rng):
    frags = build_fragments(inc, kept, attrs, gfp)
    print(f"  (c3) {name}: {len(frags)} dropped fragments "
          f"({int((frags['ring_id'] > 0).sum())} on a truth ring)", flush=True)
    return frags, pair_table(frags, G, rng)


def part_c3(seeds, truth, pdir, cache, rng, dry):
    G = FullGraph(pdir)
    sig_rows, lnk_rows, extra = [], [], {}

    # ---- training window: the construction the bars are read on
    inc_tr, kept_tr = train_included(pdir)
    Wtr = (int(inc_tr["timestamp"].min()), int(inc_tr["timestamp"].max()))
    truth_tr, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet",
                                    *Wtr, "test_visible", verbose=False)
    ftr, ptr = window_fragments("train", inc_tr, kept_tr, edge_attrs("train", pdir),
                                gfp_table("train", pdir), G, rng)
    for s in SIGNALS:
        for k in ("different_ring", "ring_nonring", "nonring_nonring"):
            m = ptr["kind"] == k
            sig_rows.append({"window": "train", "signal": s, "negative": k,
                             "n_pos": int(ptr["label"].sum()), "n_neg": int(m.sum()),
                             "auc": auc(ptr.loc[ptr["label"], s].to_numpy(),
                                        ptr.loc[m, s].to_numpy())})
    oof, folds = fit_grouped(ptr, rng)
    ap, base = weighted_pr_auc(ptr["label"].to_numpy(bool), np.nan_to_num(oof, nan=0.0),
                               ptr["weight"].to_numpy(float))
    pooled_auc = auc(oof[ptr["label"].to_numpy(bool) & ~np.isnan(oof)],
                     oof[~ptr["label"].to_numpy(bool) & ~np.isnan(oof)])
    print(f"\n  (c3) train combined model: pooled AUC {pooled_auc:.4f}, AUC-PR {ap:.5f}, "
          f"base rate {base:.2e}, ratio {ap / max(base, 1e-12):.2f}x")
    print(folds.round(4).to_string(index=False))

    # oracle rings on the training window, and what the greedy linker recovers
    seed_tr = set(inc_tr.loc[inc_tr["is_seed"], "from_id"]) | set(
        inc_tr.loc[inc_tr["is_seed"], "to_id"])
    kept_all = kept_tr
    n_oracle_tr = sum(1 for tid, t in truth_tr.items()
                      if not (t & kept_all) and len(t) >= MIN_SIZE
                      and len(t & seed_tr) >= MIN_SIZE and len(t & seed_tr) / len(t) >= 0.5)
    n_seed_equiv = float(inc_tr["is_seed"].sum()) / 864.0
    pmax = float(np.nanmax(oof))
    # The BAR is the 0.5 cut. The other cuts are reported so the failure is legible -- they are
    # not an operating point anyone chose, and nothing downstream reads them.
    n_pos = int(ptr["label"].sum())
    ops = [("prob>=0.5", dict(cut=0.5), True)] + \
          [(f"prob>={c}", dict(cut=c), False) for c in (0.1, 0.01, 0.005)] + \
          [(f"top{k}", dict(cut=None, top_k=k), False)
           for k in (50, 100, n_pos, 500, 2000)]
    for name, kw, is_bar in ops:
        link = greedy_link(ptr, oof, ftr, truth_tr, **kw)
        link.update({"window": "train", "operating_point": name, "is_the_bar": is_bar,
                     "n_oracle_rings": n_oracle_tr, "auc_pr": ap, "base_rate": base,
                     "auc_pr_over_base": ap / max(base, 1e-12), "pooled_auc": pooled_auc,
                     "max_oof_prob": pmax, "n_seeds": int(inc_tr["is_seed"].sum()),
                     "seed_equivalents": n_seed_equiv,
                     "rings_per_seed_equiv": link["n_rings_matched_j50"] / max(n_seed_equiv, 1e-9)})
        lnk_rows.append(link)
        pr = link["link_precision"]
        print(f"  (c3) train greedy linker {name:>10s}: {link['n_links']:5d} links, precision "
              f"{pr if link['n_links'] else float('nan'):.3f}, "
              f"rings matched {link['n_rings_matched_j50']}, "
              f"oracle-like {link['n_rings_oracle_like']}"
              + ("   <-- THE BAR" if is_bar else "   [diagnostic, not an operating point chosen]"))
    print(f"  (c3) oracle rings available on the training window: {n_oracle_tr}; "
          f"seed-equivalents {n_seed_equiv:.2f}; max out-of-fold probability {pmax:.4f}")

    # ---- test window: described only, never selected on
    attrs_te, gfp_te = edge_attrs("test", pdir), gfp_table("test", pdir)
    for s in (seeds[:1] if dry else seeds):
        rep = reproduce("test", s, pdir, cache)
        kept = {a for m in rep["ring_members"] for a in m}
        fte, pte = window_fragments(f"test seed {s}", rep["included"], kept, attrs_te, gfp_te,
                                    G, rng)
        for sg in SIGNALS:
            for k in ("different_ring", "ring_nonring", "nonring_nonring"):
                m = pte["kind"] == k
                sig_rows.append({"window": f"test_seed{s}", "signal": sg, "negative": k,
                                 "n_pos": int(pte["label"].sum()), "n_neg": int(m.sum()),
                                 "auc": auc(pte.loc[pte["label"], sg].to_numpy(),
                                            pte.loc[m, sg].to_numpy())})
    SIG = pd.DataFrame(sig_rows)
    print("\n== (c3) per-signal AUC, positive vs each negative type ==")
    piv = SIG[SIG["window"] != "train"].groupby(["signal", "negative"])["auc"].mean().unstack()
    tr_piv = SIG[SIG["window"] == "train"].set_index(["signal", "negative"])["auc"].unstack()
    print("train:\n" + tr_piv.round(4).to_string())
    print("\ntest (mean over seeds):\n" + piv.round(4).to_string())
    extra["signal_auc"] = json.loads(SIG.to_json(orient="records"))
    extra["linker"] = lnk_rows
    extra["cv_folds"] = json.loads(folds.to_json(orient="records"))
    return SIG, pd.DataFrame(lnk_rows), extra


# ============================================================ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--parts", nargs="+", default=["c1", "c2", "c3"],
                    choices=["c1", "c2", "c3"])
    ap.add_argument("--rng", type=int, default=20260930)
    ap.add_argument("--cache", type=Path,
                    default=Path("C:/Users/admin/AppData/Local/Temp/claude/E--JSJ-Ring-Shield/"
                                 "33a39003-fefe-4ae0-aaa0-9bea98394f45/scratchpad/v3b_cache"))
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "results" / "tables")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    seeds = a.seeds[:1] if a.dry_run else a.seeds
    rng = np.random.default_rng(a.rng)
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                        "test_visible", verbose=False)
    print(f"[v3b] primary window, {len(truth)} in-scope rings, seeds {seeds}")
    if not a.no_verify and not verify(seeds[0], pdir, a.cache):
        raise SystemExit("[v3b] pipeline reproduction does not match the shipped rings -- stopping")

    payload = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "seeds": seeds, "rng_seed": a.rng, "link_window_h": LINK_WINDOW_H,
               "hop_cap": HOP_CAP, "neg_cap": NEG_CAP,
               "note": "measurement only; bars read on the training window, nothing chosen on test"}
    D = V = SIG = LNK = None

    if "c1" in a.parts:
        D = attribute_discards(seeds, truth, patterns, W, pdir, a.cache)
        print("\n== (c1) discarded seed-touched accounts, by the rule that drops them ==")
        t = D.groupby("category").agg(n=("account", "size"),
                                      per_seed=("account", lambda v: len(v) / len(seeds)),
                                      in_ring=("in_ring", "sum"))
        t["share"] = (t["n"] / t["n"].sum()).round(4)
        t["ring_share"] = (t["in_ring"] / t["n"]).round(4)
        print(t.sort_values("n", ascending=False).to_string())
        payload["discard_attribution"] = json.loads(
            t.reset_index().to_json(orient="records"))

    if "c2" in a.parts:
        V = val_oracle(seeds, pdir, a.cache)
        print("\n== (c2) validation-window oracle ==")
        print(V.to_string(index=False))
        payload["val_oracle"] = json.loads(V.to_json(orient="records"))

    if "c3" in a.parts:
        SIG, LNK, extra = part_c3(seeds, truth, pdir, a.cache, rng, a.dry_run)
        payload.update(extra)

    if a.dry_run:
        print("\n[v3b] DRY RUN -- nothing written")
        return D, V, SIG, LNK
    a.out_dir.mkdir(parents=True, exist_ok=True)
    if D is not None:
        D.to_csv(a.out_dir / "v3b_discard_attribution.csv", index=False)
    if V is not None:
        V.to_csv(a.out_dir / "v3b_val_oracle.csv", index=False)
    if SIG is not None:
        SIG.to_csv(a.out_dir / "v3b_signal_auc.csv", index=False)
    if LNK is not None:
        LNK.to_csv(a.out_dir / "v3b_linker.csv", index=False)
    (a.out_dir / "v3b_fragment_linking.json").write_text(json.dumps(payload, indent=2, default=str),
                                                         encoding="utf-8")
    print(f"\n-> {a.out_dir / 'v3b_fragment_linking.json'}")
    return D, V, SIG, LNK


if __name__ == "__main__":
    main()
