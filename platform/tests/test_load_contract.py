from __future__ import annotations

import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.load_contract import ContractLoadError, _check_file
from jobs import load_contract


def test_contract_loader_rejects_non_test_sibling_log(tmp_path):
    parquet = tmp_path / "scored_edges.parquet"
    pq.write_table(pa.table({"edge_id": [1]}), parquet)
    Path(str(parquet) + ".log.json").write_text(json.dumps({"split": "val"}), encoding="utf-8")

    with pytest.raises(ContractLoadError, match="split=test"):
        _check_file(parquet, {"edge_id"})


@pytest.mark.parametrize("filename", ["labels_test.parquet", "scores_ground_truth.parquet"])
def test_contract_loader_refuses_label_and_ground_truth_paths(tmp_path, filename):
    path = tmp_path / filename

    with pytest.raises(ContractLoadError, match="label/ground-truth paths"):
        _check_file(path, {"edge_id"})


def test_edge_loader_sets_context_and_writes_only_requested_tenant(monkeypatch):
    source = {
        "edge_id": 7, "tenant_id": 220, "from_id": 1, "to_id": 2,
        "from_bank": 210, "to_bank": 220, "timestamp": 100,
        "score_raw": 0.7, "score_calibrated": 0.8, "is_seed": False,
        "model_id": "fixture", "seed": 1,
    }
    batch = pa.RecordBatch.from_pylist([source])

    class Parquet:
        schema_arrow = pa.schema([pa.field(name, pa.null()) for name in source])

        @staticmethod
        def iter_batches(batch_size):
            yield batch

    class Session:
        def __init__(self):
            self.statements = []

        def scalars(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "tenants.tenant_id = 210" in compiled
            return [210]

        def execute(self, statement):
            self.statements.append(statement)

    session = Session()
    requested = []

    class Manager:
        def __enter__(self): return session
        def __exit__(self, *_args): return False

    monkeypatch.setattr(load_contract, "_check_file", lambda *_args: (Parquet(), {
        "split": "test", "model_id": "fixture", "seed": 1,
    }))
    monkeypatch.setattr(load_contract, "loader_db_session", lambda *, tenant_id=None: (
        requested.append(tenant_id) or Manager()
    ))
    result = load_contract.load_edges(Path("scored_edges.parquet"), scope="tenant", tenant_id=210)
    assert requested == [210]
    assert result["visible_edge_rows"] == 1
    # The transaction and score inserts are built from the filtered visible set.
    transaction_rows = session.statements[0].compile().params
    assert transaction_rows["tenant_id_m0"] == 210
