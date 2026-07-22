"""Market calendars behind a small shared interface.

``MarketCalendar`` is the minimal interface the codebase actually consumes:
listing the sessions between two dates, testing session containment, and finding
the last *completed* session as of some instant. Two implementations exist:

* ``XNYSCalendar`` — the NYSE (XNYS) calendar. A session is considered
  *completed* only after 21:00 UTC on the session date — the regular NYSE close
  is 21:00 UTC (16:00 ET) during standard time; we treat 21:00 UTC as a uniform
  close-plus-buffer so a session isn't reported complete while the market may
  still be settling. ``TradingCalendar`` is kept as a backward-compatible alias
  of this class, so every existing equities call site is unchanged.

* ``CryptoCalendar`` — 24/7 markets: every UTC calendar day is a session
  (365/366 a year). A session (a UTC calendar day) is *completed* once that UTC
  day has ended (00:00 UTC the next day) plus a 15-minute ingestion buffer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

import exchange_calendars as xcals

# Uniform "session complete" cutoff for XNYS: 21:00 UTC on the session date.
_SESSION_COMPLETE_HOUR_UTC = 21

# exchange_calendars defaults to only ~20 years of history; extend the lower
# bound so validation can cover every session back to each ETF's inception.
# (The upper bound keeps its default, which already runs past the current date.)
_CALENDAR_START = "1990-01-01"

# Crypto session-completion buffer: a UTC day is final 15 minutes into the next.
_CRYPTO_COMPLETION_BUFFER = timedelta(minutes=15)


@lru_cache(maxsize=1)
def _xnys() -> xcals.ExchangeCalendar:
    return xcals.get_calendar("XNYS", start=_CALENDAR_START)


def _as_date(value: date | str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


class MarketCalendar(ABC):
    """Minimal calendar interface consumed by validation and health checks."""

    @abstractmethod
    def sessions_between(self, start: date | str, end: date | str) -> list[date]:
        """Session dates in [start, end] inclusive (empty if start > end)."""

    @abstractmethod
    def is_session(self, day: date | str) -> bool:
        """Whether ``day`` is a trading session on this calendar."""

    @abstractmethod
    def last_completed_session(self, now_utc: datetime) -> date:
        """The most recent session whose completion cutoff has passed."""


class XNYSCalendar(MarketCalendar):
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


class CryptoCalendar(MarketCalendar):
    """24/7 calendar: every UTC calendar day is a session (365/366 a year).

    A session (a UTC calendar day ``D``) is *complete* once the UTC day has ended
    — 00:00 UTC of ``D+1`` — plus a 15-minute ingestion buffer, so a feed has a
    moment to settle the prior day before we treat it as final. The month-end
    session for a month is naturally its last UTC calendar day (this class emits
    every day, so ``signals.month_end_sessions`` selects the last one).
    """

    def sessions_between(self, start: date | str, end: date | str) -> list[date]:
        """Return every UTC calendar day in [start, end] inclusive (weekends included)."""
        start_d = _as_date(start)
        end_d = _as_date(end)
        if start_d > end_d:
            return []
        span = (end_d - start_d).days
        return [start_d + timedelta(days=i) for i in range(span + 1)]

    def is_session(self, day: date | str) -> bool:
        _as_date(day)  # reject unparseable input; every calendar day is a session
        return True

    def last_completed_session(self, now_utc: datetime) -> date:
        """Return the last UTC day complete as of ``now_utc`` (incl. the 15-min buffer)."""
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)
        else:
            now_utc = now_utc.astimezone(UTC)
        # Day D completes at midnight(D+1) + buffer. Subtracting the buffer maps
        # "now" back to the day whose midnight boundary it has cleared; the last
        # completed session is the day before that.
        threshold = now_utc - _CRYPTO_COMPLETION_BUFFER
        return threshold.date() - timedelta(days=1)


# Backward-compatible alias: existing equities code imports ``TradingCalendar``
# and must keep the exact XNYS behavior it has today.
TradingCalendar = XNYSCalendar


__all__ = [
    "MarketCalendar",
    "XNYSCalendar",
    "CryptoCalendar",
    "TradingCalendar",
]
