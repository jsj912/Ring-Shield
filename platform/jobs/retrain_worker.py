"""Child-process entry point for tenant retraining."""

from __future__ import annotations

import sys

from jobs.retrain import run_retrain_job


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        raise SystemExit("usage: python -m jobs.retrain_worker TENANT_ID RUN_ID")
    try:
        tenant_id = int(args[0])
    except ValueError as exc:
        raise SystemExit("TENANT_ID must be an integer") from exc
    run_retrain_job(tenant_id, args[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
