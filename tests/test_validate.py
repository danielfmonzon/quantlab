"""Tests for single-source validation."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from quantlab.data import CANONICAL_COLUMNS
from quantlab.data.validate import validate

# Five consecutive NYSE sessions (2024-07-04 is a holiday, gap-free coverage).
SESSIONS = [
    date(2024, 7, 1), date(2024, 7, 2), date(2024, 7, 3), date(2024, 7, 5), date(2024, 7, 8),
]
INCEPTION = date(2024, 7, 1)
# "now" such that the last session (2024-07-08) is exactly complete -> staleness 0.
NOW = datetime(2024, 7, 8, 21, 0, tzinfo=UTC)


def _validate(df, **kw):
    kw.setdefault("now", NOW)
    return validate(df, "SPY", inception_date=INCEPTION, **kw)


# -- Clean frame ------------------------------------------------------------


def test_clean_frame_passes(make_frame) -> None:
    report = _validate(make_frame(SESSIONS))
    assert report.passed is True
    assert report.errors == []
    assert report.warnings == []
    assert report.row_count == 5
    assert report.first_date == date(2024, 7, 1)
    assert report.last_date == date(2024, 7, 8)
    assert report.staleness_sessions == 0


# -- ERROR rules ------------------------------------------------------------


def test_schema_mismatch_fails(make_frame) -> None:
    df = make_frame(SESSIONS).drop(columns=["volume"])
    report = _validate(df)
    assert not report.passed
    assert any("schema mismatch" in e for e in report.errors)


def test_dtype_mismatch_fails(make_frame) -> None:
    df = make_frame(SESSIONS)
    df["date"] = df["date"].astype(str)  # wrong dtype for the date column
    report = _validate(df)
    assert not report.passed
    assert any("dtype mismatch" in e for e in report.errors)


def test_non_unique_dates_fail(make_frame) -> None:
    df = make_frame([date(2024, 7, 1), date(2024, 7, 1)])
    report = _validate(df)
    assert not report.passed
    assert any("non-unique dates" in e for e in report.errors)


def test_non_monotonic_dates_fail(make_frame) -> None:
    df = make_frame([date(2024, 7, 2), date(2024, 7, 1)])  # descending
    report = _validate(df)
    assert not report.passed
    assert any("monotonic" in e for e in report.errors)


def test_nonpositive_price_fails(make_frame) -> None:
    df = make_frame(SESSIONS)
    df.loc[2, "adj_low"] = -1.0  # a price column, does not disturb OHLC ordering
    report = _validate(df)
    assert not report.passed
    assert any("nonpositive" in e for e in report.errors)


def test_high_less_than_low_fails(make_frame) -> None:
    df = make_frame(SESSIONS, high=[101, 101, 90, 101, 101], low=[99, 99, 95, 99, 99])
    report = _validate(df)
    assert not report.passed
    assert any("high < low" in e for e in report.errors)


def test_high_below_max_open_close_fails(make_frame) -> None:
    # high (100.4) below close (100.5)
    df = make_frame(SESSIONS, high=[101, 101, 100.4, 101, 101])
    report = _validate(df)
    assert not report.passed
    assert any("high < max(open, close)" in e for e in report.errors)


def test_low_above_min_open_close_fails(make_frame) -> None:
    # low (100.1) above open (100.0)
    df = make_frame(SESSIONS, low=[99, 99, 100.1, 99, 99])
    report = _validate(df)
    assert not report.passed
    assert any("low > min(open, close)" in e for e in report.errors)


def test_negative_volume_fails(make_frame) -> None:
    df = make_frame(SESSIONS)
    df.loc[1, "volume"] = -5
    report = _validate(df)
    assert not report.passed
    assert any("negative 'volume'" in e for e in report.errors)


def test_missing_session_fails(make_frame) -> None:
    # Drop 2024-07-03, leaving a coverage gap between inception and last date.
    partial = [d for d in SESSIONS if d != date(2024, 7, 3)]
    report = _validate(make_frame(partial))
    assert not report.passed
    assert any("missing" in e and "NYSE session" in e for e in report.errors)


# -- WARNING rules ----------------------------------------------------------


def test_large_return_warns(make_frame) -> None:
    # 100 -> 130 is a +30% adj_close move (> 20%).
    df = make_frame(
        [date(2024, 7, 1), date(2024, 7, 2)],
        close=[100.0, 130.0],
        adj_close=[100.0, 130.0],
        open=[100.0, 130.0],
        high=[101.0, 131.0],
        low=[99.0, 129.0],
        adj_open=[100.0, 130.0],
        adj_high=[101.0, 131.0],
        adj_low=[99.0, 129.0],
    )
    report = validate(df, "SPY", inception_date=date(2024, 7, 1),
                      now=datetime(2024, 7, 2, 21, 0, tzinfo=UTC))
    assert report.passed is True
    assert any("20%" in w for w in report.warnings)


def test_zero_volume_warns(make_frame) -> None:
    df = make_frame(SESSIONS)
    df.loc[3, "volume"] = 0
    report = _validate(df)
    assert report.passed is True
    assert any("zero-volume" in w for w in report.warnings)


def test_staleness_warns(make_frame) -> None:
    # Data ends 2024-07-08 but "now" is weeks later -> many sessions behind.
    later = datetime(2024, 7, 31, 21, 0, tzinfo=UTC)
    report = _validate(make_frame(SESSIONS), now=later)
    assert report.passed is True
    assert report.staleness_sessions > 1
    assert any("stale" in w for w in report.warnings)


def test_report_columns_match_canonical(make_frame) -> None:
    # Guard: the fixture builds exactly the canonical schema.
    df = make_frame(SESSIONS)
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert isinstance(df, pd.DataFrame)
