"""Tenant-scoped score drift monitoring; detections never trigger retraining."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Iterable
from uuid import uuid4

import numpy as np
from river.drift import ADWIN
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from audit import add_audit_event
from db.models import DriftEvent, EdgeScore, Transaction
from db.session import db_session, loader_db_session
from settings import load_platform_config

MONITORS = {"mean": "adwin_score_mean", "p99": "adwin_score_p99"}
SIMULATED_TIME_ORIGIN = 10
SECONDS_PER_DAY = 86_400


def daily_statistics(rows: Iterable[tuple[int, float | None]],
                     step_seconds: int = SECONDS_PER_DAY) -> list[tuple[int, float, float]]:
    """Return (step, mean, p99) for observed steps only, in ascending order; a step is a day
    unless `step_seconds` says otherwise (R12 replays hours)."""
    by_day: dict[int, list[float]] = defaultdict(list)
    for timestamp, score in rows:
        if score is None or not math.isfinite(float(score)):
            continue
        day = (int(timestamp) - SIMULATED_TIME_ORIGIN) // int(step_seconds)
        by_day[day].append(float(score))
    return [
        (day, float(np.mean(values)), float(np.percentile(values, 99)))
        for day, values in sorted(by_day.items())
    ]


def detect_events(daily: list[tuple[int, float, float]], *, delta: float,
                  tenant_id: int) -> list[dict]:
    """Run independent ADWIN streams and describe each detected window."""
    stream = DriftStream(delta=delta, tenant_id=tenant_id)
    return [event for point in daily for event in stream.update(*point)]


class DriftStream:
    """Incremental two-series ADWIN state for chronological replay experiments."""

    def __init__(self, *, delta: float, tenant_id: int, step_seconds: int = SECONDS_PER_DAY):
        """One update per step: a day in live operation, an hour in the R12 replay."""
        self.delta = float(delta)
        self.tenant_id = int(tenant_id)
        self.step_seconds = int(step_seconds)
        self.detectors = {
            MONITORS["mean"]: ADWIN(delta=self.delta),
            MONITORS["p99"]: ADWIN(delta=self.delta),
        }
        self.days: list[int] = []

    def update(self, day: int, mean: float, p99: float) -> list[dict]:
        self.days.append(int(day))
        events = []
        for monitor, statistic in ((MONITORS["mean"], float(mean)),
                                   (MONITORS["p99"], float(p99))):
            detector = self.detectors[monitor]
            detector.update(statistic)
            if not detector.drift_detected:
                continue
            window_size = max(1, int(detector.width))
            start_day = self.days[max(0, len(self.days) - window_size)]
            window_start = datetime.fromtimestamp(
                start_day * self.step_seconds + SIMULATED_TIME_ORIGIN, tz=timezone.utc
            )
            window_end = datetime.fromtimestamp(
                (int(day) + 1) * self.step_seconds + SIMULATED_TIME_ORIGIN, tz=timezone.utc
            )
            events.append({
                "tenant_id": self.tenant_id, "monitor": monitor,
                "detected_at": window_end, "window_start": window_start,
                "window_end": window_end, "statistic": statistic,
                "threshold": self.delta, "acted_on": False,
            })
        return events


def read_daily_scores(tenant_id: int, *, model_id: str, seed: int) -> list[tuple[int, float, float]]:
    """Read the active model's scores under RLS and explicit tenant predicates."""
    with db_session(tenant_id=tenant_id, role="supervisor") as session:
        rows = session.execute(
            select(Transaction.timestamp, EdgeScore.score_calibrated)
            .join(EdgeScore, (EdgeScore.tenant_id == Transaction.tenant_id)
                  & (EdgeScore.edge_id == Transaction.edge_id))
            .where(
                Transaction.tenant_id == tenant_id,
                EdgeScore.tenant_id == tenant_id,
                EdgeScore.model_id == model_id,
                EdgeScore.seed == seed,
                EdgeScore.score_calibrated.is_not(None),
            )
            .order_by(Transaction.timestamp, Transaction.edge_id)
        ).all()
    return daily_statistics((int(timestamp), score) for timestamp, score in rows)


def persist_events(tenant_id: int, events: list[dict]) -> int:
    """Insert new events idempotently; the DB unique key handles concurrent runs."""
    if not events:
        return 0
    inserted = 0
    run_id = uuid4().hex
    with loader_db_session(tenant_id=tenant_id) as session:
        for event in events:
            event_id = session.execute(
                insert(DriftEvent).values(**event)
                .on_conflict_do_nothing(constraint="uq_drift_events_tenant_monitor_window_end")
                .returning(DriftEvent.event_id)
            ).scalar_one_or_none()
            inserted += int(event_id is not None)
        add_audit_event(session, tenant_id=tenant_id, actor="drift_monitor",
                        action="drift.events_persisted", entity_type="drift_monitor_run",
                        entity_id=run_id, details={"run_id": run_id, "inserted": inserted})
    return inserted


def monitor_tenant(tenant_id: int, *, model_id: str | None = None,
                   seed: int | None = None, delta: float | None = None) -> dict[str, int]:
    config = load_platform_config()
    l6_drift = config["l6"]["drift"]
    active_model = model_id or str(config["active_model_id"])
    active_seed = int(config["active_seed"] if seed is None else seed)
    delta = float(l6_drift["delta"] if delta is None else delta)
    daily = read_daily_scores(tenant_id, model_id=active_model, seed=active_seed)
    events = detect_events(daily, delta=delta, tenant_id=tenant_id)
    return {
        "days": len(daily), "detected": len(events),
        "inserted": persist_events(tenant_id, events),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tenant_id", type=int)
    args = parser.parse_args()
    print(monitor_tenant(args.tenant_id))
