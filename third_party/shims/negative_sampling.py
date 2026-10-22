"""Stub for MEGA-GNN's `negative_sampling` pybind11 extension (Step 10 adapter).

Only their link-prediction task (`--task lp`) calls it; this project runs `edge_class`. The stub
exists so `train_util.py` imports cleanly on a platform without the compiled binary, and fails
loudly if the lp path is ever taken.
"""
from __future__ import annotations


def generate_negative_samples(*args, **kwargs):  # pragma: no cover - not reachable for edge_class
    raise NotImplementedError(
        "negative_sampling is MEGA-GNN's C++ extension for the link-prediction task; this project "
        "runs --task edge_class, which never calls it. Build the upstream extension if you need lp."
    )
