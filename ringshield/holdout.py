"""Holding a whole pattern type out of training (Step 11, R7).

    from ringshield.holdout import Holdout
    ho = Holdout.load("BIPARTITE")                 # None / "" gives a no-op holdout
    y = ho.relabel_licit(edge_ids, y, splits=("train", "val"))
    rings = ho.drop_rings(rings, "ring_id")
    ho.assert_absent(training_set, ring_col="ring_id", label_col="label")

One definition, used by every training entry point (`models/tgn.py`,
`ringshield/expand/{cross_score,make_training_set,policy}.py`,
`ringshield/partition/{make_pairs_training_set,affinity}.py`, `ringshield/typing/head.py`) so
that "held out" cannot mean different things in different stages.

**What is held out.** Every ring whose `pattern_type` equals the held-out type, in every split.
Their edges are relabelled **licit** wherever a label is used for training (train and val; val is
a training signal, since checkpoints, thresholds and every L3 parameter are chosen on it), and
their rings are removed from every ring-label set a stage trains on.

**What is not touched.** The graph. Held-out edges stay in the message-passing graph, in the
candidate pool and in the scored-edge table exactly as before -- only their *labels* disappear.
That is the point of the experiment: the pipeline must still be able to recover a pattern it was
never taught. The **test** split keeps its true labels, because it is what measures that.

**The assertion** (`assert_absent`) is what the step's check requires: after any training table is
built, no row may carry a held-out ring id, and no row of a held-out ring may carry a positive
label. `tests/test_holdout.py` exercises it on a fixture and on the real training tables.

A `Holdout` with `pattern=None` is a no-op whose methods return their input unchanged, so the
entry points can call it unconditionally and the non-holdout runs keep behaving exactly as they
did (`is_active` is False and nothing is recorded beyond `hold_out_pattern: null`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

SPLITS = ("train", "val", "test")
TRAINING_SPLITS = ("train", "val")      # val is a training signal: it chooses every parameter


@dataclass
class Holdout:
    """The set of rings and edges of one pattern type, per split."""

    pattern: str | None
    ring_ids: set = field(default_factory=set)
    edges_by_split: dict = field(default_factory=dict)
    processed_dir: Path | None = None

    # ------------------------------------------------------------------ construction
    @classmethod
    def load(cls, pattern: str | None, processed_dir: Path | None = None) -> "Holdout":
        if not pattern:
            return cls(pattern=None)
        from preprocessing.account_bank import load_paths
        pdir = Path(processed_dir) if processed_dir is not None else load_paths()["processed_dir"]
        rings: set = set()
        edges: dict = {}
        seen_patterns: set = set()
        for split in SPLITS:
            path = pdir / f"amlworld_{split}.parquet"
            if not path.exists():
                continue
            df = pd.read_parquet(path, columns=["EdgeID", "ring_id", "pattern_type"])
            seen_patterns |= set(df.loc[df["ring_id"] > 0, "pattern_type"].unique().tolist())
            m = (df["ring_id"] > 0) & (df["pattern_type"] == pattern)
            edges[split] = set(df.loc[m, "EdgeID"].astype(np.int64).tolist())
            rings |= set(df.loc[m, "ring_id"].astype(np.int64).tolist())
        assert edges, f"no split parquets under {pdir}"
        assert pattern in seen_patterns, (
            f"pattern {pattern!r} does not occur in {pdir}; known patterns: {sorted(seen_patterns)}")
        return cls(pattern=pattern, ring_ids=rings, edges_by_split=edges, processed_dir=pdir)

    # ------------------------------------------------------------------ queries
    @property
    def is_active(self) -> bool:
        return self.pattern is not None

    def edge_ids(self, splits=TRAINING_SPLITS) -> set:
        out: set = set()
        for s in splits:
            out |= self.edges_by_split.get(s, set())
        return out

    def summary(self) -> dict:
        """What goes into a run's config.yaml so the holdout is visible without re-deriving it."""
        if not self.is_active:
            return {"hold_out_pattern": None}
        return {"hold_out_pattern": self.pattern,
                "n_held_out_rings": len(self.ring_ids),
                "n_held_out_edges_by_split": {s: len(e) for s, e in sorted(self.edges_by_split.items())},
                "relabelled_licit_in": list(TRAINING_SPLITS),
                "test_labels_untouched": True,
                "graph_unchanged": True}

    # ------------------------------------------------------------------ operations
    def relabel_licit(self, edge_ids, y, splits=TRAINING_SPLITS):
        """Zero the label of every held-out edge of `splits`. `y` is modified out of place."""
        if not self.is_active:
            return y
        held = self.edge_ids(splits)
        if not held:
            return y
        ids = np.asarray(edge_ids, dtype=np.int64)
        mask = np.isin(ids, np.fromiter(held, dtype=np.int64, count=len(held)))
        out = y.clone() if hasattr(y, "clone") else np.array(y, copy=True)
        out[mask] = 0
        return out

    def drop_rings(self, df: pd.DataFrame, ring_col: str = "ring_id") -> pd.DataFrame:
        """Remove every row belonging to a held-out ring (for ring-level training tables)."""
        if not self.is_active or df.empty:
            return df
        keep = ~df[ring_col].astype(np.int64).isin(self.ring_ids)
        return df.loc[keep].reset_index(drop=True)

    def keep_rings(self, ring_ids) -> list:
        """The subset of `ring_ids` that is NOT held out, order preserved."""
        if not self.is_active:
            return list(ring_ids)
        return [r for r in ring_ids if int(r) not in self.ring_ids]

    # ------------------------------------------------------------------ the check
    def assert_absent(self, df: pd.DataFrame, *, ring_col: str | None = "ring_id",
                      label_col: str | None = None, edge_col: str | None = None,
                      where: str = "training table") -> None:
        """No held-out ring id, no positive label on a held-out edge. Raises with counts."""
        if not self.is_active or df is None or len(df) == 0:
            return
        if ring_col and ring_col in df.columns:
            bad = int(df[ring_col].astype(np.int64).isin(self.ring_ids).sum())
            assert bad == 0, f"{where}: {bad} rows carry a held-out {self.pattern} ring id"
        if edge_col and edge_col in df.columns and label_col and label_col in df.columns:
            held = self.edge_ids(TRAINING_SPLITS)
            ids = df[edge_col].astype(np.int64).to_numpy()
            m = np.isin(ids, np.fromiter(held, dtype=np.int64, count=len(held)))
            bad = int((df[label_col].to_numpy()[m] != 0).sum())
            assert bad == 0, f"{where}: {bad} held-out {self.pattern} edges carry a positive label"


def add_argument(ap) -> None:
    """`--hold-out-pattern` with the same help text everywhere."""
    ap.add_argument("--hold-out-pattern", default=None,
                    help="train as if this pattern type did not exist: its rings' edges are relabelled "
                         "licit in train+val and its rings leave every ring-label set. The graph, the test "
                         "labels and the candidate pool are untouched (Step 11 / R7).")
