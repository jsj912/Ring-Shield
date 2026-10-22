"""Time helpers for bounded explanation-regeneration polling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def new_poll_deadline() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=120)


def deadline_expired(deadline: datetime | None) -> bool:
    return deadline is None or datetime.now(timezone.utc) >= deadline
