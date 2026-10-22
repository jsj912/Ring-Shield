"""The code maps must decode the contract, and must stay in step with the raw encoder.

The expensive part -- replaying `format_kaggle_files.py` over 5 M raw rows -- lives in
`contract/make_code_maps.py` and asserts there. These tests check the shipped JSON is internally
consistent, covers every code the processed splits actually use, and still names currency 0
correctly, which is the one fact a consumer is most likely to assume wrongly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402

CUR = REPO_ROOT / "contract" / "currency_map.json"
FMT = REPO_ROOT / "contract" / "payment_format_map.json"
BANK = REPO_ROOT / "contract" / "bank_names.json"

needs_maps = pytest.mark.skipif(
    not (CUR.exists() and FMT.exists()),
    reason="code maps not on disk (run contract/make_code_maps.py)")


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


@needs_maps
@pytest.mark.parametrize("path", [CUR, FMT])
def test_the_two_directions_agree(path):
    d = load(path)
    c2n, n2c = d["code_to_name"], d["name_to_code"]
    assert len(c2n) == len(n2c), "a name maps to two codes, or a code to two names"
    for code, name in c2n.items():
        assert n2c[name] == int(code), f"{code} -> {name} -> {n2c[name]}"
    assert sorted(int(c) for c in c2n) == list(range(len(c2n))), "codes must be 0..n-1, no gaps"


@needs_maps
@pytest.mark.parametrize("path", [CUR, FMT])
def test_the_map_records_a_passing_verification(path):
    v = load(path)["verification"]
    assert v["n_rows"] > 0
    for col in ("Timestamp", "Sent Currency", "Received Currency", "Payment Format"):
        assert v[col]["mismatched"] == 0, f"{col} did not reproduce; the map may be wrong"
        assert v[col]["matching_rows"] == v["n_rows"]


@needs_maps
def test_currency_zero_is_the_us_dollar():
    """Not an arbitrary check: code 0 comes from the first raw row's RECEIVING currency, which is
    easy to assume is 'the commonest currency' or 'the first column'. It is neither."""
    assert load(CUR)["code_to_name"]["0"] == "US Dollar"


@needs_maps
def test_bitcoin_is_the_currency_with_no_rate():
    """Ties the FX limitation to a name, so the docs and the data cannot drift apart."""
    fx = REPO_ROOT / "contract" / "fx_rates.json"
    if not fx.exists():
        pytest.skip("contract/fx_rates.json not on disk")
    unconvertible = load(fx)["unconvertible"]
    names = load(CUR)["code_to_name"]
    assert [names[str(c)] for c in unconvertible] == ["Bitcoin"]


@needs_maps
def test_every_code_in_the_splits_is_covered():
    pdir = load_paths()["processed_dir"]
    f = pdir / "amlworld_test.parquet"
    if not f.exists():
        pytest.skip(f"{f} not on disk")
    d = pd.read_parquet(f, columns=["Sent Currency", "Received Currency", "Payment Format"])
    cur, fmt = load(CUR)["code_to_name"], load(FMT)["code_to_name"]
    used_cur = set(d["Sent Currency"]) | set(d["Received Currency"])
    missing = [c for c in used_cur if str(int(c)) not in cur]
    assert not missing, f"currency codes in the split with no name: {sorted(missing)}"
    missing = [c for c in set(d["Payment Format"]) if str(int(c)) not in fmt]
    assert not missing, f"payment format codes in the split with no name: {sorted(missing)}"


@pytest.mark.skipif(not BANK.exists(), reason="contract/bank_names.json not on disk")
def test_bank_names_exist_and_are_not_a_join_key():
    """The opposite was assumed. Names exist; they are simply not unique."""
    d = load(BANK)
    assert d["meta"]["present"] is True
    assert d["meta"]["all_resolved"] is True, "some bank code in the splits has no name"
    assert d["meta"]["name_is_unique_key"] is False, (
        "if names ever become unique per id, the 'display only' warning can be relaxed")
    assert len(d["id_to_name"]) == d["meta"]["n_bank_ids"]
