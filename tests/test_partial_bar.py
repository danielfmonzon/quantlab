"""Completed-sessions-only enforcement on every path that READS a bar (DEFECT 2).

Ingestion may write a bar for the session in progress -- the crypto upsert does it
on every run, and the next run overwrites it. Reading it is the defect: the
2026-07-24 diagnosis traced a 120 bps swing in ``crypto_voltarget``'s reported
weekly divergence (and a sign flip in its cumulative figure) to a BTC bar that read
65,230 at 05:43 UTC and settled at 64,083.

These tests pin both read paths -- the runner's signal and the shadow -- and assert
the equity path is untouched, since an EOD bar only appears after its session ends.
No network, no real store.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.panel import build_price_panel, completed_sessions_only
from quantlab.broker.alpaca_trading import AccountInfo, OrderInfo
from quantlab.data.calendar import CryptoCalendar, TradingCalendar
from quantlab.data.health import HealthReport
from quantlab.data.validate import ValidationReport
from quantlab.paper.runner import (
    calendar_for_account,
    current_target_weights,
    make_paper_strategy,
    run_paper,
)
from quantlab.reporting.shadow import shadow_coverage_end, shadow_returns

# 05:43 UTC on 2026-07-24 -- the exact shape of the real crypto run whose partial
# bar corrupted the week: the 07-24 UTC day has ~18h left to run.
NOW = datetime(2026, 7, 24, 5, 43, 3, tzinfo=UTC)
LAST_COMPLETE = date(2026, 7, 23)
PARTIAL_DAY = date(2026, 7, 24)


def _frame(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "adj_close": prices})


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
        return self._frames.get(symbol, _frame(pd.DatetimeIndex([]), np.array([])))

    def load_metadata(self, symbol: str) -> None:
        return None


def _btc_prices(n: int) -> np.ndarray:
    # Deterministic drift + oscillation. The amplitude/period are chosen so trailing
    # realized vol lands WELL ABOVE the strategy's 20% target: that puts the
    # vol-target weight strictly between 0 and 1, where it can actually move in
    # response to a new bar. A quieter series pins the weight at the 1.0 cap and
    # every "unchanged" assertion below would pass vacuously.
    i = np.arange(n, dtype=float)
    return 60_000.0 * (1.0004 ** i) * (1.0 + 0.05 * np.sin(i / 1.5))


def _btc_store(*, with_partial: bool) -> FakeStore:
    """Daily BTC bars through 2026-07-23, optionally plus a partial 07-24 bar.

    The crypto grid is every UTC calendar day, so ``date_range`` (not ``bdate_range``).
    """
    dates = pd.date_range(end=pd.Timestamp(LAST_COMPLETE), periods=500, freq="D")
    prices = _btc_prices(len(dates))
    if with_partial:
        # A violent in-progress print: -20% intraday. If anything reads it, the
        # trailing-vol weight and the signal date both move measurably.
        dates = dates.append(pd.DatetimeIndex([pd.Timestamp(PARTIAL_DAY)]))
        prices = np.append(prices, prices[-1] * 0.80)
    return FakeStore({"BTC-USD": _frame(dates, prices)})


def _equity_store() -> FakeStore:
    dates = pd.bdate_range(end=pd.Timestamp(LAST_COMPLETE), periods=400)
    spy = 700.0 * (1.0004 ** np.arange(len(dates)))
    ief = np.full(len(dates), 95.0)
    return FakeStore({"SPY": _frame(dates, spy), "IEF": _frame(dates, ief)})


def _panel(store: FakeStore, label: str) -> pd.DataFrame:
    strategy = make_paper_strategy(label)
    panel = build_price_panel(store, strategy.all_symbols)
    usable = panel[strategy.required_symbols].dropna()
    return panel.loc[usable.index.min():]


def _broker(equity: float = 100_000.0) -> MagicMock:
    broker = MagicMock()
    broker.get_account.return_value = AccountInfo(
        equity=equity, cash=equity, currency="USD",
        account_blocked=False, trading_blocked=False,
    )
    broker.get_positions.return_value = []
    broker.submit_order.side_effect = lambda symbol, side, notional, coid: OrderInfo(
        id=f"oid-{symbol}", client_order_id=coid, symbol=symbol, side=side,
        notional=notional, status="accepted", submitted_at=None,
    )
    return broker


def _run(label: str, store: FakeStore, tmp_path, symbols: list[str]):
    return run_paper(
        label, dry_run=True, store=store, broker=_broker(), do_ingest=False,
        validation_override=[ValidationReport(symbol=s, passed=True) for s in symbols],
        health_override=HealthReport(generated_at=NOW, market_open=True,
                                     data_fresh=True, symbols=[], blocking_reasons=[]),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet",
        write_report=False, alert_fn=lambda _a: None,
    )


# --------------------------------------------------------------------------- #
# The helper itself                                                           #
# --------------------------------------------------------------------------- #

def test_completed_sessions_only_drops_exactly_the_in_progress_bar() -> None:
    panel = _panel(_btc_store(with_partial=True), "crypto_voltarget")
    assert panel.index[-1].date() == PARTIAL_DAY  # the partial bar IS present

    filtered = completed_sessions_only(panel, CryptoCalendar(), NOW)
    assert filtered.index[-1].date() == LAST_COMPLETE
    assert len(filtered) == len(panel) - 1


def test_completed_sessions_only_is_a_noop_without_calendar_context() -> None:
    panel = _panel(_btc_store(with_partial=True), "crypto_voltarget")
    pd.testing.assert_frame_equal(completed_sessions_only(panel, None, NOW), panel)
    pd.testing.assert_frame_equal(completed_sessions_only(panel, CryptoCalendar(), None), panel)


def test_calendar_for_account_maps_asset_classes() -> None:
    assert isinstance(calendar_for_account("crypto_voltarget"), CryptoCalendar)
    assert isinstance(calendar_for_account("crypto_trend"), CryptoCalendar)
    assert isinstance(calendar_for_account("trend"), TradingCalendar)
    assert isinstance(calendar_for_account("voltarget"), TradingCalendar)


# --------------------------------------------------------------------------- #
# (a) the signal ignores a partial bar                                        #
# --------------------------------------------------------------------------- #

def test_signal_ignores_a_partial_current_day_crypto_bar() -> None:
    strategy = make_paper_strategy("crypto_voltarget")
    clean = _panel(_btc_store(with_partial=False), "crypto_voltarget")
    partial = _panel(_btc_store(with_partial=True), "crypto_voltarget")

    baseline_w, baseline_d = current_target_weights(strategy, clean)
    assert baseline_d == LAST_COMPLETE
    assert baseline_w  # a real, non-cash weight -- the assertions below have teeth
    assert 0.0 < baseline_w["BTC-USD"] < 1.0

    filtered_w, filtered_d = current_target_weights(
        strategy, partial, calendar=CryptoCalendar(), now=NOW
    )
    # Adding the partial bar changes NOTHING once the filter is on.
    assert filtered_w == baseline_w
    assert filtered_d == baseline_d == LAST_COMPLETE


def test_the_partial_bar_would_move_the_signal_if_it_were_read() -> None:
    """Teeth check: without the filter the same bar shifts weight AND signal date."""
    strategy = make_paper_strategy("crypto_voltarget")
    clean = _panel(_btc_store(with_partial=False), "crypto_voltarget")
    partial = _panel(_btc_store(with_partial=True), "crypto_voltarget")

    baseline_w, baseline_d = current_target_weights(strategy, clean)
    unfiltered_w, unfiltered_d = current_target_weights(strategy, partial)

    assert unfiltered_d == PARTIAL_DAY != baseline_d
    assert unfiltered_w["BTC-USD"] != pytest.approx(baseline_w["BTC-USD"])
    # A -20% print inflates trailing vol, so vol-targeting cuts exposure hard.
    assert unfiltered_w["BTC-USD"] < baseline_w["BTC-USD"]


def test_crypto_run_target_weights_unaffected_by_a_partial_bar(tmp_path) -> None:
    clean = _run("crypto_voltarget", _btc_store(with_partial=False),
                 tmp_path / "a", ["BTC-USD"])
    partial = _run("crypto_voltarget", _btc_store(with_partial=True),
                   tmp_path / "b", ["BTC-USD"])
    assert not clean.aborted and not partial.aborted
    assert clean.target_weights == partial.target_weights
    assert clean.target_weights  # not the trivially-equal cash case


# --------------------------------------------------------------------------- #
# (b) the shadow ignores a partial bar                                        #
# --------------------------------------------------------------------------- #

def test_shadow_returns_ignore_a_partial_current_day_crypto_bar() -> None:
    start, end = date(2026, 6, 1), PARTIAL_DAY
    clean = shadow_returns("crypto_voltarget", _btc_store(with_partial=False),
                           start, end, now=NOW)
    partial = shadow_returns("crypto_voltarget", _btc_store(with_partial=True),
                             start, end, now=NOW)
    assert not clean.empty
    pd.testing.assert_series_equal(clean, partial)
    assert clean.index.max().date() == LAST_COMPLETE


def test_shadow_would_differ_if_the_partial_bar_were_read() -> None:
    """Teeth check: with the cutoff pushed past 07-24 the partial bar does land."""
    start, end = date(2026, 6, 1), PARTIAL_DAY
    filtered = shadow_returns("crypto_voltarget", _btc_store(with_partial=True),
                              start, end, now=NOW)
    # A day later the 07-24 session is complete, so its (now final) bar is read.
    later = shadow_returns("crypto_voltarget", _btc_store(with_partial=True),
                           start, end, now=NOW + pd.Timedelta(days=1))
    assert len(later) == len(filtered) + 1
    assert later.index.max().date() == PARTIAL_DAY


def test_shadow_coverage_end_is_the_last_completed_session() -> None:
    for with_partial in (False, True):
        assert shadow_coverage_end(
            "crypto_voltarget", _btc_store(with_partial=with_partial), now=NOW
        ) == LAST_COMPLETE


def test_shadow_coverage_end_is_none_when_nothing_is_usable() -> None:
    empty = FakeStore({"BTC-USD": _frame(pd.DatetimeIndex([]), np.array([]))})
    assert shadow_coverage_end("crypto_voltarget", empty, now=NOW) is None


# --------------------------------------------------------------------------- #
# The equity path is byte-identical: EOD bars only exist post-completion       #
# --------------------------------------------------------------------------- #

def test_equity_signal_identical_with_the_filter_on_and_off() -> None:
    strategy = make_paper_strategy("trend")
    panel = _panel(_equity_store(), "trend")

    off_w, off_d = current_target_weights(strategy, panel)
    on_w, on_d = current_target_weights(
        strategy, panel, calendar=TradingCalendar(), now=NOW
    )
    assert (on_w, on_d) == (off_w, off_d)
    assert off_w == {"SPY": 1.0}  # warmed and risk-on, not a vacuous match


def test_equity_run_target_weights_match_the_unfiltered_signal(tmp_path) -> None:
    store = _equity_store()
    report = _run("trend", store, tmp_path, ["SPY", "IEF"])
    assert not report.aborted

    strategy = make_paper_strategy("trend")
    unfiltered, _ = current_target_weights(strategy, _panel(store, "trend"))
    assert report.target_weights == unfiltered == {"SPY": 1.0}


def test_equity_filter_does_not_truncate_an_eod_panel() -> None:
    panel = _panel(_equity_store(), "trend")
    filtered = completed_sessions_only(panel, TradingCalendar(), NOW)
    pd.testing.assert_frame_equal(filtered, panel)
