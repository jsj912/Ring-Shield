"""Which predicted ring matches which true ring -- by calling the research side's code (XR-28).

    W = window_from_config(cfg)                                    # "primary" = test days 8-9
    res = match_in_window(rings, scored_edges, W, truth_path=..., threshold=0.5, scope="test_visible")
    res.matches          # DataFrame: ring_id, truth_ring_id, pattern_type, jaccard, coverage
    T = truth_edge_sets(split_parquet, W, ring_ids=res.matches.truth_ring_id)

No matching rule is written here. The order of operations is exactly the research side's own
evaluation (`ringshield/evaluate.py::evaluate_blocks`):
    1. truth rings in scope of the window   -> ringshield.truth.load_ground_truth
    2. predicted rings cut to the window     -> ringshield.evaluate.restrict_rings
    3. greedy one-to-one Jaccard >= 0.5       -> evaluation.ring_metrics.match_rings
so the matched count is the count Joan reports (seed 1, primary window: 81 of 94 predictions).

The one thing added is bookkeeping. `restrict_rings` silently DROPS rings with no member edge inside
the window and returns a shorter list of account sets with no ring ids, so position i of its output is
not ring i of its input (docs/PITFALLS.md §4). We drop those rings ourselves first, with the same
rule, and assert the lengths agree -- after that, position i means the same ring on both sides.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from contract.schema import RINGS_ORDER
from evaluation.ring_metrics import match_rings
from explainability.contract_io import load_research_config, repo_path
from ringshield.evaluate import restrict_rings
from ringshield.rings import Ring
from ringshield.truth import load_ground_truth
from ringshield.windows import Window, load_windows


@dataclass
class MatchResult:
    matches: pd.DataFrame          # one row per matched (predicted ring, truth ring) pair
    n_pred_in_window: int          # predicted rings with >= 1 member edge in the window
    n_pred_total: int
    n_truth: int                   # truth rings in scope of the window
    window: dict
    threshold: float
    scope: str

    @property
    def n_matched(self) -> int:
        return len(self.matches)


def window_from_config(cfg: dict) -> Window:
    path = repo_path(cfg["research_configs"]["eval_window"])
    return load_windows(path)[cfg["evaluation"]["window"]]


def matching_rule(cfg: dict) -> tuple[float, str]:
    """(Jaccard threshold, scope policy) from configs/threshold_rule.yaml -- read, never copied."""
    rule = load_research_config(cfg, "threshold_rule")
    return float(rule["match_threshold"]), str(rule["scope"])


def in_window_edge_ids(scored_edges: pd.DataFrame, window: Window) -> set[int]:
    return set(scored_edges.loc[window.mask(scored_edges["timestamp"].to_numpy()), "edge_id"].tolist())


def windowed_prediction_sets(rings: pd.DataFrame, scored_edges: pd.DataFrame, window: Window):
    """(ring_ids, account sets) of the rings with >= 1 member edge in the window, aligned by position."""
    in_win = in_window_edge_ids(scored_edges, window)
    kept = rings[[any(e in in_win for e in m) for m in rings["member_edges"]]]
    ring_objs = [Ring(**{c: row[c] for c in RINGS_ORDER}) for row in kept.to_dict("records")]
    sets = restrict_rings(ring_objs, scored_edges, window)
    assert len(sets) == len(ring_objs), (
        f"restrict_rings returned {len(sets)} sets for {len(ring_objs)} in-window rings; "
        "positions would no longer identify rings")
    return list(kept["ring_id"]), sets


def match_in_window(rings: pd.DataFrame, scored_edges: pd.DataFrame, window: Window, *, threshold: float,
                    scope: str, truth_path: Path | None = None, truth: dict | None = None,
                    patterns: dict | None = None) -> MatchResult:
    """Match predicted rings to truth rings inside `window`. Pass `truth_path` (the ground-truth parquet)
    or, in tests, an in-memory `truth` dict {truth_ring_id: account set}."""
    if truth is None:
        truth, patterns = load_ground_truth(repo_path(truth_path), *window.bounds, scope, verbose=False)
    patterns = patterns or {}
    ring_ids, sets = windowed_prediction_sets(rings, scored_edges, window)
    matched, _, _ = match_rings(sets, truth, threshold)
    rows = [{"ring_id": ring_ids[m.pred_idx], "truth_ring_id": int(m.truth_id),
             "pattern_type": patterns.get(m.truth_id, "UNKNOWN"),
             "jaccard": float(m.jaccard), "coverage": float(m.coverage)} for m in matched]
    df = pd.DataFrame(rows, columns=["ring_id", "truth_ring_id", "pattern_type", "jaccard", "coverage"])
    df = df.sort_values("ring_id", kind="stable").reset_index(drop=True)
    return MatchResult(matches=df, n_pred_in_window=len(sets), n_pred_total=len(rings), n_truth=len(truth),
                       window=window.as_dict(), threshold=threshold, scope=scope)


@dataclass
class TruthEdges:
    edges: dict[int, set[int]]      # truth ring id -> its transaction (edge) ids inside the window
    accounts: dict[int, set[int]]   # truth ring id -> the accounts on those transactions (consistency check)


def truth_edge_sets(split_parquet, window: Window, ring_ids=None) -> TruthEdges:
    """The true edge set T of each truth ring inside the window.

    The ground-truth parquet has no edge ids, so T comes from the test split parquet, whose `ring_id`
    column labels every transaction matched to a pattern line (-1 = no ring). Duplicate payments that
    matched the same pattern line are all labelled and all kept."""
    df = pd.read_parquet(repo_path(split_parquet), columns=["EdgeID", "from_id", "to_id", "Timestamp", "ring_id"])
    df = df[(df["ring_id"] > 0) & window.mask(df["Timestamp"].to_numpy())]
    if ring_ids is not None:
        df = df[df["ring_id"].isin({int(r) for r in ring_ids})]
    edges = {int(r): set(g["EdgeID"].astype(int)) for r, g in df.groupby("ring_id")}
    accounts = {int(r): set(g["from_id"].astype(int)) | set(g["to_id"].astype(int)) for r, g in df.groupby("ring_id")}
    return TruthEdges(edges=edges, accounts=accounts)
