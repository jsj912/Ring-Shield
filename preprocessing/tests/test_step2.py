"""Step 2 checks: bank columns (2.1), ring scope (2.2) and ceiling (2.3).

Dry-run tests (1% of rows / rings) always run when the processed data is on disk; the
"checks before moving on" run against docs/ring_scope.json and the in-place Parquets and
are skipped until those exist.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from preprocessing.account_bank import (  # noqa: E402
    ACCOUNT_BANK_COLUMNS, bank_of_series, load_account_bank_map, load_paths,
)
from preprocessing import add_bank_columns as abc  # noqa: E402
from preprocessing import ring_scope as rs  # noqa: E402

PATHS = load_paths()
PROC = PATHS["processed_dir"]
GT = PROC / "amlworld_ring_ground_truth.parquet"
SCOPE_JSON = REPO_ROOT / "docs" / "ring_scope.json"
GT_DOC = REPO_ROOT / "docs" / "RING_GROUND_TRUTH_DEFINITION.md"
SEED = 1

pytestmark = pytest.mark.skipif(
    not all((PROC / f).exists() for f in abc.TARGETS) or not PATHS["account_bank_map"].exists(),
    reason="processed data not on disk",
)


@pytest.fixture(scope="module")
def bank_of():
    amap = load_account_bank_map()
    assert list(amap.columns) == ACCOUNT_BANK_COLUMNS
    return bank_of_series(amap)


# ---------------------------------------------------------------- 2.1 dry run
@pytest.fixture(scope="module")
def banks_dry(tmp_path_factory):
    out = tmp_path_factory.mktemp("banks")
    abc.main(["--dry-run", "--out-dir", str(out), "--seed", str(SEED)])
    return out


def test_bank_columns_dry_run(banks_dry, bank_of):
    for name in abc.TARGETS:
        df = pd.read_parquet(banks_dry / name)
        src_n = pd.read_parquet(PROC / name, columns=["from_id"]).shape[0]
        assert len(df) == round(abc.DRY_RUN_FRAC * src_n), name
        cols = list(df.columns)
        assert cols[cols.index("to_id") + 1: cols.index("to_id") + 3] == ["from_bank", "to_bank"], name
        assert df["from_bank"].dtype == "int64" and df["to_bank"].dtype == "int64"
        assert (bank_of.reindex(df["from_id"].values).values == df["from_bank"].values).all()
        assert (bank_of.reindex(df["to_id"].values).values == df["to_bank"].values).all()
        log = json.loads((banks_dry / (name + ".banks.log.json")).read_text())
        assert log["n_rows_out"] == len(df) and log["dry_run"] is True


def test_bank_columns_idempotent(banks_dry, bank_of):
    df = pd.read_parquet(banks_dry / "amlworld_ring_ground_truth.parquet")
    again = abc.add_bank_columns(df, bank_of)
    pd.testing.assert_frame_equal(df, again)
    assert list(again.columns).count("from_bank") == 1


def test_bank_columns_missing_account_raises(bank_of):
    df = pd.DataFrame({"from_id": [0, 10**9], "to_id": [1, 2]})
    with pytest.raises(AssertionError, match="no bank_code"):
        abc.add_bank_columns(df, bank_of)


# ---------------------------------------------------------------- 2.2 / 2.3 dry run
@pytest.fixture(scope="module")
def scope_dry(tmp_path_factory):
    out = tmp_path_factory.mktemp("scope") / "ring_scope_dryrun.json"
    res = rs.run(GT, PROC, out, seed=SEED, dry_run=True, argv=["--dry-run"])
    return {"out": out, "res": res, "json": json.loads(out.read_text(encoding="utf-8"))}


def test_ring_scope_dry_run_sample_size(scope_dry):
    j = scope_dry["json"]
    assert j["n_rings_total_in_gt"] == 370
    assert j["summary"]["n_rings"] == len(j["per_ring"]) == max(1, round(rs.DRY_RUN_FRAC * 370)) == 4
    assert j["dry_run"] is True and j["policy"]["scope_policy"] == "strict"


def test_ring_scope_per_ring_recomputed_independently(scope_dry, bank_of):
    gt = pd.read_parquet(GT)
    splits = rs.load_split_labels(PROC)
    bounds = {s: (int(d["Timestamp"].min()), int(d["Timestamp"].max())) for s, d in splits.items()}
    for r in scope_dry["json"]["per_ring"]:
        g = gt[gt["ring_id"] == r["ring_id"]]
        assert len(g) == r["n_pattern_lines"] == r["n_txn"]
        assert r["pattern_type"] == g["pattern_type"].iloc[0]
        assert r["start"] == int(g["timestamp_int"].min()) and r["end"] == int(g["timestamp_int"].max())
        members = set(g["from_id"]) | set(g["to_id"])
        assert r["n_members"] == len(members)
        assert r["n_banks"] == bank_of.loc[sorted(members)].nunique()
        assert r["cross_bank"] == (r["n_banks"] > 1)
        ts = g["timestamp_int"]
        n_tr = int((ts <= bounds["train"][1]).sum())
        n_te = int((ts > bounds["val"][1]).sum())
        n_va = len(g) - n_tr - n_te
        assert (r["n_txn_train"], r["n_txn_val"], r["n_txn_test"]) == (n_tr, n_va, n_te)
        for s, d in splits.items():
            assert r[f"n_rows_{s}"] == int((d["ring_id"] == r["ring_id"]).sum())
        assert r["strict_test"] == (n_te == len(g)) and r["majority_test"] == (n_te / len(g) > 0.5)
        assert r["strict_val"] == (n_va == len(g)) and r["majority_val"] == (n_va / len(g) > 0.5)
        assert r["straddles"] == (sum(x > 0 for x in (n_tr, n_va, n_te)) > 1)
        assert np.isclose(r["frac_test"], n_te / len(g))


def test_ring_scope_summary_consistent_with_per_ring(scope_dry):
    j = scope_dry["json"]
    pr = pd.DataFrame(j["per_ring"])
    s = j["summary"]
    assert s["n_rings_cross_bank"] == int(pr["cross_bank"].sum())
    assert np.isclose(s["cross_bank_fraction"], pr["cross_bank"].mean())
    assert s["n_rings_lt3_members"] == int((pr["n_members"] < 3).sum())
    for sp in ("test", "val"):
        assert s[sp]["n_rings_strict"] == int(pr[f"strict_{sp}"].sum())
        assert s[sp]["n_rings_majority"] == int(pr[f"majority_{sp}"].sum())
        assert s[sp]["n_rings_straddling"] == int((pr[f"n_txn_{sp}"] > 0).mul(pr["straddles"]).sum())
        assert s[sp]["n_rings_strict"] <= s[sp]["n_rings_majority"] <= s[sp]["n_rings_touching_split"]


def test_ring_scope_ceiling_dry_run(scope_dry):
    j = scope_dry["json"]
    c = j["ceiling"]
    test = pd.read_parquet(PROC / "amlworld_test.parquet", columns=["ring_id", "Is Laundering"])
    keep = set(r["ring_id"] for r in j["per_ring"])
    test = test[test["ring_id"].isin(keep) | (test["ring_id"] == -1)]
    assert c["a_n_test_laundering_txn"] == int(test["Is Laundering"].sum())
    strict = {r["ring_id"] for r in j["per_ring"] if r["strict_test"]}
    assert c["b_n_test_laundering_txn_in_strict_ring"] == int(
        ((test["Is Laundering"] == 1) & test["ring_id"].isin(strict)).sum())
    m = c["c_strict_test_ring_members"]
    assert m["n_members_unrecoverable"] == m["n_members_no_test_txn"] + m["n_members_all_test_txn_licit"]
    assert 0.0 <= m["fraction_unrecoverable"] <= 1.0


def test_ring_scope_cli_dry_run_writes_dryrun_file(tmp_path):
    out = tmp_path / "scope.json"
    rs.main(["--out", str(out), "--dry-run", "--seed", str(SEED)])
    assert (tmp_path / "scope_dryrun.json").exists() and not out.exists()


# ---------------------------------------------------------------- checks before moving on (full)
full = pytest.mark.skipif(not SCOPE_JSON.exists(), reason="docs/ring_scope.json not produced yet")


@full
def test_check1_counts_written_into_gt_document():
    j = json.loads(SCOPE_JSON.read_text(encoding="utf-8"))
    n_test, n_val = j["summary"]["test"]["n_rings_strict"], j["summary"]["val"]["n_rings_strict"]
    assert n_test == 86 and n_val == 13  # 85 in the E7 metrics: see the document for why
    assert j["summary"]["test"]["n_rings_majority"] == 120
    doc = GT_DOC.read_text(encoding="utf-8")
    assert "____" not in doc, "blanks remain in the ground-truth document"
    assert re.search(rf"N_test_rings\s*=\s*\*?\*?{n_test}\b", doc), "N_test_rings not written"
    assert re.search(rf"N_val_rings\s*=\s*\*?\*?{n_val}\b", doc), "N_val_rings not written"
    assert "85" in doc and "10 s" in doc  # the explanation of the earlier 85 must be there


@full
def test_check2_every_gt_account_has_bank_and_cross_bank_fraction_recorded(bank_of):
    gt = pd.read_parquet(GT)
    assert {"from_bank", "to_bank"} <= set(gt.columns)
    assert gt["from_bank"].notna().all() and gt["to_bank"].notna().all()
    accounts = pd.Index(sorted(set(gt["from_id"]) | set(gt["to_id"])))
    assert bank_of.reindex(accounts).notna().all()
    assert (bank_of.reindex(gt["from_id"].values).values == gt["from_bank"].values).all()
    j = json.loads(SCOPE_JSON.read_text(encoding="utf-8"))
    assert j["summary"]["n_rings"] == 370
    assert 0 < j["summary"]["cross_bank_fraction"] <= 1
    assert j["summary"]["n_rings_cross_bank"] == 366
    doc = GT_DOC.read_text(encoding="utf-8")
    assert f"{j['summary']['cross_bank_fraction']:.1%}" in doc or str(j["summary"]["n_rings_cross_bank"]) in doc


@full
def test_check2_split_parquets_have_bank_columns(bank_of):
    for name in abc.TARGETS[:3]:
        df = pd.read_parquet(PROC / name, columns=["from_id", "to_id", "from_bank", "to_bank"])
        assert df["from_bank"].notna().all() and df["to_bank"].notna().all()
        s = df.sample(n=5000, random_state=SEED)
        assert (bank_of.reindex(s["from_id"].values).values == s["from_bank"].values).all()
        assert (bank_of.reindex(s["to_id"].values).values == s["to_bank"].values).all()
        assert Path(str(PROC / name) + ".banks.log.json").exists()


@full
def test_check3_ceiling_numbers_recorded_with_command():
    j = json.loads(SCOPE_JSON.read_text(encoding="utf-8"))
    assert j["command"].startswith("python preprocessing/ring_scope.py")
    c = j["ceiling"]
    assert c["a_n_test_laundering_txn"] == 1611
    assert 0 < c["b_n_test_laundering_txn_in_strict_ring"] <= c["b_n_test_laundering_txn_in_any_ring"] <= 1611
    assert 0.0 <= c["c_strict_test_ring_members"]["fraction_unrecoverable"] <= 1.0
    assert 0.0 <= c["c_all_ring_members"]["fraction_unrecoverable"] <= 1.0
    doc = GT_DOC.read_text(encoding="utf-8")
    for v in (c["a_n_test_laundering_txn"], c["b_n_test_laundering_txn_in_strict_ring"]):
        assert re.search(rf"\b{v:,}\b|\b{v}\b", doc), v
    assert "preprocessing/ring_scope.py" in doc
