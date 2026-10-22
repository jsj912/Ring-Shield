"""`currency="converted"`: the rate table, the leg booking, and the guarantee that `raw` is frozen.

The point of this module is the last one. `raw` is what every published number was computed with,
so a change that improves the roles must be provably unable to move it.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.roles import (  # noqa: E402
    CURRENCY_MODES,
    account_roles,
    flows_converted,
    flows_of,
    load_fx_rates,
    load_roles_config,
)

FX_JSON = REPO_ROOT / "contract" / "fx_rates.json"
needs_fx = pytest.mark.skipif(not FX_JSON.exists(),
                              reason="contract/fx_rates.json not on disk (run contract/make_fx_rates.py)")

SE_COLS = ["edge_id", "from_id", "to_id", "timestamp", "amount_sent", "amount_received",
           "currency_sent", "currency_received", "score_calibrated", "is_seed"]


def edges(rows) -> pd.DataFrame:
    """rows: (edge_id, from, to, ts, amt_sent, amt_recv, cur_sent, cur_recv)"""
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "timestamp", "amount_sent",
                                     "amount_received", "currency_sent", "currency_received"])
    df["score_calibrated"] = 0.9
    df["is_seed"] = True
    return df[SE_COLS]


class Ring:
    """Minimal stand-in: account_roles only reads these."""
    def __init__(self, df):
        self.member_edges = [int(x) for x in df["edge_id"]]
        self.seed_edges = list(self.member_edges)
        self.expanded_edges = []
        self.start_time = int(df["timestamp"].min())
        self.end_time = int(df["timestamp"].max())
        self.members = sorted(set(df["from_id"]) | set(df["to_id"]))


# --------------------------------------------------------------------------- the mode exists
def test_converted_is_a_mode():
    assert CURRENCY_MODES == ("raw", "partitioned", "converted")


def test_an_unknown_mode_is_refused():
    df = edges([(1, 10, 11, 0, 100.0, 100.0, 0, 0)])
    with pytest.raises(AssertionError, match="currency must be one of"):
        account_roles(Ring(df), df, currency="nonsense")


# --------------------------------------------------------------------------- the rate table
@needs_fx
def test_rate_table_is_self_consistent():
    d = json.loads(FX_JSON.read_text(encoding="utf-8"))
    assert d["fixed_rates"] is True
    assert d["split"] == "train", "rates must not be estimated on val or test"
    assert d["label_filter"].startswith("none"), "a generator constant must not depend on labels"
    c = d["checks"]
    assert c["n_round_trip_ok"] == c["n_round_trip"] > 0
    assert c["n_triangle_ok"] == c["n_triangle"] > 0
    assert c["worst_round_trip_err"] < 1e-4 and c["worst_triangle_rel_err"] < 1e-4


@needs_fx
def test_hub_is_identity_and_unconvertible_is_explicit():
    fx = load_fx_rates()
    assert fx["rate_to_ccy0"][fx["hub"]] == 1.0
    for c in fx["unconvertible"]:
        assert fx["rate_to_ccy0"][c] is None, "an unconvertible currency must be null, not absent"
    assert 1 in fx["unconvertible"], "currency 1 has no rate at 2-dp precision"


# --------------------------------------------------------------------------- raw is frozen
@needs_fx
def test_raw_is_untouched_by_the_new_mode():
    """The regression that matters: adding `converted` must not move `raw` anywhere."""
    df = edges([(1, 10, 11, 0, 100.0, 85.34, 0, 2),
                (2, 11, 12, 3600, 85.34, 85.34, 2, 2),
                (3, 12, 12, 7200, 85.34, 100.0, 2, 0)])
    r = Ring(df)
    a = account_roles(r, df, currency="raw")
    f = flows_of(df)
    for row in f.itertuples(index=False):
        rec = a[int(row.account)]
        assert rec["inflow"] == pytest.approx(float(row.inflow))
        assert rec["outflow"] == pytest.approx(float(row.outflow))
        assert rec["n_in"] == int(row.n_in) and rec["n_out"] == int(row.n_out)
    assert all("ccy_unconvertible" not in v for v in a.values()), "raw must gain no new keys"


# --------------------------------------------------------------------------- the leg booking
@needs_fx
def test_a_self_loop_conversion_is_booked_on_both_currencies():
    """The defect this mode repairs: raw books the sender's leg at the receiver's amount."""
    fx = load_fx_rates()["rate_to_ccy0"]
    # account 10 converts 1000 of currency 0 into currency 2 with itself
    amt0, amt2 = 1000.0, 1000.0 * 0.8534
    df = edges([(1, 10, 10, 0, amt0, amt2, 0, 2)])
    raw = flows_of(df).set_index("account")
    con = flows_converted(df).set_index("account")
    # raw: both legs at amount_received -> in == out -> closure 1.0, a balanced mule
    assert raw.loc[10, "inflow"] == pytest.approx(amt2)
    assert raw.loc[10, "outflow"] == pytest.approx(amt2)
    # converted: outflow is amount_sent in currency 0, inflow amount_received in currency 2
    assert con.loc[10, "outflow"] == pytest.approx(amt0 * fx[0])
    assert con.loc[10, "inflow"] == pytest.approx(amt2 * fx[2])
    # and because the generator's rate is exact, the conversion still balances -- in VALUE
    assert con.loc[10, "closure"] == pytest.approx(1.0, abs=1e-3)


@needs_fx
def test_conversion_makes_two_currencies_comparable():
    """1000 of currency 0 in, the same value out in currency 2: a mule, not a source."""
    cfg = load_roles_config()
    df = edges([(1, 9, 10, 0, 1000.0, 1000.0, 0, 0),
                (2, 10, 11, 3600, 1000.0, 853.4, 0, 2)])
    roles = account_roles(Ring(df), df, config=cfg, currency="converted")
    assert roles[10]["role"] == "mule", roles[10]
    assert roles[10]["closure"] == pytest.approx(1.0, abs=1e-3)


# --------------------------------------------------------------------------- withholding
@needs_fx
def test_an_unconvertible_currency_is_withheld_not_guessed():
    """Only the account that actually touches currency 1 is withheld -- not its counterparty."""
    df = edges([(1, 9, 10, 0, 500.0, 500.0, 0, 0),
                (2, 10, 11, 3600, 500.0, 0.04, 0, 1),      # 11 RECEIVES currency 1: no rate
                (3, 11, 12, 7200, 0.04, 500.0, 1, 0)])     # 11 SENDS currency 1: no rate either
    roles = account_roles(Ring(df), df, currency="converted")
    # 11 is the only account with a currency-1 leg
    assert roles[11]["role"] == "undetermined", roles[11]
    assert math.isnan(roles[11]["closure"])
    assert roles[11]["ccy_unconvertible"] is True
    # 10's own legs are both currency 0, so it stays judgeable: the withholding does not spread
    assert roles[10]["role"] != "undetermined", roles[10]
    assert roles[10]["ccy_unconvertible"] is False
    # and 12 only receives currency 0
    assert roles[12]["ccy_unconvertible"] is False


@needs_fx
def test_withholding_applies_to_the_sending_leg_too():
    """currency_sent is read for the sender, so an unconvertible OUTflow must also withhold."""
    df = edges([(1, 9, 10, 0, 500.0, 0.04, 0, 1),          # 10 receives currency 1
                (2, 10, 11, 3600, 0.04, 500.0, 1, 0)])     # 10 sends currency 1
    roles = account_roles(Ring(df), df, currency="converted")
    assert roles[10]["role"] == "undetermined"
    assert roles[10]["ccy_unconvertible"] is True


@needs_fx
def test_a_single_currency_ring_is_the_same_under_raw_and_converted():
    """Conversion by 1.0 changes nothing, so the two modes must agree exactly."""
    df = edges([(1, 10, 11, 0, 900.0, 900.0, 0, 0),
                (2, 11, 12, 3600, 880.0, 880.0, 0, 0),
                (3, 12, 13, 7200, 870.0, 870.0, 0, 0)])
    r = Ring(df)
    a = account_roles(r, df, currency="raw")
    b = account_roles(r, df, currency="converted")
    assert set(a) == set(b)
    for acc in a:
        assert a[acc]["role"] == b[acc]["role"], acc
        assert a[acc]["inflow"] == pytest.approx(b[acc]["inflow"])
        assert a[acc]["outflow"] == pytest.approx(b[acc]["outflow"])


@needs_fx
def test_missing_currency_columns_fall_back_to_raw():
    df = edges([(1, 10, 11, 0, 100.0, 100.0, 0, 0)]).drop(columns=["currency_sent",
                                                                   "currency_received"])
    f = flows_converted(df)
    assert not f["ccy_unconvertible"].any()
    assert f["inflow"].sum() == pytest.approx(flows_of(df)["inflow"].sum())


def test_a_missing_rate_file_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="make_fx_rates"):
        load_fx_rates(tmp_path / "absent.json")


# --------------------------------------------------------------------------- ring-level helper
@needs_fx
def test_ring_conservation_converted_agrees_with_the_closure_function():
    """The helper must not be a second implementation of the closure definition."""
    from ringshield.roles import conservation_closure, ring_conservation_converted
    df = edges([(1, 9, 10, 0, 1000.0, 853.4, 0, 2),
                (2, 10, 11, 3600, 853.4, 853.4, 2, 2),
                (3, 11, 12, 7200, 853.4, 1000.0, 2, 0)])
    r = Ring(df)
    roles = account_roles(r, df, currency="converted")
    c = ring_conservation_converted(r, df)
    want = conservation_closure(roles)
    assert (math.isnan(c["closure"]) and math.isnan(want)) or c["closure"] == pytest.approx(want)
    assert c["currency"] == load_fx_rates()["hub"] == 0
    assert c["n_accounts"] == len(roles)
    assert c["unconvertible"] is False


@needs_fx
def test_the_totals_are_the_parts_of_the_ratio():
    from ringshield.roles import ring_conservation_converted
    df = edges([(1, 9, 10, 0, 1000.0, 1000.0, 0, 0),
                (2, 10, 11, 3600, 1000.0, 1000.0, 0, 0)])
    c = ring_conservation_converted(Ring(df), df)
    assert c["n_sources"] >= 1 and c["n_sinks"] >= 1
    hi = max(c["in_at_sinks"], c["out_at_sources"])
    expect = min(max(1.0 - abs(c["in_at_sinks"] - c["out_at_sources"]) / hi, 0.0), 1.0)
    assert c["closure"] == pytest.approx(expect)


@needs_fx
def test_a_ring_touching_an_unconvertible_currency_is_flagged_partial():
    from ringshield.roles import ring_conservation_converted
    df = edges([(1, 9, 10, 0, 500.0, 500.0, 0, 0),
                (2, 10, 11, 3600, 500.0, 0.04, 0, 1)])
    c = ring_conservation_converted(Ring(df), df)
    assert c["unconvertible"] is True, "a ring touching currency 1 must say its total is partial"
    assert c["n_undetermined"] >= 1
