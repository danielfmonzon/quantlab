"""Tests for the 24/7 CryptoCalendar and the shared MarketCalendar interface."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd

from quantlab.backtest.signals import month_end_sessions
from quantlab.data.calendar import (
    CryptoCalendar,
    MarketCalendar,
    TradingCalendar,
    XNYSCalendar,
)

# -- Interface wiring -------------------------------------------------------


def test_calendars_implement_market_calendar() -> None:
    assert isinstance(CryptoCalendar(), MarketCalendar)
    assert isinstance(XNYSCalendar(), MarketCalendar)


def test_trading_calendar_is_xnys_alias() -> None:
    # Existing equities code imports TradingCalendar and must keep XNYS behavior.
    assert TradingCalendar is XNYSCalendar


# -- Session listing (weekends + 365/366 day counts) ------------------------


def test_sessions_between_includes_weekends() -> None:
    cal = CryptoCalendar()
    # 2024-07-06 is a Saturday, 2024-07-07 a Sunday: both are crypto sessions.
    sessions = cal.sessions_between(date(2024, 7, 4), date(2024, 7, 8))
    assert sessions == [
        date(2024, 7, 4),
        date(2024, 7, 5),
        date(2024, 7, 6),
        date(2024, 7, 7),
        date(2024, 7, 8),
    ]


def test_sessions_between_empty_when_start_after_end() -> None:
    assert CryptoCalendar().sessions_between(date(2024, 7, 8), date(2024, 7, 1)) == []


def test_non_leap_year_has_365_sessions() -> None:
    cal = CryptoCalendar()
    assert len(cal.sessions_between(date(2023, 1, 1), date(2023, 12, 31))) == 365


def test_leap_year_has_366_sessions() -> None:
    cal = CryptoCalendar()
    assert len(cal.sessions_between(date(2024, 1, 1), date(2024, 12, 31))) == 366


def test_is_session_true_on_weekend() -> None:
    assert CryptoCalendar().is_session(date(2024, 7, 6)) is True  # Saturday


# -- Month-end = last UTC calendar day --------------------------------------


def test_month_end_is_last_utc_calendar_day() -> None:
    cal = CryptoCalendar()
    dates = [pd.Timestamp(d) for d in cal.sessions_between(date(2024, 1, 1), date(2024, 3, 15))]
    ends = month_end_sessions(dates)
    assert pd.Timestamp("2024-01-31") in ends
    assert pd.Timestamp("2024-02-29") in ends  # leap February's last day
    # A partial trailing month yields its last available day.
    assert ends[-1] == pd.Timestamp("2024-03-15")


# -- Completion cutoff (00:00 UTC next day + 15-minute buffer) ---------------


def test_session_not_complete_before_buffer() -> None:
    cal = CryptoCalendar()
    # 00:14 UTC on 2024-01-02: the 2024-01-01 session's 00:15 cutoff hasn't passed.
    now = datetime(2024, 1, 2, 0, 14, tzinfo=UTC)
    assert cal.last_completed_session(now) == date(2023, 12, 31)


def test_session_complete_at_buffer() -> None:
    cal = CryptoCalendar()
    # Exactly 00:15 UTC on 2024-01-02: 2024-01-01 is now complete.
    now = datetime(2024, 1, 2, 0, 15, tzinfo=UTC)
    assert cal.last_completed_session(now) == date(2024, 1, 1)


def test_session_complete_midday() -> None:
    cal = CryptoCalendar()
    now = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    assert cal.last_completed_session(now) == date(2024, 1, 1)


def test_naive_now_treated_as_utc() -> None:
    cal = CryptoCalendar()
    assert cal.last_completed_session(datetime(2024, 1, 2, 0, 15)) == date(2024, 1, 1)


def test_non_utc_tz_now_is_converted() -> None:
    cal = CryptoCalendar()
    # 2024-01-01 19:20 in UTC-5 == 2024-01-02 00:20 UTC -> past the 00:15 cutoff.
    now = datetime(2024, 1, 1, 19, 20, tzinfo=timezone(timedelta(hours=-5)))
    assert cal.last_completed_session(now) == date(2024, 1, 1)
