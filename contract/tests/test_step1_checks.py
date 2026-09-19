"""Step 1 'Checks before moving on', run against the FULL contract outputs.

    python contract/make_scored_edges.py --preds experiments/E6_tgn/predictions_with_ids.csv --model-id gine --seed 1
    python contract/make_rings_stub.py --e7-csv experiments/legacy_E7_test_tuned/rings_gine.csv \
        --scored-edges contract/out/scored_edges_gine_1.parquet --aggregator-id cc
    python -m pytest contract/tests/test_step1_checks.py -q

Skipped when the full outputs are not on disk.
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from contract.schema import (  # noqa: E402
    LABELS_ORDER, RINGS_ORDER, SCORED_EDGES_ORDER, render_readme,
)

PATHS = load_paths()
OUT = REPO_ROOT / "contract" / "out"
SCORED = OUT / "scored_edges_gine_1.parquet"
LABELS = OUT / "labels_test.parquet"
RINGS = OUT / "rings_stub_cc_step1_legacy.parquet"  # the Step 1 stub, kept; rings_stub_cc.parquet is rebuilt in Step 3c
TEST_PARQUET = PATHS["processed_dir"] / "amlworld_test.parquet"
README = REPO_ROOT / "contract" / "README.md"

pytestmark = pytest.mark.skipif(
    not (SCORED.exists() and LABELS.exists() and RINGS.exists() and TEST_PARQUET.exists()),
    reason="full contract outputs not on disk",
)


def _load_both_ways(path: Path):
    """Check 4: loads with pandas and pyarrow without any warning."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        df = pd.read_parquet(path)
        table = pq.read_table(path)
    return df, table


@pytest.fixture(scope="module")
def scored():
    return _load_both_ways(SCORED)[0]


@pytest.fixture(scope="module")
def labels():
    return _load_both_ways(LABELS)[0]


@pytest.fixture(scope="module")
def rings():
    return _load_both_ways(RINGS)[0]


# Check 1 ---------------------------------------------------------------------------
def test_check1_scored_edges_counts(scored, labels):
    assert len(scored) == 863_900
    assert scored["edge_id"].nunique() == 863_900
    nan = scored["score_raw"].isna()
    assert int(nan.sum()) == 841
    assert not scored.loc[nan, "is_seed"].any()
    assert (scored["score_calibrated"].isna() == nan).all()
    assert len(labels) == 863_900 and labels["edge_id"].is_unique
    assert int(labels["true_label"].sum()) == 1_611
    assert "true_label" not in scored.columns


# Check 2 ---------------------------------------------------------------------------
def test_check2_join_back_to_test_parquet(scored):
    t = pd.read_parquet(TEST_PARQUET, columns=["EdgeID", "from_id", "to_id", "Timestamp"])
    m = scored[["edge_id", "from_id", "to_id", "timestamp"]].merge(
        t, left_on="edge_id", right_on="EdgeID", how="inner", suffixes=("", "_t"), validate="one_to_one")
    assert len(m) == 863_900
    assert (m["from_id"] == m["from_id_t"]).all()
    assert (m["to_id"] == m["to_id_t"]).all()
    assert (m["timestamp"] == m["Timestamp"]).all()


# Check 3 ---------------------------------------------------------------------------
def test_check3_rings(rings):
    bank_of = pd.read_parquet(PATHS["account_bank_map"]).set_index("account_id")["bank_code"]
    assert len(rings) == 178
    assert (rings["n_members"] >= 3).all()
    assert (rings["members"].map(len) >= 3).all()
    assert (rings["member_edges"].map(len) > 0).all()
    all_members = pd.Index(sorted({int(a) for m in rings["members"] for a in m}))
    assert bank_of.reindex(all_members).notna().all()
    assert rings["ring_id"].is_unique
    assert rings["tenant_id"].notna().all()


def test_check3_ring_start_time_is_min_member_edge(rings, scored):
    ts = scored.set_index("edge_id")["timestamp"]
    for r in rings.itertuples(index=False):
        assert int(ts.loc[list(r.member_edges)].min()) == r.start_time, r.ring_id
        assert set(r.seed_edges) <= set(r.member_edges)


# Check 4 ---------------------------------------------------------------------------
def test_check4_loads_without_warnings_and_columns_match_schema():
    for path, order in ((SCORED, SCORED_EDGES_ORDER), (LABELS, LABELS_ORDER), (RINGS, RINGS_ORDER)):
        df, table = _load_both_ways(path)
        assert list(df.columns) == order, path
        assert table.schema.names == order, path


def test_check4_readme_generated_from_schema_and_lists_all_columns():
    text = README.read_text(encoding="utf-8")
    assert text == render_readme(), "contract/README.md is out of date: run `python contract/schema.py`"
    for col in set(SCORED_EDGES_ORDER) | set(LABELS_ORDER) | set(RINGS_ORDER):
        assert re.search(rf"\| `{re.escape(col)}` \|", text), col


def test_data_manifest_matches_disk():
    import subprocess
    r = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "data_manifest.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
