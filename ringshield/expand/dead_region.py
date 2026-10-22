"""The classifier head's dead region (docs/R2_BASELINES.md): edges whose score is a bias constant.

The Multi-GINe head is Linear(3h, 50) -> ReLU -> Linear(50, 25) -> ReLU -> Linear(25, 2). Two
inputs make its output independent of the embedding:

    c1  every first-layer unit inactive  -> softmax(W3 relu(b2) + b3)[1]
    c2  every second-layer unit inactive -> softmax(b3)[1]

Both are real plateaus in the R1 scores (seed 1: 0.010742 on 12-16 % of every split, 0.079603
on 0.5-2.5 %). An edge sitting on one of them has a score that says nothing about it, so the
expansion policy carries `dead_region` as a binary feature and never reads the score quantile
of such an edge as evidence (Step 6 amendment d). Such edges can never be seeds -- the
constants are far below the 0.1 % quantile -- but are valid expansion candidates.

    consts = head_constants(torch.load(ckpt, map_location="cpu", weights_only=True))
    mask = dead_region_mask(score_raw, consts)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HEAD_PREFIX = "mlp.{layer}.node__to__node.{param}"   # to_hetero naming for the `to` edge type
RTOL, ATOL = 1e-5, 1e-9


def head_constants(state_dict: dict, prefix: str = HEAD_PREFIX) -> list[float]:
    """[c1, c2] from a checkpoint's state dict (see module docstring)."""
    import torch
    key = lambda layer, p: prefix.format(layer=layer, param=p)   # noqa: E731
    if key(0, "bias") not in state_dict:                          # homogeneous (no reverse MP) checkpoint
        key = lambda layer, p: f"mlp.{layer}.{p}"                 # noqa: E731
    b2, W3, b3 = state_dict[key(3, "bias")], state_dict[key(6, "weight")], state_dict[key(6, "bias")]
    c1 = torch.softmax(W3 @ torch.relu(b2) + b3, 0)[1].item()
    c2 = torch.softmax(b3, 0)[1].item()
    return [float(c1), float(c2)]


def head_constants_from_checkpoint(ckpt: Path) -> list[float]:
    import torch
    return head_constants(torch.load(Path(ckpt), map_location="cpu", weights_only=True))


def dead_region_mask(score_raw: np.ndarray, constants: list[float]) -> np.ndarray:
    """True where score_raw equals one of the head constants (float32 softmax -> tolerance)."""
    s = np.asarray(score_raw, dtype=float)
    out = np.zeros(len(s), dtype=bool)
    for c in constants:
        out |= np.isclose(s, c, rtol=RTOL, atol=ATOL)
    return out
