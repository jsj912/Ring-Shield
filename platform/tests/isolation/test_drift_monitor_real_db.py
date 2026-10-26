"""PostgreSQL acceptance for drift event tenant binding and idempotence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from sqlalchemy import create_engine, text

from jobs.drift_monitor import persist_events

TENANT_A, TENANT_B = 210, 220


def _snapshot(engine, tenant_id: int) -> list[tuple]:
    with engine.connect() as connection:
        return list(connection.execute(text("""
            SELECT monitor, detected_at, window_start, window_end, statistic,
                   threshold, acted_on
            FROM drift_events WHERE tenant_id = :tenant_id ORDER BY event_id
        """), {"tenant_id": tenant_id}).all())


def test_drift_event_writes_are_idempotent_and_tenant_scoped(register_db_test_ids):
    admin = create_engine(os.environ["RINGSHIELD_TEST_ADMIN_URL"])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    end_a = now + timedelta(days=3)
    end_b = now + timedelta(days=4)
    run_token = uuid4().hex
    monitor_a = "adwin_score_mean"
    monitor_b = "adwin_score_p99"
    register_db_test_ids(run_token)
    event_a = {"tenant_id": TENANT_A, "monitor": monitor_a,
               "detected_at": end_a, "window_start": now, "window_end": end_a,
               "statistic": 0.83, "threshold": 0.002, "acted_on": False}
    event_b = {"tenant_id": TENANT_B, "monitor": monitor_b,
               "detected_at": end_b, "window_start": now, "window_end": end_b,
               "statistic": 0.91, "threshold": 0.002, "acted_on": False}
    before_b = _snapshot(admin, TENANT_B)
    try:
        assert persist_events(TENANT_A, [event_a]) == 1
        assert persist_events(TENANT_A, [event_a]) == 0
        assert persist_events(TENANT_B, [event_b]) == 1
        assert persist_events(TENANT_B, [event_b]) == 0
        after_b = _snapshot(admin, TENANT_B)
        assert after_b == before_b + [(
            monitor_b, end_b, now, end_b, 0.91, 0.002, False,
        )]
        with admin.connect() as connection:
            assert connection.execute(text("""
                SELECT count(*) FROM drift_events
                WHERE tenant_id = :tenant_id AND monitor = :monitor AND window_end = :window_end
            """), {"tenant_id": TENANT_A, "monitor": monitor_a,
                  "window_end": end_a}).scalar_one() == 1
    finally:
        with admin.begin() as connection:
            connection.execute(text("""
                DELETE FROM audit_log
                WHERE tenant_id IN (:tenant_a, :tenant_b) AND object_id = :run_id
            """), {"tenant_a": TENANT_A, "tenant_b": TENANT_B,
                  "run_id": run_token})
            connection.execute(text("""
                DELETE FROM drift_events
                WHERE tenant_id IN (:tenant_a, :tenant_b)
                  AND window_end IN (:end_a, :end_b)
                  AND monitor IN (:monitor_a, :monitor_b)
            """), {"tenant_a": TENANT_A, "tenant_b": TENANT_B,
                  "end_a": end_a, "end_b": end_b,
                  "monitor_a": monitor_a, "monitor_b": monitor_b})
        admin.dispose()
