"""Tests for cross-source reconciliation (Tiingo vs Alpaca IEX)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pandas as pd

from quantlab.data.reconcile import reconcile


def _bdates(n: int, start: str = "2024-01-02") -> list[date]:
    return [ts.date() for ts in pd.bdate_range(start, periods=n)]


def _alpaca(dates: Sequence[date], closes: Sequence[float]) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(list(dates)),
            "open": [c - 1 for c in closes],
            "high": [c + 1 for c in closes],
            "low": [c - 2 for c in closes],
            "close": list(closes),
            "volume": [1000] * n,
        }
    )


def test_identical_frames_pass(make_frame) -> None:
    dates = _bdates(25)
    closes = [100.0 + i for i in range(25)]
    report = reconcile(make_frame(dates, close=closes), _alpaca(dates, closes), "SPY")
    assert report.passed is True
    assert report.n_overlap == 25
    assert report.n_mismatches == 0
    assert report.dates_only_in_tiingo == []
    assert report.dates_only_in_alpaca == []


def test_volume_difference_is_ignored(make_frame) -> None:
    dates = _bdates(25)
    closes = [100.0] * 25
    t = make_frame(dates, close=closes, volume=[5_000_000] * 25)
    a = _alpaca(dates, closes)  # tiny IEX-style volume
    a["volume"] = [1234] * 25
    report = reconcile(t, a, "SPY")
    assert report.passed is True  # volume divergence must never matter


def test_single_mismatch_reported_but_passes(make_frame) -> None:
    dates = _bdates(60)
    closes = [100.0] * 60
    a_closes = list(closes)
    a_closes[10] = 105.0  # 5% > 0.75% tolerance
    report = reconcile(make_frame(dates, close=closes), _alpaca(dates, a_closes), "SPY")
    assert report.passed is True  # 1/60 = 1.67% < 2%
    assert report.n_mismatches == 1
    assert any("mismatch" in w for w in report.warnings)
    assert report.mismatches[0].date == dates[10]


def test_excess_mismatches_fail(make_frame) -> None:
    dates = _bdates(30)
    closes = [100.0] * 30
    a_closes = list(closes)
    for i in (5, 10, 15):
        a_closes[i] = 105.0
    report = reconcile(make_frame(dates, close=closes), _alpaca(dates, a_closes), "SPY")
    assert report.passed is False  # 3/30 = 10% > 2%
    assert report.n_mismatches == 3


def test_date_misalignment_fails(make_frame) -> None:
    dates = _bdates(30)
    closes = [100.0] * 30
    t = make_frame(dates, close=closes)
    keep = [i for i in range(30) if i not in (5, 6, 7, 8, 9, 10)]  # drop 6 interior dates
    a = _alpaca([dates[i] for i in keep], [closes[i] for i in keep])
    report = reconcile(t, a, "SPY")
    assert report.passed is False
    assert len(report.dates_only_in_tiingo) == 6  # > 5 allowed


def test_short_overlap_fails(make_frame) -> None:
    dates = _bdates(15)
    closes = [100.0] * 15
    report = reconcile(make_frame(dates, close=closes), _alpaca(dates, closes), "SPY")
    assert report.passed is False
    assert report.n_overlap == 15  # < 20 sessions


def test_empty_source_fails(make_frame) -> None:
    dates = _bdates(25)
    empty = _alpaca([], [])
    report = reconcile(make_frame(dates, close=[100.0] * 25), empty, "SPY")
    assert report.passed is False
    assert report.n_overlap == 0
