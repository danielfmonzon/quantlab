"""Tests for tactical strategies and shared signal helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.signals import month_end_sessions
from quantlab.backtest.strategies import DualMomentum, TrendSMA10, VolTarget
from quantlab.data.calendar import TradingCalendar
from tests.oracle import run_backtest_oracle

# -- Fixture builders -------------------------------------------------------


def _monthly(values: dict[str, list[float]]) -> pd.DataFrame:
    """Panel indexed by month-end (one row per month)."""
    m = len(next(iter(values.values())))
    idx = pd.date_range("2020-01-31", periods=m, freq="ME")
    return pd.DataFrame(values, index=idx)


def _prices_from_returns(returns: Sequence[float], p0: float = 100.0) -> list[float]:
    px = [p0]
    for r in returns:
        px.append(px[-1] * (1.0 + r))
    return px


def _daily_spy(returns: Sequence[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=len(returns) + 1)
    return pd.DataFrame({"SPY": _prices_from_returns(returns)}, index=idx)


def _last(panel: pd.DataFrame) -> pd.Timestamp:
    return panel.index[-1]


# -- month_end_sessions -----------------------------------------------------


def test_month_end_sessions_known_quarter() -> None:
    cal = TradingCalendar()
    sess = [pd.Timestamp(d) for d in cal.sessions_between(date(2024, 7, 1), date(2024, 9, 30))]
    assert month_end_sessions(sess) == [
        pd.Timestamp("2024-07-31"),
        pd.Timestamp("2024-08-30"),
        pd.Timestamp("2024-09-30"),
    ]


# -- TrendSMA10 -------------------------------------------------------------


def test_trend_uptrend_goes_risk_on() -> None:
    # 11 rising month-ends: last close (200) > SMA of the last 10 (155) -> risk.
    panel = _monthly({"SPY": [100 + 10 * i for i in range(11)], "IEF": [100.0] * 11})
    w = TrendSMA10().target_weights(panel, _last(panel))
    assert w == {"SPY": 1.0}


def test_trend_crash_goes_safe() -> None:
    # Rising 10 months then a crash below the SMA on the current month-end.
    spy = [100 + 10 * i for i in range(10)] + [50.0]  # ..., 190, then 50
    panel = _monthly({"SPY": spy, "IEF": [100.0] * 11})
    w = TrendSMA10().target_weights(panel, _last(panel))
    assert w == {"IEF": 1.0}  # 50 < SMA(110..190, 50) = 140 -> safe


def test_trend_warmup_uses_safe_when_present() -> None:
    panel = _monthly({"SPY": [100.0, 110.0, 120.0], "IEF": [100.0, 100.0, 100.0]})
    w = TrendSMA10().target_weights(panel, _last(panel))
    assert w == {"IEF": 1.0}  # <10 month-ends -> warmup -> safe


def test_trend_warmup_uses_cash_when_safe_absent() -> None:
    panel = _monthly({"SPY": [100.0, 110.0, 120.0], "IEF": [np.nan, np.nan, np.nan]})
    w = TrendSMA10().target_weights(panel, _last(panel))
    assert w == {}  # safe not present -> cash


# -- DualMomentum -----------------------------------------------------------


def test_dualmom_picks_higher_positive_momentum() -> None:
    # 12 month-ends. SPY rises (+~43% over window), EFA flat (0%).
    panel = _monthly(
        {
            "SPY": [100.0 * (1.03**i) for i in range(12)],
            "EFA": [100.0] * 12,
            "IEF": [100.0] * 12,
        }
    )
    w = DualMomentum().target_weights(panel, _last(panel))
    assert w == {"SPY": 1.0}  # SPY 12m return > EFA and > 0


def test_dualmom_all_negative_goes_safe() -> None:
    # Both equities decline over the window -> absolute momentum fails -> safe.
    panel = _monthly(
        {
            "SPY": [100.0 * (0.98**i) for i in range(12)],  # ~ -22%
            "EFA": [100.0 * (0.99**i) for i in range(12)],  # ~ -10% (winner, still <0)
            "IEF": [100.0] * 12,
        }
    )
    w = DualMomentum().target_weights(panel, _last(panel))
    assert w == {"IEF": 1.0}


def test_dualmom_warmup_returns_safe() -> None:
    panel = _monthly({"SPY": [100.0] * 5, "EFA": [100.0] * 5, "IEF": [100.0] * 5})
    w = DualMomentum().target_weights(panel, _last(panel))
    assert w == {"IEF": 1.0}  # <12 month-ends -> warmup -> safe


# -- VolTarget --------------------------------------------------------------


def test_voltarget_low_vol_caps_at_one() -> None:
    panel = _daily_spy([0.001, -0.001] * 10)  # 20 returns, tiny vol
    w = VolTarget().target_weights(panel, _last(panel))
    assert w == {"SPY": 1.0}  # target/realized >> 1 -> capped at max_weight


def test_voltarget_high_vol_scales_down_exactly() -> None:
    returns = np.array([0.03, -0.03] * 10)  # 20 returns, high vol
    panel = _daily_spy(returns.tolist())
    w = VolTarget().target_weights(panel, _last(panel))
    realized = float(np.std(returns, ddof=1) * np.sqrt(252))
    expected = min(1.0, 0.10 / realized)
    assert expected < 1.0
    assert w["SPY"] == pytest.approx(expected, rel=1e-12)


def test_voltarget_zero_vol_is_cash_no_inf() -> None:
    panel = _daily_spy([0.0] * 20)  # constant price -> zero realized vol
    w = VolTarget().target_weights(panel, _last(panel))
    assert w == {}  # guarded to cash, never inf/NaN


def test_voltarget_warmup_is_cash() -> None:
    panel = _daily_spy([0.001] * 10)  # only 11 prices (<21) -> warmup
    w = VolTarget().target_weights(panel, _last(panel))
    assert w == {}


# -- Engine vs oracle (tactical) --------------------------------------------


@pytest.mark.parametrize("cost_bps", [0.0, 25.0])
def test_trend_matches_oracle_with_regime_flip(cost_bps: float) -> None:
    rng = np.random.default_rng(5)
    n = 400
    dates = pd.bdate_range("2019-01-02", periods=n)
    # SPY drifts up for the first half, down for the second -> the SMA flips.
    drift = np.where(np.arange(n - 1) < 200, 0.0012, -0.0012)
    spy = _prices_from_returns(drift + rng.normal(0.0, 0.008, n - 1), 100.0)
    ief = _prices_from_returns(0.0002 + rng.normal(0.0, 0.002, n - 1), 100.0)
    panel = pd.DataFrame({"SPY": spy, "IEF": ief}, index=dates)

    strat = TrendSMA10()
    engine = run_backtest(panel, strat, cost_bps=cost_bps, initial_capital=100_000.0)
    oracle = run_backtest_oracle(panel, strat, cost_bps, initial_capital=100_000.0)
    np.testing.assert_allclose(engine.equity.to_numpy(), oracle.to_numpy(), rtol=1e-9)


def test_tactical_no_lookahead() -> None:
    rng = np.random.default_rng(3)
    n = 300
    dates = pd.bdate_range("2019-01-02", periods=n)
    spy = _prices_from_returns(rng.normal(0.0005, 0.01, n - 1), 100.0)
    ief = _prices_from_returns(rng.normal(0.0002, 0.002, n - 1), 100.0)
    panel = pd.DataFrame({"SPY": spy, "IEF": ief}, index=dates)

    class PeekingTrend(TrendSMA10):
        def target_weights(self, window: pd.DataFrame, current_date: pd.Timestamp):
            assert window.index.max() <= current_date  # engine must slice
            return super().target_weights(window, current_date)

    # Completes without the assertion firing -> the window was always sliced.
    run_backtest(panel, PeekingTrend(), cost_bps=0.0)
