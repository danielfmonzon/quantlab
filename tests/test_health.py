"""Tests for the data-health preflight."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from quantlab.data.alpaca_client import ClockInfo
from quantlab.data.calendar import TradingCalendar
from quantlab.data.health import preflight
from quantlab.data.store import ParquetStore

# now such that the last completed NYSE session is 2024-07-08.
NOW = datetime(2024, 7, 8, 21, 0, tzinfo=UTC)


def _fake_clock(is_open: bool) -> ClockInfo:
    return ClockInfo(
        is_open=is_open,
        next_open=datetime(2024, 7, 9, 13, 30, tzinfo=UTC),
        next_close=datetime(2024, 7, 8, 20, 0, tzinfo=UTC),
        timestamp=NOW,
    )


def test_fresh_store_passes(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    cal = TradingCalendar()
    sessions = cal.sessions_between(date(2024, 6, 1), date(2024, 7, 8))
    for sym in ("SPY", "QQQ"):
        store.upsert(sym, make_frame(sessions))

    report = preflight(["SPY", "QQQ"], store, cal, clock=None, now=NOW)
    assert report.data_fresh is True
    assert report.blocking_reasons == []
    assert report.market_open is None
    assert all(sh.staleness_sessions == 0 for sh in report.symbols)


def test_stale_symbol_flips_data_fresh(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    cal = TradingCalendar()
    fresh = cal.sessions_between(date(2024, 6, 1), date(2024, 7, 8))
    stale = cal.sessions_between(date(2024, 6, 1), date(2024, 7, 2))  # ends 3 sessions back
    store.upsert("SPY", make_frame(fresh))
    store.upsert("QQQ", make_frame(stale))

    report = preflight(["SPY", "QQQ"], store, cal, clock=None, now=NOW)
    assert report.data_fresh is False
    assert any("QQQ" in reason for reason in report.blocking_reasons)
    qqq = next(sh for sh in report.symbols if sh.symbol == "QQQ")
    assert qqq.staleness_sessions == 3
    spy = next(sh for sh in report.symbols if sh.symbol == "SPY")
    assert spy.staleness_sessions == 0


def test_market_open_reflects_clock(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    cal = TradingCalendar()
    sessions = cal.sessions_between(date(2024, 6, 1), date(2024, 7, 8))
    store.upsert("SPY", make_frame(sessions))

    report = preflight(["SPY"], store, cal, clock=_fake_clock(True), now=NOW)
    assert report.market_open is True
    assert report.data_fresh is True


def test_missing_symbol_blocks(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    cal = TradingCalendar()
    sessions = cal.sessions_between(date(2024, 6, 1), date(2024, 7, 8))
    store.upsert("SPY", make_frame(sessions))

    report = preflight(["SPY", "GLD"], store, cal, clock=None, now=NOW)
    assert report.data_fresh is False
    gld = next(sh for sh in report.symbols if sh.symbol == "GLD")
    assert gld.has_data is False
    assert any("GLD" in reason for reason in report.blocking_reasons)
