"""Print the row count from a parquet file's metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pyarrow.parquet as pq


def count_rows(path: Path) -> int:
    """Return a parquet file's metadata row count, with a clear input error."""
    if not path.is_file():
        raise ValueError(f"parquet file does not exist: {path}")
    try:
        metadata = pq.ParquetFile(path).metadata
    except Exception as exc:
        raise ValueError(f"could not read parquet metadata: {exc}") from exc
    if metadata is None:
        raise ValueError("parquet metadata is missing")
    return metadata.num_rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        rows = count_rows(args.path)
    except (OSError, ValueError) as exc:
        print(f"Unable to count parquet rows for '{args.path}': {exc}", file=sys.stderr)
        return 1
    print(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
