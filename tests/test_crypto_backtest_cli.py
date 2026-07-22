"""Tests for the crypto-backtest CLI helpers: --no-risk semantics and the
per-calendar-year return breakdown. No network, no stored data required."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.strategies import BuyAndHold
from quantlab.backtest.strategy import Strategy
from quantlab.cli import _calendar_year_returns, build_parser
from quantlab.risk.engine import HALT_DAILY_LOSS, RiskEngine
from quantlab.risk.limits import load_risk_limits

_BTC = "BTC-USD"


def _btc_panel(returns: list[float]) -> pd.DataFrame:
    """Daily BTC-USD price panel from a list of returns (initial price 100)."""
    idx = pd.bdate_range("2020-01-01", periods=len(returns) + 1)
    px = [100.0]
    for r in returns:
        px.append(px[-1] * (1.0 + r))
    return pd.DataFrame({_BTC: px}, index=idx)


# -- --no-risk semantics: risk_engine=None yields no risk events -------------


def _panel_that_trips_a_halt() -> pd.DataFrame:
    # Held from day 1; a -10% day (< -3% daily limit) trips a HALT, and the
    # following day records the forced-liquidation risk event.
    return _btc_panel([0.005, 0.005, -0.10, 0.005, 0.005])


def test_gated_run_records_a_halt() -> None:
    panel = _panel_that_trips_a_halt()
    engine = RiskEngine(load_risk_limits())
    result = run_backtest(panel, BuyAndHold(symbol=_BTC), cost_bps=25.0, risk_engine=engine)
    assert result.risk_events, "gated run should record at least one risk event"
    assert any(e["action"] == HALT_DAILY_LOSS for e in result.risk_events)


def test_ungated_run_has_no_risk_events() -> None:
    panel = _panel_that_trips_a_halt()
    # This is exactly what --no-risk wires: risk_engine=None.
    result = run_backtest(panel, BuyAndHold(symbol=_BTC), cost_bps=25.0, risk_engine=None)
    assert result.risk_events == []


def test_no_risk_flag_parses() -> None:
    parser = build_parser()
    assert parser.parse_args(["crypto-backtest", "--no-risk"]).no_risk is True
    assert parser.parse_args(["crypto-backtest"]).no_risk is False


def test_default_strategy_class_declares_252() -> None:
    # Guard: the risk overlay toggle does not disturb the default annualization.
    class _Trivial(Strategy):
        @property
        def name(self) -> str:
            return "trivial"

        def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
            return []

        def target_weights(
            self, window: pd.DataFrame, current_date: pd.Timestamp
        ) -> dict[str, float]:
            return {}

    assert _Trivial().periods_per_year == 252


# -- Calendar-year return computation ---------------------------------------


def test_calendar_year_returns_compounds_within_each_year() -> None:
    idx = pd.to_datetime(["2020-06-01", "2020-06-02", "2021-03-01", "2021-03-02"])
    s = pd.Series([0.10, 0.10, 0.00, -0.50], index=idx)
    out = _calendar_year_returns(s)
    assert set(out) == {"2020", "2021"}
    assert out["2020"] == pytest.approx(1.10 * 1.10 - 1.0)  # +21%
    assert out["2021"] == pytest.approx(-0.50)


def test_calendar_year_returns_spans_three_years() -> None:
    idx = pd.to_datetime(["2019-12-31", "2020-07-01", "2021-01-04"])
    s = pd.Series([0.05, -0.20, 0.10], index=idx)
    out = _calendar_year_returns(s)
    assert out["2019"] == pytest.approx(0.05)
    assert out["2020"] == pytest.approx(-0.20)
    assert out["2021"] == pytest.approx(0.10)


def test_calendar_year_returns_empty_series() -> None:
    assert _calendar_year_returns(pd.Series(dtype="float64")) == {}


def test_calendar_year_matches_full_compounded_return() -> None:
    # The product of (1 + yearly return) equals the whole-series total return.
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2020-01-01", periods=520)  # ~2 years of business days
    r = pd.Series(rng.normal(0.0, 0.02, len(idx)), index=idx)
    out = _calendar_year_returns(r)
    total_by_year = np.prod([1.0 + v for v in out.values()]) - 1.0
    total_direct = float((1.0 + r).prod() - 1.0)
    assert total_by_year == pytest.approx(total_direct, rel=1e-12)
