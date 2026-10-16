"""Convert loader-basis seconds to UTC instants for the platform API."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException


def time_origin() -> datetime:
    value = os.environ.get("RINGSHIELD_TIME_ORIGIN_UTC")
    if not value:
        raise HTTPException(status_code=503, detail="Dataset time origin is not configured")
    try:
        origin = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Dataset time origin is invalid") from exc
    if origin.tzinfo is None:
        raise HTTPException(status_code=503, detail="Dataset time origin must include a UTC offset")
    return origin.astimezone(timezone.utc)


def to_utc(loader_seconds: int) -> datetime:
    return time_origin() + timedelta(seconds=int(loader_seconds))


def from_utc(value: datetime) -> int:
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="Date filters must include a timezone")
    return int((value.astimezone(timezone.utc) - time_origin()).total_seconds())
