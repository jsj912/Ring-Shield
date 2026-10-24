"""Read-only preflight for one or more tenant L4 explanation handoffs.

This command calls the same ``read_handoff`` validation used by the loader but
never opens a database connection or writes data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "platform"))

from jobs.load_explanations import ExplanationLoadError, read_handoff  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explanations", action="append", type=Path, required=True,
                        help="explanation parquet; repeat alongside each log option")
    parser.add_argument("--run-log", action="append", type=Path, required=True,
                        help="sibling explanation .log.json; repeat once per parquet")
    parser.add_argument("--rings-log", action="append", type=Path, required=True,
                        help="source tenant rings .log.json; repeat once per parquet")
    args = parser.parse_args(argv)
    counts = (len(args.explanations), len(args.run_log), len(args.rings_log))
    if len(set(counts)) != 1:
        parser.error("provide the same number of --explanations, --run-log, and --rings-log arguments")

    refused = False
    for explanations, run_log, rings_log in zip(args.explanations, args.run_log, args.rings_log):
        try:
            rows, _ = read_handoff(explanations, run_log, rings_log)
        except (ExplanationLoadError, OSError, ValueError) as exc:
            print(f"REFUSED {explanations}: {exc}")
            refused = True
        else:
            print(f"OK {len(rows)} rows: {explanations}")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
