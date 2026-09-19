"""Stage B -- expansion policy (Step 6, R3): recover the quiet members of a ring around its seeds.

    from ringshield.expand.candidates import candidates
    from ringshield.expand.features import compute_features
    from ringshield.expand.index import SplitIndex, index_for

Modules:
    index              per-split, per-account sorted event arrays (built once per split)
    candidates         candidates(scored_edges, included_edge_ids, delta_t_h, max_hops) -> DataFrame
    features           feature rows for candidates, computed at the candidate's timestamp only
    dead_region        the classifier head's constant-score plateaus (score is not evidence there)
    cross_score        5-fold cross-scoring of the TRAIN split (fold models never see their day)
    make_training_set  cross-scores + train-visible rings -> policy training rows
    policy             (6.4) LightGBM policy, greedy expansion, aggregator 'expand'
"""
from __future__ import annotations
