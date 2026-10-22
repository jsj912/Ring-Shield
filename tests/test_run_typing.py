"""`ringshield run` types rings with the model dir's head, exactly as the contract files are typed.

The acceptance test: `run` on pooled seed 1 must reproduce the contract rings file's
`topology_type` (and `topology_probs`) ring for ring. Skips only when the gitignored inputs are
not on disk, and says which.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from contract.schema import RINGS_COLUMNS          # noqa: E402

PATHS = load_paths()
ROOT = PATHS["experiments_dir"].parent
MD = ROOT / "models" / "artifacts" / "full_gine_causal_seed1"
SCORES = ROOT / "contract" / "out" / "scored_edges_gine_causal_1.parquet"
GFP = PATHS["processed_dir"] / "amlworld_gfp_features_test.parquet"
EMB = PATHS["experiments_dir"] / "R1_gine_causal" / "embeddings_test_seed1.parquet"


def _contract_rings() -> Path | None:
    for c in (ROOT / "contract" / "out" / "rings_full_gine_causal_1.parquet",
              ROOT.parent / "RS-ccy-valrings" / "contract" / "out" / "rings_full_gine_causal_1.parquet"):
        if c.exists() and len(pq.read_schema(c).names) == len(RINGS_COLUMNS):
            return c
    return None


CONTRACT = _contract_rings()
need = [p for p in (MD / "typing" / "head.json", SCORES, GFP, EMB) if not p.exists()]
pytestmark = pytest.mark.skipif(bool(need) or CONTRACT is None,
                                reason=f"inputs not on disk: {[str(p) for p in need] or 'v2 contract rings seed 1'}")


@pytest.fixture(scope="module")
def run_rings(tmp_path_factory):
    out = tmp_path_factory.mktemp("typed") / "rings.parquet"
    r = subprocess.run([sys.executable, "-m", "ringshield", "run", "--scores", str(SCORES), "--model-dir", str(MD),
                        "--gfp", str(GFP), "--embeddings", str(EMB), "--out", str(out)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _by_members(df):
    return {tuple(sorted(int(x) for x in r.member_edges)): r for r in df.itertuples()}


def test_run_reproduces_contract_topology_ring_for_ring(run_rings):
    a, b = _by_members(pd.read_parquet(run_rings)), _by_members(pd.read_parquet(CONTRACT))
    assert set(a) == set(b), "membership differs from the contract file"
    mismatched = [(b[k].ring_id, b[k].topology_type, a[k].topology_type) for k in b if a[k].topology_type != b[k].topology_type]
    assert not mismatched, mismatched[:5]
    worst = max(float(np.abs(np.asarray(a[k].topology_probs) - np.asarray(b[k].topology_probs)).max()) for k in b)
    assert worst == 0.0


def test_run_output_is_schema_v2_and_typed(run_rings):
    names = pq.read_schema(run_rings).names
    assert set(names) == set(RINGS_COLUMNS) and len(names) == 30
    df = pd.read_parquet(run_rings, columns=["topology_type", "topology_probs"])
    assert (df["topology_type"] != "UNKNOWN").all()
    assert np.allclose(df["topology_probs"].map(lambda p: float(np.sum(p))), 1.0)
    log = json.loads(Path(str(run_rings) + ".log.json").read_text(encoding="utf-8"))
    assert log["expansion"]["typing_head"].replace("\\", "/").endswith("full_gine_causal_seed1/typing")


def test_the_head_is_recorded_in_version_json():
    v = json.loads((MD / "version.json").read_text(encoding="utf-8"))["typing_head"]
    assert v["source"] == "experiments/R5_typing/head_w2" and v["retrained"] is False
    import hashlib
    for f, rec in v["files"].items():
        assert hashlib.sha256((MD / "typing" / f).read_bytes()).hexdigest() == rec["sha256"]
