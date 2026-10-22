"""RingShield library (Step 4): ring aggregation, ground truth and the rings contract as
importable code. The CLIs under models/ and evaluation/ are thin wrappers around this.

    from ringshield.aggregators.cc import aggregate_cc
    from ringshield.rings import Ring, rings_to_table, write_rings_parquet
    from ringshield.truth import load_ground_truth
"""
from __future__ import annotations

__all__ = ["aggregators", "rings", "truth"]
