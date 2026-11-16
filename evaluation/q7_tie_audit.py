"""Q7: tie audit of the ring scorer's greedy one-to-one matching (read-only on the scorer).

    CUDA_VISIBLE_DEVICES="" python -m evaluation.q7_tie_audit

Shipped matcher: `evaluation.ring_metrics.match_rings` sorts candidate pairs (Jaccard >= tau) by
(-Jaccard, prediction index, str(truth id)) (ring_metrics.py:81) and consumes them greedily. Ties at
equal Jaccard are therefore broken by the prediction's position in the rings file.

For each row (full, proposed, B1b, B0, Louvain r0.5, LPA on expansion; plus the T-P2 pair), seeds 1-5,
primary window, tau 0.5, predictions restricted to the window exactly as the scorer does
(`score_external.load_predictions` -> `ringshield.evaluate.restrict_rings`):

  a. tie count: truth rings in a Jaccard tie the greedy matcher must break (count_forced_ties);
  b. 200 shuffles of the prediction order (numpy default_rng(20261115)): min / max / SD of the row's
     ring-F1 (mean of seeds, the scorer's point estimate) and of each decision difference (arms shuffled
     independently, draw by draw);
  c. optimal one-to-one matching (maximum cardinality at Jaccard >= tau, scipy
     maximum_bipartite_matching); ring-F1 and the gap to the shipped greedy.

Ring-F1 per run = 2PR/(P+R) with P = matched / restricted predictions, R = matched / targets
(`evaluation.ring_stats.metrics_from_evidence` on the full target set). Conventions: test_visible for
every row; component and component_ge3 as well for B0 and Louvain r0.5 (the T-P3 bar-A swaps).
Writes results/tables/q7_tie_audit.csv (rows) and q7_tie_audit_pairs.csv (differences).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

E2E = REPO_ROOT.parent / "RS-e2e" / "experiments"
ROWS = {
    "full": REPO_ROOT / "experiments/R4_partition/runs/average/seed{S}/rings.parquet",
    "proposed": E2E / "R3_expansion/runs/proposed/seed{S}/rings.parquet",
    "B1b": E2E / "R3_expansion/runs/b1b/seed{S}/rings.parquet",
    "B0": E2E / "R2_b0/gine_causal/seed{S}/rings.parquet",
    "louvain_r0.5": REPO_ROOT / "experiments/R13_baselines/louvain_r0.5/seed{S}/rings.parquet",
    "lpa_on_expansion": REPO_ROOT / "experiments/R13_baselines/lpa_on_expansion/seed{S}/rings.parquet",
    "ringfold_proposed": REPO_ROOT / "experiments/R3_ringfold/runs/proposed/seed{S}/rings.parquet",
}
PAIRS = [("full", "B0", "test_visible"), ("full", "B1b", "test_visible"), ("B0", "louvain_r0.5", "test_visible"),
         ("B0", "louvain_r0.5", "component"), ("B0", "louvain_r0.5", "component_ge3"),
         ("full", "lpa_on_expansion", "test_visible"), ("ringfold_proposed", "proposed", "test_visible")]
EXTRA_CONV = {"B0": ["component", "component_ge3"], "louvain_r0.5": ["component", "component_ge3"]}
N_SHUFFLE, RNG_SEED, TAU = 200, 20261115, 0.5


# ----------------------------------------------------------------------------- pure functions
def candidates(preds: list[set], truth: dict, tau: float = TAU) -> list[tuple]:
    out = []
    for pi, p in enumerate(preds):
        for tid, t in truth.items():
            inter = len(p & t)
            if inter:
                j = inter / len(p | t)
                if j >= tau:
                    out.append((j, pi, tid))
    return out


def greedy_count(preds: list[set], truth: dict, tau: float = TAU) -> int:
    """Number of pairs matched by the shipped rule (same sort key as ring_metrics.match_rings)."""
    c = sorted(candidates(preds, truth, tau), key=lambda x: (-x[0], x[1], str(x[2])))
    up, ut, n = set(), set(), 0
    for _, pi, tid in c:
        if pi in up or tid in ut:
            continue
        up.add(pi)
        ut.add(tid)
        n += 1
    return n


def greedy_matched(preds: list[set], truth: dict, tau: float = TAU) -> set:
    """Truth ids matched by the shipped rule."""
    c = sorted(candidates(preds, truth, tau), key=lambda x: (-x[0], x[1], str(x[2])))
    up, ut = set(), set()
    for _, pi, tid in c:
        if pi in up or tid in ut:
            continue
        up.add(pi)
        ut.add(tid)
    return ut


def optimal_count(preds: list[set], truth: dict, tau: float = TAU) -> int:
    """Maximum number of one-to-one pairs at Jaccard >= tau."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching
    c = candidates(preds, truth, tau)
    if not c:
        return 0
    tids = {t: i for i, t in enumerate(truth)}
    m = csr_matrix((np.ones(len(c)), ([x[1] for x in c], [tids[x[2]] for x in c])), shape=(len(preds), len(truth)))
    return int((maximum_bipartite_matching(m, perm_type="column") >= 0).sum())


def count_forced_ties(preds: list[set], truth: dict, tau: float = TAU) -> set:
    """Truth ids in a tie the greedy matcher must break: walking Jaccard levels from the top, among
    the pairs still available at that level, two pairs with the same Jaccard that share a prediction or
    a truth ring. Matching then proceeds by the shipped order."""
    c = candidates(preds, truth, tau)
    levels = {}
    for j, pi, tid in c:
        levels.setdefault(round(j, 12), []).append((pi, tid))
    up, ut, tied = set(), set(), set()
    for j in sorted(levels, reverse=True):
        avail = [(pi, tid) for pi, tid in levels[j] if pi not in up and tid not in ut]
        for a in range(len(avail)):
            for b in range(a + 1, len(avail)):
                if avail[a][0] == avail[b][0] or avail[a][1] == avail[b][1]:
                    tied |= {avail[a][1], avail[b][1]}
        for pi, tid in sorted(avail, key=lambda x: (x[0], str(x[1]))):
            if pi not in up and tid not in ut:
                up.add(pi)
                ut.add(tid)
    return tied


def f1(m: int, n_pred: int, n_truth: int) -> float:
    p = m / n_pred if n_pred else 0.0
    r = m / n_truth if n_truth else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


# ----------------------------------------------------------------------------- driver
def main():
    from preprocessing.account_bank import load_paths
    from evaluation.score_external import build_targets, load_predictions, load_split_edges
    from ringshield.evaluate import restrict_rings
    from ringshield.windows import load_windows
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    edges = load_split_edges("test", pdir)
    targets, _ = build_targets(pdir / "amlworld_ring_ground_truth.parquet", W)
    preds = {name: [restrict_rings(load_predictions(Path(str(t).format(S=S)), edges, 3)[0], edges, W) for S in range(1, 6)]
             for name, t in ROWS.items()}
    convs = {name: ["test_visible"] + EXTRA_CONV.get(name, []) for name in ROWS}
    rng = np.random.default_rng(RNG_SEED)
    perms = {(name, s): [rng.permutation(len(preds[name][s])) for _ in range(N_SHUFFLE)] for name in ROWS for s in range(5)}
    shuf = {}          # (name, conv) -> array (N_SHUFFLE,) of mean-over-seeds F1
    rows = []
    for name in ROWS:
        for conv in convs[name]:
            truth = targets[conv][0]
            nT = len(truth)
            g, o, ties = [], [], []
            draws = np.zeros((N_SHUFFLE, 5))
            for s in range(5):
                P = preds[name][s]
                g.append(f1(greedy_count(P, truth), len(P), nT))
                o.append(f1(optimal_count(P, truth), len(P), nT))
                ties.append(len(count_forced_ties(P, truth)))
                for k, perm in enumerate(perms[(name, s)]):
                    draws[k, s] = f1(greedy_count([P[i] for i in perm], truth), len(P), nT)
            sh = draws.mean(axis=1)
            shuf[(name, conv)] = sh
            rows.append({"row": name, "convention": conv, "n_targets": nT, "ring_f1_shipped": np.mean(g),
                         "shuffle_min": sh.min(), "shuffle_max": sh.max(), "shuffle_sd": sh.std(ddof=1),
                         "shuffle_range": sh.max() - sh.min(), "ring_f1_optimal": np.mean(o),
                         "optimal_minus_shipped": np.mean(o) - np.mean(g),
                         "forced_tie_truth_rings_per_seed": ";".join(map(str, ties)), "forced_tie_mean": np.mean(ties)})
            print(rows[-1], flush=True)
    pairs = []
    for a, b, conv in PAIRS:
        d = shuf[(a, conv)] - shuf[(b, conv)]
        ra = next(r for r in rows if r["row"] == a and r["convention"] == conv)
        rb = next(r for r in rows if r["row"] == b and r["convention"] == conv)
        pairs.append({"pair": f"{a} - {b}", "convention": conv, "delta_shipped": ra["ring_f1_shipped"] - rb["ring_f1_shipped"],
                      "shuffle_min": d.min(), "shuffle_max": d.max(), "shuffle_sd": d.std(ddof=1),
                      "delta_optimal": ra["ring_f1_optimal"] - rb["ring_f1_optimal"]})
    # paired-bootstrap interval under prediction-order shuffles (the --compare procedure: evidence_stat +
    # paired_unit_bootstrap, 10,000 draws, seed 20261114); draw 0 = shipped order
    from evaluation.ring_stats import paired_unit_bootstrap
    from evaluation.score_external import evidence_stat

    def ev_block(name, conv, k):
        truth = targets[conv][0]
        ids = list(truth)
        runs = []
        for s in range(5):
            P = preds[name][s]
            if k >= 0:
                P = [P[i] for i in perms[(name, s)][k]]
            m = greedy_matched(P, truth)
            runs.append({"matched": [int(t in m) for t in ids], "n_predicted": len(P)})
        return {"runs": runs}

    for row in pairs:
        a, b = row["pair"].split(" - ")
        conv = row["convention"]
        los, his, ps = [], [], []
        for k in [-1] + list(range(N_SHUFFLE)):
            sa, n = evidence_stat(ev_block(a, conv, k))
            sb, _ = evidence_stat(ev_block(b, conv, k))
            r = paired_unit_bootstrap(lambda m, W: (sa if m == "a" else sb)(W), [("d", "a", "b")], n,
                                      n_boot=10000, seed=20261114)[("d", "ring_f1")]
            los.append(r["lo"]); his.append(r["hi"]); ps.append(r["p"])
        row.update(ci_lo_shipped=los[0], ci_hi_shipped=his[0], p_shipped=ps[0],
                   ci_lo_min=min(los[1:]), ci_lo_max=max(los[1:]), ci_hi_min=min(his[1:]), ci_hi_max=max(his[1:]),
                   p_min=min(ps[1:]), p_max=max(ps[1:]))
        print(row, flush=True)
    out = REPO_ROOT / "results/tables/q7_tie_audit"
    pd.DataFrame(rows).to_csv(f"{out}.csv", index=False)
    pd.DataFrame(pairs).to_csv(f"{out}_pairs.csv", index=False)
    print(pd.DataFrame(rows).round(4).to_string())
    print(pd.DataFrame(pairs).round(4).to_string())


if __name__ == "__main__":
    main()
