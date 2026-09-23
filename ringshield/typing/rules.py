"""The hand-written 8-way topology scorer (Step 8.2) -- the sanity bound for the learned head.

    t = rule_type(features)            # one of contract.schema.TOPOLOGY_TYPES
    s = rule_scores(features)          # {type: score in [0, 1]}, argmax == rule_type

**What the rules see.** A ring visible in one split is usually a FRAGMENT of its pattern: only
the transactions inside the split are there, so a 45-account STACK arrives as seven short chains
and a BIPARTITE as six disjoint pairs (`docs/TYPING.md`). The rules are therefore written on the
*fragment's* account graph -- degrees, pass-through accounts, connected pieces -- not on the
idealised shape. The first version, written from the idealised shapes with role counts
(one sink and >= 3 sources for FAN-IN, a single mule for GATHER-SCATTER, ...), scored 0.336 on
true train rings, below the 0.60 sanity bound; this version scores 0.783.

Rules, in the order they are tested (first match wins; `f` is a `ringshield.typing.features` row):

    GATHER-SCATTER  some account has in-degree >= 2 AND out-degree >= 2 (it gathers, then scatters)
    BIPARTITE       >= 2 connected pieces, every piece a 2-account pair, no pass-through account
    FAN-IN          in-degree >= 2 somewhere, out-degree <= 1 everywhere, no pass-through account
    FAN-OUT         the mirror image
    SCATTER-GATHER  in-degree >= 2 and out-degree >= 2 at different accounts, >= 2 pass-throughs
    CYCLE           a directed cycle covering >= 60 % of the members
    STACK           >= 2 pieces with a pass-through account, or a directed path of >= 3 edges
                    with <= 2 branch points
    RANDOM          none of the above

`rule_scores` gives every type a soft score (how far its conditions are met) so the head can be
compared against a ranking, not only an argmax; the argmax reproduces `rule_type` exactly.
"""
from __future__ import annotations

import numpy as np

from contract.schema import TOPOLOGY_TYPES

STACK_MIN_PATH = 3
STACK_MAX_BRANCH = 2
CYCLE_COVER = 0.6


def rule_type(f: dict) -> str:
    if f["n_hub_both"] >= 1:
        return "GATHER-SCATTER"
    if f["n_components"] >= 2 and f["n_pair_components"] == f["n_components"] and f["n_both"] == 0:
        return "BIPARTITE"
    if f["max_in_degree"] >= 2 and f["max_out_degree"] <= 1 and f["n_both"] == 0:
        return "FAN-IN"
    if f["max_out_degree"] >= 2 and f["max_in_degree"] <= 1 and f["n_both"] == 0:
        return "FAN-OUT"
    if f["max_out_degree"] >= 2 and f["max_in_degree"] >= 2 and f["n_both"] >= 2:
        return "SCATTER-GATHER"
    if f["has_cycle"] and f["cycle_cover"] >= CYCLE_COVER:
        return "CYCLE"
    if f["n_components"] >= 2 and f["n_both"] >= 1:
        return "STACK"
    if f["longest_path"] >= STACK_MIN_PATH and f["n_branch_points"] <= STACK_MAX_BRANCH:
        return "STACK"
    return "RANDOM"


def rule_scores(f: dict) -> dict[str, float]:
    """Soft score per type; the argmax equals `rule_type(f)`."""
    n = max(f["n_members"], 1)
    hard = rule_type(f)
    pieces = max(f["n_components"], 1)
    s = {
        "GATHER-SCATTER": min(f["n_hub_both"], 1.0),
        "BIPARTITE": (f["n_pair_components"] / pieces) * (1.0 if f["n_both"] == 0 else 0.2) * min(pieces / 2, 1.0),
        "FAN-IN": min(f["max_in_degree"] / 2, 1.0) * (1.0 if f["max_out_degree"] <= 1 else 0.3) * (1.0 if f["n_both"] == 0 else 0.3),
        "FAN-OUT": min(f["max_out_degree"] / 2, 1.0) * (1.0 if f["max_in_degree"] <= 1 else 0.3) * (1.0 if f["n_both"] == 0 else 0.3),
        "SCATTER-GATHER": min(f["max_out_degree"] / 2, 1.0) * min(f["max_in_degree"] / 2, 1.0) * min(f["n_both"] / 2, 1.0),
        "CYCLE": float(f["has_cycle"]) * min(f["cycle_cover"] / CYCLE_COVER, 1.0),
        "STACK": max(min(f["longest_path"] / STACK_MIN_PATH, 1.0) * (1.0 if f["n_branch_points"] <= STACK_MAX_BRANCH else 0.3),
                     min(pieces / 2, 1.0) * min(f["n_both"], 1.0)),
        "RANDOM": 0.35,
    }
    s[hard] = max(s[hard], max(s.values()) + 1e-6)      # the argmax is the hard rule
    tot = sum(s.values()) or 1.0
    return {t: s[t] / tot for t in TOPOLOGY_TYPES}


def rule_probs(f: dict) -> np.ndarray:
    d = rule_scores(f)
    return np.array([d[t] for t in TOPOLOGY_TYPES], dtype=float)
