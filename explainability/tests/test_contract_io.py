"""XR-01: the contract readers load the real files and fail loudly, naming the problem, on anything else.

Run from the repository root:  python -m pytest explainability/tests -q
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from contract.schema import RINGS_COLUMNS, SCORED_EDGES_COLUMNS
from explainability.contract_io import (ContractError, provenance, read_rings, read_scored_edges, repo_path,
                                        validate_rings, validate_scored_edges)
from explainability.tests import fixtures as fx

SEEDS = [1, 2, 3, 4, 5]
SCORES = "contract/out/scored_edges_gine_causal_{}.parquet"
RINGS = "contract/out/rings_full_gine_causal_{}.parquet"
STUB = "contract/out/rings_stub_cc.parquet"


def _need(*paths):
    missing = [p for p in paths if not repo_path(p).exists()]
    if missing:
        pytest.skip(f"contract files not on disk: {missing}")


@pytest.fixture(scope="module")
def real1():
    _need(SCORES.format(1), RINGS.format(1))
    se = read_scored_edges(SCORES.format(1))
    return se, read_rings(RINGS.format(1), scored_edges=se)


# ----------------------------------------------------------------------------- the real files load
@pytest.mark.parametrize("seed", SEEDS)
def test_real_files_load(seed):
    _need(SCORES.format(seed), RINGS.format(seed))
    se = read_scored_edges(SCORES.format(seed))
    rings = read_rings(RINGS.format(seed), scored_edges=se)
    assert len(se) == 863_900 and len(rings) > 0
    assert provenance(se, rings) == {"model_id": "gine_causal", "seed": seed, "aggregator_id": "full"}


def test_stub_loads(real1):
    _need(STUB)
    se, _ = real1
    stub = read_rings(STUB, scored_edges=se)
    assert provenance(se, stub)["aggregator_id"] == "cc"
    assert all(len(e) == 0 for e in stub["expanded_edges"])


# ----------------------------------------------------------------------------- missing fields are named
@pytest.mark.parametrize("col", list(SCORED_EDGES_COLUMNS))
def test_missing_scored_edges_field_is_named(real1, col):
    se, _ = real1
    with pytest.raises(ContractError, match=rf"missing field\(s\) \['{col}'\]"):
        validate_scored_edges(se.head(50).drop(columns=[col]))


@pytest.mark.parametrize("col", list(RINGS_COLUMNS))
def test_missing_rings_field_is_named(real1, col):
    _, rings = real1
    with pytest.raises(ContractError, match=rf"missing field\(s\) \['{col}'\]"):
        validate_rings(rings.head(5).drop(columns=[col]))


def test_missing_field_in_a_file_on_disk_is_named(real1, tmp_path):
    _, rings = real1
    p = tmp_path / "rings_without_members.parquet"
    rings.drop(columns=["members"]).to_parquet(p)
    with pytest.raises(ContractError, match=r"missing field\(s\) \['members'\]"):
        read_rings(p)


def test_extra_field_is_rejected(real1):
    _, rings = real1
    with pytest.raises(ContractError, match=r"unexpected field\(s\) \['member_accounts'\]"):
        validate_rings(rings.head(5).assign(member_accounts=rings.head(5)["members"]))


# ----------------------------------------------------------------------------- wrong types
def test_wrong_scalar_type_is_rejected(real1):
    se, _ = real1
    bad = se.head(50).assign(score_calibrated=se.head(50)["score_calibrated"].astype(str))
    with pytest.raises(ContractError, match="score_calibrated: expected float64"):
        validate_scored_edges(bad)


def test_wrong_list_element_type_is_rejected(real1):
    _, rings = real1
    bad = rings.head(3).copy()
    bad["members"] = [[float(a) for a in m] for m in bad["members"]]
    with pytest.raises(ContractError, match="members: expected list<int64>"):
        validate_rings(bad)


# ----------------------------------------------------------------------------- invariants
def _one_ring(rings, **changes):
    r = rings.head(1).copy()
    for k, v in changes.items():
        r[k] = [v]
    return r


def test_seed_edges_not_in_member_edges_is_rejected(real1):
    se, rings = real1
    row = rings.iloc[0]
    with pytest.raises(ContractError, match="seed_edges not a subset of member_edges"):
        validate_rings(_one_ring(rings, member_edges=[e for e in row.member_edges if e != row.seed_edges[0]]))


def test_expanded_probs_length_mismatch_is_rejected(real1):
    _, rings = real1
    i = next(i for i, e in enumerate(rings["expanded_edges"]) if e)
    r = rings.iloc[[i]].copy()
    r["expanded_edge_probs"] = [list(r["expanded_edge_probs"].iloc[0])[:-1]]
    with pytest.raises(ContractError, match="expanded_edge_probs for"):
        validate_rings(r)


def test_topology_probs_not_a_distribution_is_rejected(real1):
    _, rings = real1
    with pytest.raises(ContractError, match="topology_probs do not form a distribution"):
        validate_rings(_one_ring(rings, topology_probs=[0.5] * 8))


def test_edge_missing_from_scored_edges_is_rejected(real1):
    se, rings = real1
    row = rings.iloc[0]
    with pytest.raises(ContractError, match="not in scored_edges"):
        validate_rings(rings.head(1), se[se["edge_id"] != row.member_edges[0]])


def test_rings_from_another_seed_are_rejected(real1):
    _need(SCORES.format(2))
    _, rings = real1
    se2 = read_scored_edges(SCORES.format(2))
    with pytest.raises(ContractError, match="rings do not belong to these scored_edges"):
        provenance(se2, rings)


def test_nan_conservation_closure_is_kept_as_nan(real1):
    _, rings = real1
    nan = rings["conservation_closure"].isna()
    assert int(nan.sum()) == 6                           # docs/TYPING.md: 6 of 108 rings for seed 1
    assert all(math.isnan(x) for x in rings.loc[nan, "conservation_closure"])


# ----------------------------------------------------------------------------- the fixtures (step 3)
def test_every_fixture_passes_validation():
    se, rings = fx.fixture_contract()
    validate_scored_edges(se, "fixture scored_edges")
    validate_rings(rings, se, what="fixture rings")
    assert set(fx.PATTERN_TYPES) <= set(rings["topology_type"])
    assert set(fx.EDGE_CASES) <= set(rings["ring_id"])


def test_broken_fixture_seed_not_in_members_is_rejected():
    se, rings = fx.fixture_contract()
    broken = rings.copy()
    broken.at[0, "seed_edges"] = list(broken.at[0, "seed_edges"]) + [max(se["edge_id"])]
    with pytest.raises(ContractError, match="seed_edges not a subset of member_edges"):
        validate_rings(broken, se)
