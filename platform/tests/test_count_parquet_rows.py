from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


PLATFORM_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PLATFORM_ROOT / "jobs" / "count_parquet_rows.py"


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_count_parquet_rows_prints_metadata_count(tmp_path: Path) -> None:
    parquet_path = tmp_path / "tiny.parquet"
    pq.write_table(pa.table({"value": [1, 2, 3]}), parquet_path)

    result = _run(parquet_path)

    assert result.returncode == 0
    assert result.stdout == "3\n"
    assert result.stderr == ""


def test_count_parquet_rows_missing_file_has_clear_failure(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing.parquet")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "does not exist" in result.stderr


def test_count_parquet_rows_non_parquet_has_clear_failure(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.parquet"
    invalid_path.write_text("not a parquet file", encoding="utf-8")

    result = _run(invalid_path)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Unable to count parquet rows" in result.stderr


def test_count_parquet_rows_success_cannot_return_empty_output(tmp_path: Path) -> None:
    parquet_path = tmp_path / "empty.parquet"
    pq.write_table(pa.table({"value": []}), parquet_path)

    result = _run(parquet_path)

    assert result.returncode == 0
    assert result.stdout == "0\n"
    assert result.stdout.strip() != ""
