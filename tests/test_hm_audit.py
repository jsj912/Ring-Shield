"""T-P4 helpers."""
from evaluation.hm_audit import NOTE, hm_primary, median_size


def test_primary_is_amendment15_days_6_to_14():
    W = hm_primary()
    assert W.split == "test"
    lo, hi = W.bounds
    assert lo == W.day_zero + 6 * W.seconds_per_day
    assert hi >= W.day_zero + 15 * W.seconds_per_day - 1 and hi <= W.day_zero + 15 * W.seconds_per_day


def test_median_size_and_note():
    assert median_size({1: {1, 2, 3}, 2: {4, 5, 6, 7, 8}, 3: {9, 10, 11, 12}}) == 4.0
    assert "seed 3" in NOTE and "adequacy" in NOTE
