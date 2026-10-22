"""Step 3b-w apply: evaluation windows and the per-window ring scope numbers.

    python -m pytest tests/test_eval_window.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.aggregators.cc import aggregate_cc, seed_mask_for_pct, threshold_for_pct  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import Window, load_windows, test_windows  # noqa: E402

GT = REPO_ROOT / "data" / "processed" / "amlworld_ring_ground_truth.parquet"
TEST_PQ = REPO_ROOT / "data" / "processed" / "amlworld_test.parquet"
DOC = REPO_ROOT / "docs" / "RING_GROUND_TRUTH_DEFINITION.md"
EXPECTED = {"primary": (174, 114), "tail": (109, 84), "whole": (183, 132)}


def test_windows_config():
    W = load_windows()
    assert list(W) == ["val", "primary", "tail", "whole"]
    assert (W["primary"].day_lo, W["primary"].day_hi) == (8, 9)
    assert (W["tail"].day_lo, W["tail"].day_hi) == (10, 17)      # written out in full, not "days_from"
    assert (W["whole"].day_lo, W["whole"].day_hi) == (8, 17)
    assert (W["val"].day_lo, W["val"].day_hi) == (6, 7) and W["val"].split == "val"
    assert W["primary"].bounds == (691_210, 864_009) and W["tail"].bounds == (864_010, 1_555_209)
    ts = np.array([691_209, 691_210, 864_009, 864_010, 1_527_490])
    assert W["primary"].mask(ts).tolist() == [False, True, True, False, False]
    assert W["tail"].mask(ts).tolist() == [False, False, False, True, True]
    assert W["whole"].days_of(ts).tolist() == [7, 8, 9, 10, 17]
    assert set(test_windows()) == {"primary", "tail", "whole"}


@pytest.mark.skipif(not (GT.exists() and TEST_PQ.exists()), reason="processed data not on disk")
def test_per_window_scope_counts():
    W = test_windows()
    got = {}
    for name, w in W.items():
        truth, _ = load_ground_truth(GT, *w.bounds, "test_visible", verbose=False)
        got[name] = (len(truth), sum(1 for m in truth.values() if len(m) >= 3))
    assert got == EXPECTED, got
    # straddling: 100 rings have edges in both windows; 9 are tail-only; 74 primary-only
    tp, _ = load_ground_truth(GT, *W["primary"].bounds, "test_visible", verbose=False)
    tt, _ = load_ground_truth(GT, *W["tail"].bounds, "test_visible", verbose=False)
    assert len(set(tp) & set(tt)) == 100 and len(set(tt) - set(tp)) == 9 and len(set(tp) - set(tt)) == 74
    # every test positive on the tail is a ring edge in the tail block
    te = pd.read_parquet(TEST_PQ, columns=["Timestamp", "Is Laundering"])
    assert int(te.loc[W["tail"].mask(te["Timestamp"].values), "Is Laundering"].sum()) == 655


def test_doc_states_the_split():
    text = DOC.read_text(encoding="utf-8")
    sec = text[text.index("## 4a."):text.index("## 5. Matching")]
    for needle in ("**174**", "**109**", "183 − 9", "tail edges\nbelong to the tail block", "primary window, test days 8–9",
                   "days 10–17"):
        assert needle in sec, needle
    assert re.search(r"\| primary \| 8–9 \| \*\*174\*\*", sec) and re.search(r"\| tail \| 10–17 \| \*\*109\*\*", sec)


def test_strict_quantile_cut_excludes_plateau():
    scores = np.array([0.1] * 50 + [0.5] * 40 + [0.9] * 10)   # plateau of 40 ties at 0.5
    q = threshold_for_pct(scores, 30.0)                          # 70th percentile lands on the plateau
    assert q == 0.5
    m = seed_mask_for_pct(scores, 30.0)
    assert m.sum() == 10 and (scores[m] == 0.9).all()           # ties excluded, not swept in
    se = pd.DataFrame({"edge_id": np.arange(100), "from_id": np.arange(100), "to_id": np.arange(100) + 1000,
                       "from_bank": 1, "to_bank": 1, "timestamp": np.arange(100), "score_raw": scores})
    # inclusive absolute threshold keeps the plateau (legacy CLI semantics)
    r_incl = aggregate_cc(se, 30.0, 1, threshold=0.5)
    r_strict = aggregate_cc(se, 30.0, 1)
    assert sum(len(r.seed_edges) for r in r_incl) == 50 and sum(len(r.seed_edges) for r in r_strict) == 10
