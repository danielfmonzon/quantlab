"""NYSE (XNYS) trading calendar wrapper.

A session is considered *completed* only after 21:00 UTC on the session date —
the regular NYSE close is 21:00 UTC (16:00 ET) during standard time; we treat
21:00 UTC as a uniform close-plus-buffer so a session isn't reported complete
while the market may still be settling.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

import exchange_calendars as xcals

# Uniform "session complete" cutoff: 21:00 UTC on the session date.
_SESSION_COMPLETE_HOUR_UTC = 21

# exchange_calendars defaults to only ~20 years of history; extend the lower
# bound so validation can cover every session back to each ETF's inception.
# (The upper bound keeps its default, which already runs past the current date.)
_CALENDAR_START = "1990-01-01"


@lru_cache(maxsize=1)
def _xnys() -> xcals.ExchangeCalendar:
    return xcals.get_calendar("XNYS", start=_CALENDAR_START)


def _as_date(value: date | str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


class TradingCalendar:
    """Thin wrapper over the exchange_calendars XNYS calendar."""

    def __init__(self) -> None:
        self._cal = _xnys()

    def sessions_between(self, start: date | str, end: date | str) -> list[date]:
        """Return NYSE session dates in [start, end] inclusive (empty if start>end)."""
        start_d = _as_date(start)
        end_d = _as_date(end)
        if start_d > end_d:
            return []
        idx = self._cal.sessions_in_range(
            start_d.isoformat(), end_d.isoformat()
        )
        return [ts.date() for ts in idx]

    def is_session(self, day: date | str) -> bool:
        d = _as_date(day)
        return self._cal.is_session(d.isoformat())

    def last_completed_session(self, now_utc: datetime) -> date:
        """Return the most recent session whose 21:00-UTC completion has passed."""
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)
        else:
            now_utc = now_utc.astimezone(UTC)

        today = now_utc.date()
        # A window comfortably longer than the longest exchange closure.
        window_start = today - timedelta(days=30)
        sessions = self.sessions_between(window_start, today)
        for session in reversed(sessions):
            completion = datetime.combine(
                session, time(_SESSION_COMPLETE_HOUR_UTC, 0), tzinfo=UTC
            )
            if now_utc >= completion:
                return session
        # Extremely unlikely (a >30-day market closure); widen and retry once.
        sessions = self.sessions_between(today - timedelta(days=90), today)
        for session in reversed(sessions):
            completion = datetime.combine(
                session, time(_SESSION_COMPLETE_HOUR_UTC, 0), tzinfo=UTC
            )
            if now_utc >= completion:
                return session
        raise ValueError(f"No completed NYSE session found before {now_utc.isoformat()}")


__all__ = ["TradingCalendar"]
