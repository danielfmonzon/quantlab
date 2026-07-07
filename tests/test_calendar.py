"""Tests for the XNYS trading calendar wrapper."""

from __future__ import annotations

from datetime import UTC, date, datetime

from quantlab.data.calendar import TradingCalendar


def test_sessions_between_excludes_july_4_holiday() -> None:
    cal = TradingCalendar()
    sessions = cal.sessions_between(date(2024, 7, 1), date(2024, 7, 8))

    assert sessions == [
        date(2024, 7, 1),
        date(2024, 7, 2),
        date(2024, 7, 3),
        date(2024, 7, 5),
        date(2024, 7, 8),
    ]
    # July 4th (holiday) and the weekend are excluded.
    assert date(2024, 7, 4) not in sessions
    assert date(2024, 7, 6) not in sessions
    assert date(2024, 7, 7) not in sessions


def test_sessions_between_empty_when_start_after_end() -> None:
    cal = TradingCalendar()
    assert cal.sessions_between(date(2024, 7, 8), date(2024, 7, 1)) == []


def test_last_completed_session_before_2100_utc() -> None:
    cal = TradingCalendar()
    # 20:59 UTC on Monday 2024-07-08: that session is NOT yet complete,
    # so the last completed session is the prior one (Friday 2024-07-05).
    now = datetime(2024, 7, 8, 20, 59, tzinfo=UTC)
    assert cal.last_completed_session(now) == date(2024, 7, 5)


def test_last_completed_session_at_2100_utc() -> None:
    cal = TradingCalendar()
    # 21:00 UTC on Monday 2024-07-08: the session is now complete.
    now = datetime(2024, 7, 8, 21, 0, tzinfo=UTC)
    assert cal.last_completed_session(now) == date(2024, 7, 8)


def test_last_completed_session_naive_treated_as_utc() -> None:
    cal = TradingCalendar()
    now = datetime(2024, 7, 8, 21, 0)  # naive -> assumed UTC
    assert cal.last_completed_session(now) == date(2024, 7, 8)
