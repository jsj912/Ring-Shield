"""Stage C -- partition an expanded component into attempts (Step 7, R4).

    from ringshield.partition.pairs import pair_features, components_of
    from ringshield.partition.affinity import Affinity, train_affinity, cluster_pivot, cluster_average

Modules:
    pairs                   every two included edges sharing an account within an expanded component,
                            with the pair features of 7.1 (and the same-ring label on train)
    affinity                LightGBM affinity (grouped CV by component) and the two clusterings
    make_pairs_training_set train-split components (seeds + policy-added edges) -> labelled pairs
    run_partition           val grid -> test once for 'full' and the baselines B2-B4 (B5 noted)
"""
from __future__ import annotations
