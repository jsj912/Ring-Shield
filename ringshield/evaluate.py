"""Ring evaluation per window (Step 3b-w apply): truth and predictions restricted the same way.

    blocks = evaluate_blocks(rings, scored_edges, ring_gt, scope, windows, match_thr, sweep)

A ground-truth ring is in scope of a window if >= 1 of its pattern-line transactions falls in
it, and its scored members are the endpoints of those in-window transactions only
(ringshield.truth.load_ground_truth with the window's bounds = the test_visible rule applied to
the window). A predicted ring is restricted to the endpoints of its member_edges inside the
window; rings with no in-window edge are dropped from that block. A straddling ring's tail
edges therefore belong to the tail block on both sides (docs/RING_GROUND_TRUTH_DEFINITION.md
section 4a).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.ring_metrics import evaluate_rings, match_rings
from ringshield.rings import Ring
from ringshield.truth import load_ground_truth
from ringshield.windows import Window


def ring_metrics_full(pred_sets: list[set], truth: dict, patterns: dict, match_threshold: float,
                      jaccard_sweep: list[float]) -> dict:
    """evaluate_rings + Ring-Recall>=3 + the Jaccard sweep, as a JSON-ready dict."""
    m = evaluate_rings(pred_sets, truth, match_threshold, patterns)
    out = m.to_dict()
    matches, _, _ = match_rings(pred_sets, truth, match_threshold)
    big = {tid for tid, members in truth.items() if len(members) >= 3}
    matched_big = {x.truth_id for x in matches} & big
    out["ring_recall_ge3"] = round(len(matched_big) / len(big), 4) if big else None
    out["n_truth_ge3"] = len(big)
    out["n_matched_ge3"] = len(matched_big)
    out["jaccard_sweep"] = {}
    for j in jaccard_sweep:
        mj = evaluate_rings(pred_sets, truth, j)
        out["jaccard_sweep"][str(j)] = {"ring_precision": round(mj.ring_precision, 4), "ring_recall": round(mj.ring_recall, 4),
                                        "ring_f1": round(mj.ring_f1, 4), "n_matched": mj.n_matched}
    out["pred_size"] = {"n_rings": len(pred_sets),
                        "mean_members": float(np.mean([len(p) for p in pred_sets])) if pred_sets else None,
                        "max_members": max((len(p) for p in pred_sets), default=None)}
    return out


def restrict_rings(rings: list[Ring], scored_edges: pd.DataFrame, window: Window) -> list[set]:
    """Predicted member sets restricted to a window: endpoints of member_edges inside it."""
    se = scored_edges.set_index("edge_id")
    in_win = window.mask(se["timestamp"].values)
    keep = set(se.index[in_win].tolist())
    frm, to = se["from_id"], se["to_id"]
    out = []
    for r in rings:
        edges = [e for e in r.member_edges if e in keep]
        if not edges:
            continue
        out.append(set(frm.loc[edges].tolist()) | set(to.loc[edges].tolist()))
    return out


def seed_edges_vs_labels(rings: list[Ring], scored_edges: pd.DataFrame, labels: pd.DataFrame | None,
                         window: Window | None = None) -> dict | None:
    """Precision and illicit recall of the seed edges / member edges, optionally inside a window."""
    if labels is None:
        return None
    lab = labels.set_index("edge_id")["true_label"]
    ts = scored_edges.set_index("edge_id")["timestamp"]
    if window is not None:
        in_win = set(ts.index[window.mask(ts.values)].tolist())
        lab = lab[lab.index.isin(in_win)]
    seeds = np.array(sorted({e for r in rings for e in r.seed_edges if e in lab.index}), dtype=np.int64)
    members = np.array(sorted({e for r in rings for e in r.member_edges if e in lab.index}), dtype=np.int64)
    n_pos = int(lab.sum())
    return {"n_edges_in_window": int(len(lab)), "n_illicit_in_window": n_pos,
            "n_seed_edges": int(len(seeds)),
            "seed_edge_precision": float(lab.loc[seeds].mean()) if len(seeds) else None,
            "seed_edge_recall_of_illicit": float(lab.loc[seeds].sum() / n_pos) if (n_pos and len(seeds)) else 0.0,
            "n_member_edges": int(len(members)),
            "member_edge_precision": float(lab.loc[members].mean()) if len(members) else None,
            "member_edge_recall_of_illicit": float(lab.loc[members].sum() / n_pos) if (n_pos and len(members)) else 0.0}


def evaluate_blocks(rings: list[Ring], scored_edges: pd.DataFrame, ring_gt: Path, scope: str,
                    windows: dict[str, Window], match_threshold: float, jaccard_sweep: list[float],
                    appendix_policies: tuple[str, ...] = ("strict", "majority"), labels: pd.DataFrame | None = None) -> dict:
    """{block: {"window": ..., "n_pred_rings_in_window": ..., **metrics, "appendix": {...},
    "seed_edges_vs_labels": {...}}} for the test windows."""
    out = {}
    for name, w in windows.items():
        truth, patterns = load_ground_truth(ring_gt, *w.bounds, scope, verbose=False)
        pred = restrict_rings(rings, scored_edges, w)
        block = {"window": w.as_dict(), "n_pred_rings_in_window": len(pred), "n_pred_rings_total": len(rings),
                 **ring_metrics_full(pred, truth, patterns, match_threshold, jaccard_sweep), "appendix": {},
                 "seed_edges_vs_labels": seed_edges_vs_labels(rings, scored_edges, labels, w)}
        for pol in appendix_policies:
            t_pol, p_pol = load_ground_truth(ring_gt, *w.bounds, pol, verbose=False)
            block["appendix"][pol] = ring_metrics_full(pred, t_pol, p_pol, match_threshold, [])
        out[name] = block
    return out
