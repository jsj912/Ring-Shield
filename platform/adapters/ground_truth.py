"""Read-only validation truth adapter used by simulation and experiments only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ringshield.truth import load_ground_truth
from ringshield.windows import load_windows


@dataclass(frozen=True)
class TruthMatch:
    ring_id: int | str | None
    jaccard: float
    members: frozenset[int]
    verdict: str


def load_window_truth(truth_parquet: Path, *, window_name: str,
                      scope: str = "test_visible") -> dict[int | str, frozenset[int]]:
    """Load one named evaluation window under the requested truth visibility rule."""
    windows = load_windows()
    try:
        window = windows[window_name]
    except KeyError as exc:
        raise RuntimeError(f"evaluation config has no {window_name} window") from exc
    truth, _ = load_ground_truth(Path(truth_parquet), *window.bounds, scope, verbose=False)
    return {ring_id: frozenset(map(int, members)) for ring_id, members in truth.items()}


def load_window_truth_details(truth_parquet: Path, *, window_name: str,
                              scope: str = "test_visible") -> tuple[dict, dict, pd.DataFrame]:
    """Return canonical truth memberships, patterns, and in-window truth rows."""
    windows = load_windows()
    try:
        window = windows[window_name]
    except KeyError as exc:
        raise RuntimeError(f"evaluation config has no {window_name} window") from exc
    path = Path(truth_parquet)
    try:
        rows = pd.read_parquet(path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"could not read configured truth artifact: {path.name}") from exc
    required = {"ring_id", "from_id", "to_id", "timestamp_int"}
    if not required <= set(rows.columns):
        raise RuntimeError(f"ground truth is missing required transaction columns: {sorted(required - set(rows.columns))}")
    lower, upper = window.bounds
    in_window = (rows["timestamp_int"] >= lower) & (rows["timestamp_int"] <= upper)
    scoped = rows.loc[in_window].copy() if scope == "test_visible" else rows.copy()
    truth, patterns = load_ground_truth(path, lower, upper, scope, verbose=False)
    selected_ids = set(truth)
    scoped = scoped.loc[scoped["ring_id"].isin(selected_ids)].copy()
    return ({ring_id: frozenset(map(int, members)) for ring_id, members in truth.items()},
            patterns, scoped)


def load_val_truth(truth_parquet: Path) -> dict[int | str, frozenset[int]]:
    """Load val days 6-7 under the fixed test-visible membership rule."""
    return load_window_truth(truth_parquet, window_name="val", scope="test_visible")


def match_ring(members: set[int] | frozenset[int], truth_rings: dict,
               min_jaccard: float, full_confirm_jaccard: float = 0.9) -> TruthMatch:
    """Return the best deterministic Jaccard match and simulator's true label."""
    predicted = frozenset(map(int, members))
    if not 0 <= min_jaccard <= 1 or not 0 <= full_confirm_jaccard <= 1:
        raise ValueError("Jaccard thresholds must be in [0, 1]")
    candidates: list[tuple[float, str, int | str, frozenset[int]]] = []
    for ring_id, raw_members in truth_rings.items():
        actual = frozenset(map(int, raw_members))
        union = predicted | actual
        score = len(predicted & actual) / len(union) if union else 1.0
        candidates.append((score, str(ring_id), ring_id, actual))
    if not candidates:
        return TruthMatch(None, 0.0, frozenset(), "reject")
    score, _, ring_id, actual = max(candidates, key=lambda item: (item[0], item[1]))
    if score < min_jaccard:
        return TruthMatch(None, score, frozenset(), "reject")
    verdict = "confirm" if score >= full_confirm_jaccard else "partial"
    return TruthMatch(ring_id, score, actual, verdict)
