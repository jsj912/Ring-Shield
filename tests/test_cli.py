"""Step 5: the research CLI (python -m ringshield run / train / eval) on the 1 % dry-run data.

    python -m pytest tests/test_cli.py -q          # < 2 min

Fixture: a scored_edges contract parquet for a 1 % sample (seed 1) of the test split with the
gfpxgb seed-1 scores (experiments/R2_b0/gfpxgb_scores) and a model dir exported from the
gfpxgb seed-1 run_rings output, with min_size 2 / 3 % seeds so the sparse sample still forms
rings. One run restricts to a single bank via --edge-subset and asserts every member edge and
seed edge of every ring is in the subset.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.schema import RINGS_ORDER, SCORED_EDGES_ORDER  # noqa: E402
from ringshield.model_dir import read_model, write_model  # noqa: E402
from ringshield.rings import RINGS_PA_SCHEMA  # noqa: E402

SCORES = REPO_ROOT / "experiments" / "R2_b0" / "gfpxgb_scores" / "scores_test_seed1.parquet"
GT = REPO_ROOT / "data" / "processed" / "amlworld_ring_ground_truth.parquet"
TEST_PQ = REPO_ROOT / "data" / "processed" / "amlworld_test.parquet"
PY = sys.executable
pytestmark = pytest.mark.skipif(not (SCORES.exists() and GT.exists() and TEST_PQ.exists()),
                                reason="gfpxgb scores / processed data not on disk")


def cli(*args, cwd=REPO_ROOT):
    res = subprocess.run([PY, "-m", "ringshield", *map(str, args)], cwd=cwd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    d = tmp_path_factory.mktemp("cli")
    from ringshield.scored_edges import build_scored_edges
    se = build_scored_edges(SCORES, "test", model_id="gfpxgb", seed=1)
    se = se.sample(frac=0.01, random_state=1).sort_values("edge_id").reset_index(drop=True)   # the 1 % dry-run sample
    assert list(se.columns) == SCORED_EDGES_ORDER
    se.to_parquet(d / "scored_edges_dryrun.parquet", index=False)
    write_model(d / "model_cc", model_id="gfpxgb", seed=1, aggregator="cc",
                params={"seed_frac_pct": 3.0, "min_size": 2, "max_gap_hours": None},
                feature_set="trailing_closescycle", source="tests/test_cli.py fixture (1 % sample)")
    return {"dir": d, "se": se}


def test_run_full_sample(work):
    d, se = work["dir"], work["se"]
    t0 = time.time()
    rc, out, err = cli("run", "--scores", d / "scored_edges_dryrun.parquet", "--model-dir", d / "model_cc",
                       "--aggregator", "cc", "--out", d / "rings.parquet")
    assert rc == 0, err
    assert time.time() - t0 < 60
    assert pq.read_schema(d / "rings.parquet").equals(RINGS_PA_SCHEMA)
    rings = pd.read_parquet(d / "rings.parquet")
    assert list(rings.columns) == RINGS_ORDER and len(rings) > 0
    assert rings["ring_id"].str.match(r"^cc-gfpxgb-1-\d+$").all() and rings["ring_id"].is_unique
    assert (rings["aggregator_id"] == "cc").all() and (rings["n_members"] >= 2).all()
    log = json.loads((d / "rings.parquet.log.json").read_text())
    assert log["n_rings"] == len(rings) and log["quantile_cut"]["rule"].startswith("strict")
    # tenant rule: sender bank of the earliest seed edge
    idx = se.set_index("edge_id")
    for r in rings.head(20).itertuples(index=False):
        seeds = idx.loc[list(r.seed_edges), ["timestamp", "from_bank"]].sort_index().sort_values("timestamp", kind="stable")
        assert r.tenant_id == int(seeds.iloc[0]["from_bank"])
        assert set(r.seed_edges) <= set(r.member_edges)
    work["rings"] = rings


def test_run_single_bank_subset(work):
    d, se = work["dir"], work["se"]
    bank = int(se["from_bank"].value_counts().index[0])                 # the busiest sender bank
    subset = se[(se["from_bank"] == bank) | (se["to_bank"] == bank)][["edge_id"]]
    subset.to_parquet(d / "subset_bank.parquet", index=False)
    rc, out, err = cli("run", "--scores", d / "scored_edges_dryrun.parquet", "--edge-subset", d / "subset_bank.parquet",
                       "--model-dir", d / "model_cc", "--aggregator", "cc", "--out", d / "rings_bank.parquet")
    assert rc == 0, err
    rings = pd.read_parquet(d / "rings_bank.parquet")
    log = json.loads((d / "rings_bank.parquet.log.json").read_text())
    assert log["n_edges_used"] == len(subset) and log["n_edge_subset_ids"] == len(subset)
    ids = set(subset["edge_id"].tolist())
    assert len(rings) > 0
    for r in rings.itertuples(index=False):
        assert set(r.member_edges) <= ids, "member edge outside the subset"
        assert set(r.seed_edges) <= ids, "seed edge outside the subset"
    # the quantile was computed within the subset: seed count ~ 3 % of the subset, not of the file
    assert abs(log["quantile_cut"]["n_seeds"] - 0.03 * len(subset)) <= 0.05 * len(subset) + 5


def test_run_rejects_unknown_and_future_aggregators(work):
    d = work["dir"]
    rc, out, err = cli("run", "--scores", d / "scored_edges_dryrun.parquet", "--model-dir", d / "model_cc",
                       "--aggregator", "expand", "--out", d / "x.parquet")
    assert rc == 2 and "not an 'expand' model" in err          # a cc model dir cannot drive the expansion (Step 6)
    rc, out, err = cli("run", "--scores", d / "scored_edges_dryrun.parquet", "--model-dir", d / "model_cc",
                       "--aggregator", "full", "--out", d / "x.parquet")
    assert rc == 2 and "not a 'full' model" in err
    rc, out, err = cli("run", "--scores", d / "scored_edges_dryrun.parquet", "--model-dir", d / "nope",
                       "--aggregator", "cc", "--out", d / "x.parquet")
    assert rc == 2 and "model directory" in err


def test_train_copies_and_appends(work):
    d = work["dir"]
    rings = work["rings"]
    rows = [{"ring_id": rings.iloc[0]["ring_id"], "member_accounts": list(rings.iloc[0]["members"]),
             "member_edges": list(rings.iloc[0]["member_edges"]), "verdict": "confirm"},
            {"ring_id": rings.iloc[1]["ring_id"], "member_accounts": list(rings.iloc[1]["members"]),
             "member_edges": list(rings.iloc[1]["member_edges"]), "verdict": "reject"},
            {"ring_id": rings.iloc[2]["ring_id"], "member_accounts": list(rings.iloc[2]["members"])[:1],
             "member_edges": list(rings.iloc[2]["member_edges"])[:1], "verdict": "partial"}]
    schema = pa.schema([("ring_id", pa.string()), ("member_accounts", pa.list_(pa.int64())),
                        ("member_edges", pa.list_(pa.int64())), ("verdict", pa.string())])
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), d / "labels.parquet")
    rc, out, err = cli("train", "--component", "expansion", "--labels", d / "labels.parquet",
                       "--base-model-dir", d / "model_cc", "--out-model-dir", d / "model_v2")
    assert rc == 0, err
    assert read_model(d / "model_v2")["version"] == 2
    v = json.loads((d / "model_v2" / "version.json").read_text())
    assert v["n_labels"] == {"confirm": 1, "reject": 1, "partial": 1} and v["retrained"] is False and v["component"] == "expansion"
    extra = pd.read_parquet(d / "model_v2" / "extra_labels.parquet")
    assert len(extra) == 1 and extra.iloc[0]["verdict"] == "confirm" and extra.iloc[0]["ring_id"] == rows[0]["ring_id"]
    # second round appends and bumps the version
    rc, out, err = cli("train", "--component", "typing", "--labels", d / "labels.parquet",
                       "--base-model-dir", d / "model_v2", "--out-model-dir", d / "model_v3")
    assert rc == 0, err
    assert read_model(d / "model_v3")["version"] == 3 and len(pd.read_parquet(d / "model_v3" / "extra_labels.parquet")) == 2
    # bad verdict is rejected with exit code 2
    bad = rows[:1]
    bad[0] = {**bad[0], "verdict": "maybe"}
    pq.write_table(pa.Table.from_pylist(bad, schema=schema), d / "labels_bad.parquet")
    rc, out, err = cli("train", "--component", "affinity", "--labels", d / "labels_bad.parquet",
                       "--base-model-dir", d / "model_cc", "--out-model-dir", d / "model_bad")
    assert rc == 2 and "verdict" in err


def test_eval_and_holdout(work):
    d = work["dir"]
    rc, out, err = cli("eval", "--rings", d / "rings.parquet", "--truth", GT, "--scope", "test_visible",
                       "--window", "primary", "--scores", d / "scored_edges_dryrun.parquet", "--out", d / "metrics.json")
    assert rc == 0, err
    m = json.loads((d / "metrics.json").read_text())
    for k in ("ring_precision", "ring_recall", "ring_f1", "ring_recall_ge3", "member_coverage", "per_pattern", "jaccard_sweep"):
        assert k in m
    assert m["n_truth"] == 174 and m["window"] == "primary" and m["predicted_restricted_to_window"] is True
    gt = pd.read_parquet(GT, columns=["ring_id"])["ring_id"].unique().tolist()
    (d / "holdout.json").write_text(json.dumps({"truth_ring_ids": gt[:5]}))
    rc, out, err = cli("eval", "--rings", d / "rings.parquet", "--truth", GT, "--holdout", d / "holdout.json",
                       "--scope", "test_visible", "--window", "whole", "--out", d / "metrics_holdout.json")
    assert rc == 0, err
    h = json.loads((d / "metrics_holdout.json").read_text())
    assert h["holdout"]["n_truth_listed"] == 5 and h["n_truth"] <= 5 and h["window"] == "whole"
