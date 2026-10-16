"""Give generated demo parquets the same test-split provenance required in production."""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main(fixture_dir: Path) -> None:
    score_log = {
        "split": "test", "model_id": "demo-model", "seed": 7,
        "seed_rule": {"q": 0.42, "selection_column": "score_raw"},
    }
    ring_log = {"split": "test", "command": "test-fixture"}
    (fixture_dir / "scored_edges.parquet.log.json").write_text(
        json.dumps(score_log, indent=2), encoding="utf-8",
    )
    (fixture_dir / "rings.parquet.log.json").write_text(
        json.dumps(ring_log, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
