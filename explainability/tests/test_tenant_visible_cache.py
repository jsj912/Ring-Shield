"""The bank's visible-scores file is reused only when it was cut from the current shipped scored edges.

Bank 1 once failed with "a seed_edge is not is_seed in scored_edges": an R11 hand-off file of the bank's own-model
scores sat at the cached path and was reused, while its rings came from the shipped scores."""
from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from explainability.tenant import visible_scored_edges_current, write_visible_scored_edges


def _setup(tmp_path, is_seed=(True, False, True)):
    shipped = tmp_path / "scored_edges_{seed}.parquet"
    table = pa.table({"edge_id": [1, 2, 3, 4], "from_bank": [7, 7, 9, 9], "to_bank": [9, 8, 7, 8],
                      "is_seed": [*is_seed, False]})
    pq.write_table(table.replace_schema_metadata({b"contract": b"shipped"}), str(shipped).format(seed=1))
    pd.DataFrame({"edge_id": [1, 2, 3]}).to_parquet(tmp_path / "tenant_7_edge_ids.parquet")
    return {"inputs": {"scored_edges": str(shipped)},
            "tenants": {"seed": 1, "rings": str(tmp_path / "tenant_{bank}_rings.parquet"),
                        "edge_ids": str(tmp_path / "tenant_{bank}_edge_ids.parquet"),
                        "scored_edges": str(tmp_path / "visible_{bank}_{seed}.parquet"),
                        "out": str(tmp_path / "explanations_{bank}_{seed}.parquet")}}


def test_written_file_is_current_and_keeps_the_shipped_schema_metadata(tmp_path):
    cfg = _setup(tmp_path)
    assert not visible_scored_edges_current(cfg, 7)                 # nothing cached yet
    out = write_visible_scored_edges(cfg, 7)
    assert visible_scored_edges_current(cfg, 7)
    assert sorted(pq.read_table(out).column("edge_id").to_pylist()) == [1, 2, 3]
    assert pq.ParquetFile(out).schema_arrow.metadata[b"contract"] == b"shipped"


def test_an_unstamped_file_at_the_cached_path_is_not_reused(tmp_path):
    cfg = _setup(tmp_path)
    stale = pa.table({"edge_id": [1, 2, 3], "is_seed": [False, False, False]})   # e.g. own-model scores
    pq.write_table(stale, tmp_path / "visible_7_1.parquet")
    assert not visible_scored_edges_current(cfg, 7)


def test_new_shipped_scores_make_the_cached_file_stale(tmp_path):
    cfg = _setup(tmp_path)
    write_visible_scored_edges(cfg, 7)
    _setup(tmp_path, is_seed=(False, True, True))                   # the detector was re-run
    assert not visible_scored_edges_current(cfg, 7)


def test_a_file_cut_for_another_bank_is_not_current(tmp_path):
    cfg = _setup(tmp_path)
    write_visible_scored_edges(cfg, 7)
    (tmp_path / "visible_7_1.parquet").rename(tmp_path / "visible_9_1.parquet")
    assert not visible_scored_edges_current(cfg, 9)
