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
