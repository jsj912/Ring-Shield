"""Child-process entry point for tenant drift monitoring."""

from __future__ import annotations

import sys

from jobs.drift_monitor import monitor_tenant


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("usage: python -m jobs.drift_monitor_worker TENANT_ID")
    try:
        tenant_id = int(args[0])
    except ValueError as exc:
        raise SystemExit("TENANT_ID must be an integer") from exc
    print(monitor_tenant(tenant_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
