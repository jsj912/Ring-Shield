"""`ringshield train --component {expansion,affinity}`: real retraining, the holdout guard, the
labels manifest -- and the property everything else rests on: an EMPTY label file reproduces the
shipped model exactly, down to its holdout ring-F1.

These run the real pipeline on the shipped seed-1 model and so take a few minutes; they skip only
when the gitignored artefacts are not on disk, and say which.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths                                     # noqa: E402
from ringshield.retrain import (HOLDOUT_MANIFEST, RetrainError, holdout_ring_f1,       # noqa: E402
                                load_holdout_manifest, manifest_content_sha256)

PATHS = load_paths()
ROOT = PATHS["experiments_dir"].parent            # the research checkout holding the gitignored artefacts
BASE = ROOT / "models" / "artifacts" / "full_gine_causal_seed1"
OUT = ROOT / "contract" / "out"
PROC = PATHS["processed_dir"]
EXP = PATHS["experiments_dir"]
SCHEMA = pa.schema([("ring_id", pa.string()), ("member_accounts", pa.list_(pa.int64())),
                    ("member_edges", pa.list_(pa.int64())), ("verdict", pa.string())])


def _find_rings() -> Path | None:
    for c in (OUT / "rings_full_gine_causal_1.parquet",
              ROOT.parent / "RS-ccy-valrings" / "contract" / "out" / "rings_full_gine_causal_1.parquet"):
        if c.exists():
            return c
    return None


RINGS = _find_rings()
TEST_IN = {"scores": OUT / "scored_edges_gine_causal_1.parquet", "gfp": PROC / "amlworld_gfp_features_test.parquet",
           "embeddings": EXP / "R1_gine_causal" / "embeddings_test_seed1.parquet"}
VAL_IN = {"val_scores": OUT / "scored_edges_gine_causal_1_val.parquet", "gfp": PROC / "amlworld_gfp_features_val.parquet",
          "embeddings": EXP / "R1_gine_causal" / "embeddings_val_seed1.parquet",
          "truth": PROC / "amlworld_ring_ground_truth.parquet"}
NEEDED = [BASE / "model.json", *TEST_IN.values(), *VAL_IN.values()]
missing = [str(p) for p in NEEDED if not p.exists()] + ([] if RINGS else ["rings_full_gine_causal_1.parquet"])
pytestmark = pytest.mark.skipif(bool(missing), reason=f"retraining artefacts not on disk: {missing[:3]}")


def cli(*args):
    env = {**os.environ}
    r = subprocess.run([sys.executable, "-m", "ringshield", "train", *map(str, args)], cwd=REPO_ROOT,
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def labels_file(path: Path, rows: list[dict]) -> Path:
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), path)
    return path


def ring_rows(n: int = 3) -> list[dict]:
    r = pd.read_parquet(RINGS)
    out = []
    for i, verdict in zip(range(n), ("confirm", "reject", "partial")):
        me = [int(x) for x in r.member_edges[i]]
        acc = [int(x) for x in r.members[i]]
        if verdict == "partial":
            me, acc = me[: max(2, len(me) // 2)], acc[:3]
        out.append({"ring_id": r.ring_id[i], "member_accounts": acc, "member_edges": me, "verdict": verdict})
    return out


def common():
    return ["--scores", TEST_IN["scores"], "--rings", RINGS, "--gfp", TEST_IN["gfp"], "--embeddings", TEST_IN["embeddings"]]


# --------------------------------------------------------------------------- the manifest
def test_the_committed_holdout_manifest_passes_its_own_hash():
    m = load_holdout_manifest(HOLDOUT_MANIFEST)
    assert m["content_sha256"] == manifest_content_sha256(m)
    assert m["window"] == "val" and m["days"] == [6, 7] and m["scope"] == "test_visible"
    assert len(m["truth_ring_ids"]) == 114, "the holdout is fixed once; a different count means it moved"
    assert "pred_ring_ids" not in m, "eval would filter a retrained model's rings by the shipped model's ids"


def test_an_edited_manifest_is_refused(tmp_path):
    m = json.loads(HOLDOUT_MANIFEST.read_text(encoding="utf-8"))
    m["truth_ring_ids"] = m["truth_ring_ids"][:-1]
    (tmp_path / "m.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(RetrainError, match="content hash mismatch"):
        load_holdout_manifest(tmp_path / "m.json")


# --------------------------------------------------------------------------- determinism
@pytest.fixture(scope="module")
def empty_retrain(tmp_path_factory):
    d = tmp_path_factory.mktemp("empty")
    lab = labels_file(d / "empty.parquet", [])
    rc, out, err = cli("--component", "expansion", "--labels", lab, "--base-model-dir", BASE, "--out-model-dir", d / "v2")
    assert rc == 0, err
    rc, out, err = cli("--component", "affinity", "--labels", lab, "--base-model-dir", d / "v2", "--out-model-dir", d / "v3")
    assert rc == 0, err
    return d


def test_empty_labels_reproduce_the_shipped_boosters(empty_retrain):
    for f in ("policy/policy.txt", "affinity/affinity.txt"):
        a = (BASE / f).read_text(encoding="utf-8").split("feature_importances")[0]
        b = (empty_retrain / "v3" / f).read_text(encoding="utf-8").split("feature_importances")[0]
        assert a == b, f"{f}: an empty retrain did not reproduce the shipped trees"


def test_empty_labels_reproduce_the_shipped_holdout_ring_f1_exactly(empty_retrain):
    shipped = holdout_ring_f1(BASE, **VAL_IN)
    retrained = holdout_ring_f1(empty_retrain / "v3", **VAL_IN)
    for k in ("ring_f1", "ring_precision", "ring_recall", "n_predicted", "n_matched"):
        assert shipped[k] == retrained[k], f"{k}: shipped {shipped[k]} vs retrained {retrained[k]}"


def test_an_empty_retrain_records_itself_honestly(empty_retrain):
    v = json.loads((empty_retrain / "v3" / "version.json").read_text(encoding="utf-8"))
    assert v["retrained"] is True and v["component"] == "affinity" and v["version"] == 3
    assert v["appended"]["n_rows_new"] == 0
    assert v["cv"]["old"]["cv_auc_pr_mean"] == pytest.approx(v["cv"]["new"]["cv_auc_pr_mean"], abs=0)
    assert v["holdout_check"]["passed"] and v["holdout_check"]["verified"]


# --------------------------------------------------------------------------- real labels
@pytest.fixture(scope="module")
def labelled(tmp_path_factory):
    d = tmp_path_factory.mktemp("lab")
    rows = ring_rows()
    lab = labels_file(d / "l.parquet", rows)
    rc, out, err = cli("--component", "affinity", "--labels", lab, "--base-model-dir", BASE,
                       "--out-model-dir", d / "aff", *common())
    assert rc == 0, err
    return d, rows


def test_verdicts_become_correctly_labelled_rows(labelled):
    d, rows = labelled
    v = json.loads((d / "aff" / "version.json").read_text(encoding="utf-8"))
    per = {x["ring_id"]: x for x in v["training_labels"]["this_round"]}
    assert per[rows[1]["ring_id"]]["n_positive"] == 0, "every pair of a reject is a negative"
    assert per[rows[0]["ring_id"]]["n_positive"] > 0
    kept = pd.read_parquet(d / "aff" / "retrain_rows_affinity.parquet")
    assert len(kept) == v["appended"]["n_rows_new"] and kept["component"].min() >= 1_000_000_000


def test_version_json_lists_every_training_ring(labelled):
    d, rows = labelled
    v = json.loads((d / "aff" / "version.json").read_text(encoding="utf-8"))
    tl = {x["ring_id"]: x for x in v["training_labels"]["rings"]}
    assert set(tl) == {r["ring_id"] for r in rows}
    for r in rows:
        assert tl[r["ring_id"]]["verdict"] == r["verdict"]
        assert tl[r["ring_id"]]["n_member_edges"] == len(r["member_edges"])


def test_test_window_labels_pass_even_though_their_names_exist_in_val(labelled):
    """Predicted ring ids carry no split: full-gine_causal-1-0 names a val ring AND a test ring.
    Guarding by predicted id would refuse every operating-period label; the guard must not."""
    d, _ = labelled
    v = json.loads((d / "aff" / "version.json").read_text(encoding="utf-8"))
    assert v["holdout_check"]["passed"] and v["holdout_check"]["n_ring_id_in_holdout"] == 0


def test_labels_accumulate_and_a_later_verdict_replaces_an_earlier_one(labelled, tmp_path):
    d, rows = labelled
    flipped = [{**rows[0], "verdict": "reject"}]
    lab = labels_file(tmp_path / "flip.parquet", flipped)
    rc, out, err = cli("--component", "affinity", "--labels", lab, "--base-model-dir", d / "aff",
                       "--out-model-dir", tmp_path / "aff2", *common())
    assert rc == 0, err
    v = json.loads((tmp_path / "aff2" / "version.json").read_text(encoding="utf-8"))
    tl = {x["ring_id"]: x["verdict"] for x in v["training_labels"]["rings"]}
    assert tl == {rows[0]["ring_id"]: "reject", rows[1]["ring_id"]: "reject", rows[2]["ring_id"]: "partial"}
    assert v["appended"]["replaced_ring_ids"] == [rows[0]["ring_id"]]


# --------------------------------------------------------------------------- the guard
def _val_label(tmp_path) -> Path:
    se = pd.read_parquet(VAL_IN["val_scores"], columns=["edge_id", "timestamp"]).head(3)
    return labels_file(tmp_path / "val.parquet", [{"ring_id": "anything", "member_accounts": [1, 2, 3],
                                                    "member_edges": [int(e) for e in se["edge_id"]], "verdict": "confirm"}])


def test_a_label_with_edges_in_the_holdout_days_is_refused(tmp_path):
    lab = _val_label(tmp_path)
    rc, out, err = cli("--component", "affinity", "--labels", lab, "--base-model-dir", BASE,
                       "--out-model-dir", tmp_path / "x", "--scores", VAL_IN["val_scores"], "--rings", RINGS)
    assert rc == 2 and "overlap the holdout" in err and not (tmp_path / "x").exists()


def test_a_label_on_a_holdout_truth_ring_id_is_refused(tmp_path):
    rid = str(load_holdout_manifest()["truth_ring_ids"][0])
    r = ring_rows(1)[0]
    lab = labels_file(tmp_path / "t.parquet", [{**r, "ring_id": rid}])
    rc, out, err = cli("--component", "affinity", "--labels", lab, "--base-model-dir", BASE,
                       "--out-model-dir", tmp_path / "x", *common())
    assert rc == 2 and "overlap the holdout" in err


def test_the_override_is_allowed_and_recorded(tmp_path):
    rid = str(load_holdout_manifest()["truth_ring_ids"][0])
    r = ring_rows(1)[0]
    lab = labels_file(tmp_path / "t.parquet", [{**r, "ring_id": rid}])
    # the label's ring_id must exist in --rings for features; alias the rings file under that id
    rings = pd.read_parquet(RINGS)
    rings.loc[0, "ring_id"] = rid
    rings.to_parquet(tmp_path / "rings.parquet", index=False)
    rc, out, err = cli("--component", "affinity", "--labels", lab, "--base-model-dir", BASE,
                       "--out-model-dir", tmp_path / "x", "--scores", TEST_IN["scores"], "--rings", tmp_path / "rings.parquet",
                       "--gfp", TEST_IN["gfp"], "--embeddings", TEST_IN["embeddings"], "--allow-holdout-overlap")
    assert rc == 0, err
    hc = json.loads((tmp_path / "x" / "version.json").read_text(encoding="utf-8"))["holdout_check"]
    assert hc["allow_holdout_overlap"] is True and hc["passed"] is False and hc["offending_ring_ids"] == [rid]


def test_a_component_the_model_lacks_is_refused(tmp_path):
    cc = ROOT / "models" / "artifacts" / "cc_gine_causal_seed1"
    if not cc.exists():
        pytest.skip(f"{cc} not on disk")
    lab = labels_file(tmp_path / "e.parquet", [])
    rc, out, err = cli("--component", "expansion", "--labels", lab, "--base-model-dir", cc, "--out-model-dir", tmp_path / "x")
    assert rc == 2 and "no policy/" in err
