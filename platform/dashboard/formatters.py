"""Display formatting for API values (FR-D101). Formatting only: no sums, ratios or re-ranking (FR-D102).

Amounts: thousands separators and two decimals, with the currency exactly as the API names it and
the partial flag shown, never converted. Percentages: one decimal. Weights: two decimals. Times:
the viewer's local zone, with the UTC instant kept for hover.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MISSING = "—"


def fmt_amount(value, currency: str | None = None, partial: bool | None = None) -> str:
    if value is None:
        return MISSING
    text = f"{float(value):,.2f}"
    if currency:
        text = f"{text} {currency}"
    if partial:
        text = f"{text} (partial)"
    return text


def fmt_percent(fraction) -> str:
    """A fraction in [0, 1] shown as a percentage with one decimal (formatting, not arithmetic)."""
    return MISSING if fraction is None else f"{float(fraction):.1%}"


def fmt_weight(value) -> str:
    return MISSING if value is None else f"{float(value):.2f}"


def fmt_recall(value) -> str:
    """A recall in [0, 1] with three decimals, as the R10 tables report it."""
    return MISSING if value is None else f"{float(value):.3f}"


def fmt_interval(value, low, high) -> str:
    """A value with its 95 % interval, e.g. "0.088 [0.031, 0.161]"."""
    return f"{fmt_recall(value)} [{fmt_recall(low)}, {fmt_recall(high)}]"


def fmt_as_received(value) -> str:
    """A number shown exactly as the API sent it (change 3: topology_prob)."""
    return MISSING if value is None else str(value)


def fmt_closure(value, closed_loop: bool | None = None) -> str:
    """Conservation closure: "closed loop" for a ring with no source or sink, never a percentage."""
    if closed_loop or value is None:
        return "closed loop" if closed_loop or value is None else MISSING
    return fmt_percent(value)


def _parse(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def fmt_time(value, tz_name: str | None = None) -> str:
    """The instant in the viewer's zone (falls back to UTC when the zone is unknown); a value
    that is not an ISO-8601 instant is shown as received rather than breaking the screen."""
    try:
        moment = _parse(value)
    except ValueError:
        return str(value)
    if moment is None:
        return MISSING
    try:
        zone = ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    local = moment.astimezone(zone)
    return local.strftime("%Y-%m-%d %H:%M ") + (local.tzname() or "UTC")


def fmt_time_utc(value) -> str:
    """The same instant in UTC, for hover text."""
    try:
        moment = _parse(value)
    except ValueError:
        return str(value)
    return MISSING if moment is None else moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_seconds(value) -> str:
    """A duration in seconds with separators; missing or NaN (no hold time) shows as a dash."""
    if value is None or value != value:
        return MISSING
    return f"{float(value):,.0f} s"


def fmt_bool(value) -> str:
    return MISSING if value is None else ("Yes" if value else "No")
