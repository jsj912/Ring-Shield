"""A bank's visible-scores file is cut from the scores its rings were built from, and reused only while it still is.

Bank 1's rings were built from its own-model scores, whose is_seed flags differ from the shipped scores'. Cut from the
shipped scores, every ring failed "a seed_edge is not is_seed in scored_edges"."""
from __future__ import annotations

import json

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from explainability.tenant import rings_scores_source, visible_scored_edges_current, write_visible_scored_edges


def _scores(path, is_seed):
    table = pa.table({"edge_id": [1, 2, 3, 4], "from_bank": [7, 7, 9, 9], "to_bank": [9, 8, 7, 8],
                      "is_seed": [*is_seed, False]})
    pq.write_table(table.replace_schema_metadata({b"contract": b"scored_edges"}), path)


def _setup(tmp_path, rings_scores=None):
    """Shipped scores at scored_edges_1.parquet; the bank 7 rings' log records rings_scores (no log if None)."""
    _scores(tmp_path / "scored_edges_1.parquet", (True, False, True))
    pd.DataFrame({"edge_id": [1, 2, 3]}).to_parquet(tmp_path / "tenant_7_edge_ids.parquet")
    if rings_scores is not None:
        (tmp_path / "tenant_7_rings.parquet.log.json").write_text(json.dumps({"scores": str(rings_scores)}))
    return {"inputs": {"scored_edges": str(tmp_path / "scored_edges_{seed}.parquet")},
            "tenants": {"seed": 1, "rings": str(tmp_path / "tenant_{bank}_rings.parquet"),
                        "edge_ids": str(tmp_path / "tenant_{bank}_edge_ids.parquet"),
                        "scored_edges": str(tmp_path / "visible_{bank}_{seed}.parquet"),
                        "out": str(tmp_path / "explanations_{bank}_{seed}.parquet")}}


def _is_seed(path):
    t = pq.read_table(path).to_pandas().sort_values("edge_id")
    return t["is_seed"].tolist()


def test_without_a_rings_log_the_shipped_scores_are_cut(tmp_path):
    cfg = _setup(tmp_path)
    assert not visible_scored_edges_current(cfg, 7)                 # nothing cached yet
    out = write_visible_scored_edges(cfg, 7)
    assert visible_scored_edges_current(cfg, 7)
    assert _is_seed(out) == [True, False, True]
    assert pq.ParquetFile(out).schema_arrow.metadata[b"contract"] == b"scored_edges"


def test_rings_built_from_own_model_scores_are_explained_with_those_scores(tmp_path):
    own = tmp_path / "own_7.parquet"
    _scores(own, (False, True, True))
    cfg = _setup(tmp_path, rings_scores=own)
    assert rings_scores_source(cfg, 7) == own
    assert _is_seed(write_visible_scored_edges(cfg, 7)) == [False, True, True]


def test_a_cut_of_other_scores_at_the_cached_path_is_rewritten(tmp_path):
    own = tmp_path / "own_7.parquet"
    _scores(own, (False, True, True))
    cfg = _setup(tmp_path)
    write_visible_scored_edges(cfg, 7)                              # cut from the shipped scores
    assert visible_scored_edges_current(cfg, 7)
    _setup(tmp_path, rings_scores=own)                              # rings rebuilt from own-model scores
    assert not visible_scored_edges_current(cfg, 7)


def test_an_unstamped_file_is_not_reused(tmp_path):
    cfg = _setup(tmp_path)
    pq.write_table(pa.table({"edge_id": [1, 2, 3], "is_seed": [False, False, False]}), tmp_path / "visible_7_1.parquet")
    assert not visible_scored_edges_current(cfg, 7)


def test_new_scores_at_the_same_path_make_the_cached_file_stale(tmp_path):
    cfg = _setup(tmp_path)
    write_visible_scored_edges(cfg, 7)
    _scores(tmp_path / "scored_edges_1.parquet", (False, True, True))   # the detector was re-run
    assert not visible_scored_edges_current(cfg, 7)


def test_a_file_cut_for_another_bank_is_not_current(tmp_path):
    cfg = _setup(tmp_path)
    write_visible_scored_edges(cfg, 7)
    (tmp_path / "visible_7_1.parquet").rename(tmp_path / "visible_9_1.parquet")
    assert not visible_scored_edges_current(cfg, 9)


def test_a_log_from_another_machine_naming_the_shipped_file_uses_the_shipped_scores(tmp_path):
    cfg = _setup(tmp_path, rings_scores=r"E:\elsewhere\contract\out\scored_edges_1.parquet")
    assert rings_scores_source(cfg, 7) == tmp_path / "scored_edges_1.parquet"


def test_a_log_naming_missing_other_scores_is_an_error(tmp_path):
    cfg = _setup(tmp_path, rings_scores=r"E:\elsewhere\own_7.parquet")
    with pytest.raises(FileNotFoundError):
        rings_scores_source(cfg, 7)
