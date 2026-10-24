"""NFR-D53: unit tests for the dashboard's formatting functions."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from formatters import (MISSING, fmt_amount, fmt_as_received, fmt_bool, fmt_closure, fmt_percent,
                        fmt_seconds, fmt_time, fmt_time_utc, fmt_weight)


def test_amount_has_separators_two_decimals_currency_and_partial_flag():
    assert fmt_amount(1234567.5, "US Dollar") == "1,234,567.50 US Dollar"
    assert fmt_amount(12.0, "Yen", partial=True) == "12.00 Yen (partial)"
    assert fmt_amount(0.005) == "0.01"
    assert fmt_amount(None, "US Dollar", True) == MISSING


def test_percentage_one_decimal_and_weight_two_decimals():
    assert fmt_percent(0.926) == "92.6%"
    assert fmt_percent(1) == "100.0%"
    assert fmt_percent(None) == MISSING
    assert fmt_weight(0.7895700827) == "0.79"
    assert fmt_weight(None) == MISSING


def test_topology_probability_is_shown_exactly_as_received():
    assert fmt_as_received(0.5815107754343875) == "0.5815107754343875"


def test_closed_loop_closure_is_text_never_a_percentage():
    assert fmt_closure(None, closed_loop=True) == "closed loop"
    assert fmt_closure(None) == "closed loop"
    assert fmt_closure(0.92, closed_loop=False) == "92.0%"


def test_times_are_local_with_utc_kept_for_hover():
    instant = "2022-09-09T06:00:00Z"
    assert fmt_time(instant, "Asia/Kolkata") == "2022-09-09 11:30 IST"
    assert fmt_time(instant, None) == "2022-09-09 06:00 UTC"
    assert fmt_time(instant, "Not/AZone") == "2022-09-09 06:00 UTC"
    assert fmt_time_utc("2022-09-09T11:30:00+05:30") == "2022-09-09 06:00:00 UTC"
    assert fmt_time(None) == MISSING
    assert fmt_time("not-a-time") == "not-a-time" and fmt_time_utc("t0") == "t0"


def test_seconds_have_separators_and_missing_or_nan_is_a_dash():
    assert fmt_seconds(93840) == "93,840 s"
    assert fmt_seconds(None) == MISSING and fmt_seconds(float("nan")) == MISSING


def test_booleans_read_as_text():
    assert fmt_bool(True) == "Yes" and fmt_bool(False) == "No" and fmt_bool(None) == MISSING
