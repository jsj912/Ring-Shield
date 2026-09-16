"""Checks for contract/make_rings_stub.py on the 1% dry-run sample of rings.

Needs contract/out/scored_edges_gine_1.parquet (full, from make_scored_edges.py) and
experiments/legacy_E7_test_tuned/rings_gine.csv.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_rings_stub import DRY_RUN_FRAC, RINGS_PA_SCHEMA, main, make_rings_stub  # noqa: E402
from contract.make_scored_edges import load_paths  # noqa: E402
from contract.schema import E7_RING_CSV_COLUMNS, RINGS_ORDER, TOPOLOGY_TYPES  # noqa: E402

PATHS = load_paths()


def tables_equal(a, b) -> bool:
    """pyarrow Table.equals treats NaN != NaN; conservation_closure is all-NaN by design."""
    if not a.schema.equals(b.schema):
        return False
    nan_a = a.column("conservation_closure").to_pandas().isna().all()
    nan_b = b.column("conservation_closure").to_pandas().isna().all()
    return nan_a and nan_b and a.drop_columns(["conservation_closure"]).equals(b.drop_columns(["conservation_closure"]))


E7_CSV = REPO_ROOT / "experiments" / "legacy_E7_test_tuned" / "rings_gine.csv"
SCORED = REPO_ROOT / "contract" / "out" / "scored_edges_gine_1.parquet"
AGG, SEED = "cc", 1

pytestmark = pytest.mark.skipif(
    not (E7_CSV.exists() and SCORED.exists() and PATHS["account_bank_map"].exists()),
    reason="rings-stub inputs not on disk (run make_scored_edges.py first)",
)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("rings") / f"rings_stub_{AGG}_dryrun.parquet"
    log = make_rings_stub(E7_CSV, SCORED, AGG, out, seed=SEED, dry_run=True)
    return {"out": out, "log": log, "df": pd.read_parquet(out), "table": pq.read_table(out)}


@pytest.fixture(scope="module")
def e7_rows(run):
    e7 = pd.read_csv(E7_CSV)
    idx = run["df"]["ring_id"].str.split("-").str[-1].astype(int)
    return e7.set_index("ring_idx").loc[idx.values]


@pytest.fixture(scope="module")
def scored():
    return pd.read_parquet(SCORED, columns=["edge_id", "from_id", "to_id", "from_bank", "timestamp", "is_seed"])


def test_e7_header_constant_matches_file():
    assert pd.read_csv(E7_CSV, nrows=0).columns.tolist() == E7_RING_CSV_COLUMNS


def test_columns_order_and_arrow_schema(run):
    assert list(run["df"].columns) == RINGS_ORDER
    assert run["table"].schema.equals(RINGS_PA_SCHEMA), run["table"].schema


def test_dry_run_is_one_percent_at_least_one(run):
    n_in = run["log"]["n_rings_in"]
    assert n_in == 178
    assert len(run["df"]) == max(1, round(DRY_RUN_FRAC * n_in)) == run["log"]["n_rings_out"]
    assert run["df"]["ring_id"].is_unique


def test_dry_run_is_deterministic(run, tmp_path):
    out2 = tmp_path / "again.parquet"
    make_rings_stub(E7_CSV, SCORED, AGG, out2, seed=SEED, dry_run=True)
    assert tables_equal(pq.read_table(out2), run["table"])


# 1. members parsed from '|' -------------------------------------------------------
def test_members_parsed_from_pipe_string(run, e7_rows):
    for m, s, n in zip(run["df"]["members"], e7_rows["members"], run["df"]["n_members"]):
        assert list(m) == [int(x) for x in s.split("|")]
        assert len(m) == n >= 3


# 2. member_edges / seed_edges recomputed independently ----------------------------
def test_member_and_seed_edges(run, scored):
    for r in run["df"].itertuples(index=False):
        members = set(int(x) for x in r.members)
        sel = scored[scored["from_id"].isin(members) & scored["to_id"].isin(members)
                     & scored["timestamp"].between(r.start_time, r.end_time)]
        assert sorted(r.member_edges) == sorted(sel["edge_id"].tolist())
        assert len(r.member_edges) > 0
        assert sorted(r.seed_edges) == sorted(sel.loc[sel["is_seed"], "edge_id"].tolist())
        assert set(r.seed_edges) <= set(r.member_edges)
        assert int(sel["timestamp"].min()) == r.start_time  # the offset-basis check


# time basis: E7 csv + offset ----------------------------------------------------------
def test_times_are_e7_plus_offset(run, e7_rows):
    off = PATHS["legacy_csv_time_offset_s"]
    assert off == 10 == run["log"]["timestamp_offset_added_seconds"]
    assert (run["df"]["start_time"].values == e7_rows["start_time"].values + off).all()
    assert (run["df"]["end_time"].values == e7_rows["end_time"].values + off).all()
    assert np.allclose(run["df"]["duration_hours"], (run["df"]["end_time"] - run["df"]["start_time"]) / 3600, atol=0.01)


# 3. placeholders ---------------------------------------------------------------------
def test_placeholders(run):
    df = run["df"]
    assert all(len(x) == 0 for x in df["expanded_edges"])
    assert df["conservation_closure"].isna().all()
    assert (df["topology_type"] == "UNKNOWN").all()
    for p in df["topology_probs"]:
        assert len(p) == len(TOPOLOGY_TYPES) == 8 and np.allclose(p, 0.125)
    for c in ("source_accounts", "sink_accounts", "mule_accounts"):
        assert all(len(x) == 0 for x in df[c])
    # empty lists keep their element type
    for c in ("expanded_edges", "source_accounts", "sink_accounts", "mule_accounts"):
        t = run["table"].schema.field(c).type
        assert pa.types.is_list(t) and t.value_type == pa.int64(), (c, t)


# 4. ring_id and tenant_id ---------------------------------------------------------------
def test_ring_id_and_tenant(run, e7_rows):
    assert run["df"]["ring_id"].tolist() == [f"{AGG}-{i}" for i in e7_rows.index]
    assert (run["df"]["aggregator_id"] == AGG).all()
    bank_of = pd.read_parquet(PATHS["account_bank_map"]).set_index("account_id")["bank_id"]
    for r in run["df"].itertuples(index=False):
        banks = bank_of.loc[list(r.members)]
        assert banks.notna().all()
        counts = banks.value_counts()
        top = counts[counts == counts.max()].index.min()  # mode, ties -> smallest bank id
        assert r.tenant_id == top


def test_carried_over_e7_values(run, e7_rows):
    for c in ("n_edges", "confidence", "max_edge_prob", "density"):
        assert np.allclose(run["df"][c].values, e7_rows[c].values), c


def test_log_and_cli(run, tmp_path):
    log = json.loads(Path(str(run["out"]) + ".log.json").read_text())
    assert log["columns"] == RINGS_ORDER and len(log["git_commit"]) == 40
    out = tmp_path / "cli.parquet"
    main(["--e7-csv", str(E7_CSV), "--scored-edges", str(SCORED), "--aggregator-id", AGG,
          "--seed", str(SEED), "--dry-run", "--out", str(out)])
    assert tables_equal(pq.read_table(out), run["table"])


def test_wrong_e7_columns_raise(tmp_path):
    bad = pd.read_csv(E7_CSV, nrows=5).drop(columns="density")
    p = tmp_path / "bad.csv"
    bad.to_csv(p, index=False)
    with pytest.raises(AssertionError, match="unexpected E7 columns"):
        make_rings_stub(p, SCORED, AGG, tmp_path / "x.parquet")


def test_mode_smallest_tie_break():
    from contract.make_rings_stub import _mode_smallest
    assert _mode_smallest(np.array([5, 3, 5, 3])) == 3
    assert _mode_smallest(np.array([7])) == 7
    assert math.isnan(float("nan"))  # sanity for the NaN placeholder semantics used above
