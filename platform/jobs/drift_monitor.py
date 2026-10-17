"""Tenant-scoped score drift monitoring; detections never trigger retraining."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Iterable

import numpy as np
from river.drift import ADWIN
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from db.models import DriftEvent, EdgeScore, Transaction
from db.session import db_session, loader_db_session
from settings import load_platform_config

MONITORS = {"mean": "adwin_score_mean", "p99": "adwin_score_p99"}
SIMULATED_TIME_ORIGIN = 10
SECONDS_PER_DAY = 86_400


def daily_statistics(rows: Iterable[tuple[int, float | None]]) -> list[tuple[int, float, float]]:
    """Return (day, mean, p99) for observed days only, in ascending day order."""
    by_day: dict[int, list[float]] = defaultdict(list)
    for timestamp, score in rows:
        if score is None or not math.isfinite(float(score)):
            continue
        day = (int(timestamp) - SIMULATED_TIME_ORIGIN) // SECONDS_PER_DAY
        by_day[day].append(float(score))
    return [
        (day, float(np.mean(values)), float(np.percentile(values, 99)))
        for day, values in sorted(by_day.items())
    ]


def detect_events(daily: list[tuple[int, float, float]], *, delta: float,
                  tenant_id: int) -> list[dict]:
    """Run independent ADWIN streams and describe each detected window."""
    events: list[dict] = []
    for statistic_index, monitor in ((1, MONITORS["mean"]), (2, MONITORS["p99"])):
        detector = ADWIN(delta=float(delta))
        observed_days: list[int] = []
        for day, mean, p99 in daily:
            observed_days.append(day)
            statistic = mean if statistic_index == 1 else p99
            detector.update(statistic)
            if not detector.drift_detected:
                continue
            window_size = max(1, int(detector.width))
            start_day = observed_days[max(0, len(observed_days) - window_size)]
            window_start = datetime.fromtimestamp(
                start_day * SECONDS_PER_DAY + SIMULATED_TIME_ORIGIN, tz=timezone.utc
            )
            window_end = datetime.fromtimestamp(
                (day + 1) * SECONDS_PER_DAY + SIMULATED_TIME_ORIGIN, tz=timezone.utc
            )
            events.append({
                "tenant_id": int(tenant_id), "monitor": monitor,
                "detected_at": window_end, "window_start": window_start,
                "window_end": window_end, "statistic": statistic,
                "threshold": float(delta), "acted_on": False,
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
    with loader_db_session(tenant_id=tenant_id) as session:
        for event in events:
            event_id = session.execute(
                insert(DriftEvent).values(**event)
                .on_conflict_do_nothing(constraint="uq_drift_events_tenant_monitor_window_end")
                .returning(DriftEvent.event_id)
            ).scalar_one_or_none()
            inserted += int(event_id is not None)
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
