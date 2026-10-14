"""`contract.schema.ring_record` against the L4 layer's own frame type check.

The L4 layer validates a rings frame with `explainability.contract_io.check_frame_types`, which
takes the exact column set and then the dtype of every column. When that package is on the branch
this module imports the real function, so the test exercises the validator the other side actually
runs; otherwise it falls back to a copy of the same rule, kept byte-faithful to
`explainability/contract_io.py::_column_type_ok` so the two cannot drift silently.

What this guards: `pd.DataFrame(rows, columns=RINGS_ORDER)` materialises any column the rows omit
as all-NaN float64. The names are then all present -- a column check passes -- and the dtype check
fails on columns the producer never knew existed. A schema bump therefore breaks every fixture
builder that enumerates its own fields, and the failure reads like a type bug rather than a missing
default. `ring_record` is the single place those defaults live.
"""
from __future__ import annotations

import math
import numbers
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.schema import (  # noqa: E402
    RINGS_COLUMNS,
    RINGS_NAN_OK,
    RINGS_ORDER,
    TOPOLOGY_TYPES,
    ring_record,
)

# --------------------------------------------------------------------------- the validator
try:                                                      # the real thing, once L4 is merged in
    from explainability.contract_io import ContractError, check_frame_types
    VALIDATOR = "explainability.contract_io.check_frame_types"
except Exception:                                         # pragma: no cover - L4 not on this branch
    class ContractError(Exception):
        pass

    def _is_int(x) -> bool:
        return isinstance(x, numbers.Integral) and not isinstance(x, (bool, np.bool_))

    def _is_real(x) -> bool:
        return isinstance(x, numbers.Real) and not isinstance(x, (bool, np.bool_))

    def _column_type_ok(s: pd.Series, spec_type: str) -> bool:
        if spec_type == "int64":
            return pd.api.types.is_integer_dtype(s) and not pd.api.types.is_bool_dtype(s)
        if spec_type == "float64":
            return pd.api.types.is_float_dtype(s)
        if spec_type == "bool":
            return pd.api.types.is_bool_dtype(s)
        if spec_type == "string":
            return pd.api.types.is_string_dtype(s) and all(isinstance(v, str) for v in s)
        if spec_type.startswith("list<"):
            elem_ok = _is_int if spec_type == "list<int64>" else _is_real
            return all(isinstance(v, (list, tuple, np.ndarray)) and all(elem_ok(x) for x in v) for v in s)
        raise AssertionError(f"unknown contract type {spec_type!r}")

    def check_frame_types(df: pd.DataFrame, spec: dict, what: str) -> None:
        missing = [c for c in spec if c not in df.columns]
        extra = [c for c in df.columns if c not in spec]
        if missing or extra:
            raise ContractError(f"{what}: missing {missing}; extra {extra}")
        bad = [f"{c}: expected {t}, got {df[c].dtype}" for c, (t, _) in spec.items()
               if not _column_type_ok(df[c], t)]
        if bad:
            raise ContractError(f"{what}: wrong type(s): " + "; ".join(bad))

    VALIDATOR = "local copy of explainability.contract_io's rule"


def frame(rows: list[dict]) -> pd.DataFrame:
    """Exactly how the L4 fixtures build a rings frame."""
    return pd.DataFrame(rows, columns=RINGS_ORDER)


# --------------------------------------------------------------------------- the contract
def test_every_column_is_present_in_contract_order():
    rec = ring_record()
    assert list(rec) == RINGS_ORDER, "ring_record must yield the contract column order"
    assert len(rec) == len(RINGS_COLUMNS)


def test_a_bare_record_passes_the_frame_type_check():
    check_frame_types(frame([ring_record()]), RINGS_COLUMNS, "bare ring_record")


def test_many_bare_records_pass():
    check_frame_types(frame([ring_record() for _ in range(5)]), RINGS_COLUMNS, "five bare records")


@pytest.mark.parametrize("col", RINGS_ORDER)
def test_each_column_alone_survives_an_override(col):
    """Overriding one column must not disturb the type of any other."""
    typ = RINGS_COLUMNS[col][0]
    value = {"int64": 7, "float64": 0.5, "string": "x", "bool": True,
             "list<int64>": [1, 2], "list<float64>": [0.25, 0.75]}[typ]
    if col == "topology_probs":
        value = [1.0 / len(TOPOLOGY_TYPES)] * len(TOPOLOGY_TYPES)
    check_frame_types(frame([ring_record(**{col: value})]), RINGS_COLUMNS, f"override {col}")


def test_defaults_are_the_documented_kinds():
    rec = ring_record()
    for col, (typ, _) in RINGS_COLUMNS.items():
        v = rec[col]
        if typ == "int64":
            assert v == 0 and isinstance(v, int) and not isinstance(v, bool), col
        elif typ == "float64":
            assert isinstance(v, float), col
            assert math.isnan(v) == (col in RINGS_NAN_OK), (
                f"{col}: NaN default is only for {RINGS_NAN_OK}")
        elif typ == "string":
            assert isinstance(v, str), col
        elif typ.startswith("list<"):
            assert isinstance(v, list), col


def test_topology_probs_default_is_a_distribution():
    """So a bare record is not merely well typed but semantically acceptable."""
    probs = ring_record()["topology_probs"]
    assert len(probs) == len(TOPOLOGY_TYPES)
    assert abs(sum(probs) - 1.0) < 1e-9
    assert ring_record()["topology_type"] == "UNKNOWN"


def test_the_ccy_fields_default_without_asserting_anything():
    """v2's currency fields must default to 'nothing measured', never to a claim."""
    rec = ring_record()
    assert math.isnan(rec["conservation_closure_ccy"])
    assert rec["n_accounts_ccy_undefined"] == 0
    assert rec["n_roles_changed_ccy"] == 0
    assert rec["n_currencies"] == 0
    for col in ("source_accounts_ccy", "sink_accounts_ccy", "mule_accounts_ccy",
                "undetermined_accounts_ccy"):
        assert rec[col] == [], col


def test_an_unknown_override_is_refused():
    with pytest.raises(KeyError, match="not rings-contract columns"):
        ring_record(conservation_clousre=1.0)      # deliberate typo


# --------------------------------------------------------------------------- the failure it prevents
def test_omitting_a_column_is_exactly_the_failure_this_helper_prevents():
    """The pre-helper pattern: a row dict that enumerates its own fields and misses the new ones."""
    rec = ring_record()
    v1_only = {c: rec[c] for c in RINGS_ORDER if not c.endswith("_ccy")
               and c not in ("n_accounts_ccy_undefined", "n_roles_changed_ccy", "n_currencies")}
    df = frame([v1_only])
    assert set(df.columns) == set(RINGS_COLUMNS), "names are all present -- a column check passes"
    with pytest.raises(ContractError, match="wrong type"):
        check_frame_types(df, RINGS_COLUMNS, "rings")
    for c in ("source_accounts_ccy", "n_currencies"):
        assert df[c].isna().all() and df[c].dtype == "float64", (
            f"{c} should be all-NaN float64, the symptom described in the docstring")
