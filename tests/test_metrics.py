"""Metrics tests — each formula against a hand-computed fixture."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.metrics import compute_metrics


def _equity_from(returns: list[float], start: float = 100.0) -> pd.Series:
    dates = pd.bdate_range("2024-01-01", periods=len(returns) + 1)
    vals = [start]
    for r in returns:
        vals.append(vals[-1] * (1.0 + r))
    return pd.Series(vals, index=dates)


def _returns_series(returns: list[float]) -> pd.Series:
    dates = pd.bdate_range("2024-01-01", periods=len(returns) + 1)
    return pd.Series(returns, index=dates[1:])


def test_max_drawdown_of_monotonic_curve_is_zero() -> None:
    # equity 100 -> 110 -> 121 never falls: drawdown is exactly 0.
    equity = _equity_from([0.10, 0.10])
    returns = _returns_series([0.10, 0.10])
    m = compute_metrics(returns, equity)
    assert m.max_drawdown == 0.0
    assert m.max_drawdown_duration_days == 0
    assert m.calmar is None  # undefined when there is no drawdown


def test_fifty_percent_drop_then_recovery() -> None:
    # equity 100 -> 50 -> 100: trough is 50% below the 100 peak.
    equity = _equity_from([-0.5, 1.0])
    returns = _returns_series([-0.5, 1.0])
    m = compute_metrics(returns, equity)
    assert m.max_drawdown == pytest.approx(-0.5, rel=1e-12)
    assert m.max_drawdown_duration_days == 1  # one underwater session (the 50 point)


def test_hand_computed_return_stats() -> None:
    # returns = [0.02, -0.01, 0.03, 0.00]; mean = 0.01.
    # sample std (ddof=1): sqrt(((0.01^2)+(0.02^2)+(0.02^2)+(0.01^2))/3)
    #                    = sqrt(0.0010/3) = 0.0182574...
    # ann_vol = std * sqrt(252) = 0.289828...
    # sharpe  = 0.01 / 0.0182574 * sqrt(252) = 8.69502...
    # downside dev (target 0, population) = sqrt((0.01^2)/4) = 0.005
    # sortino = 0.01 / 0.005 * sqrt(252) = 31.7490...
    # cagr    = (equity[-1]/equity[0])^(252/4) - 1
    returns_list = [0.02, -0.01, 0.03, 0.00]
    returns = _returns_series(returns_list)
    equity = _equity_from(returns_list)
    m = compute_metrics(returns, equity)

    arr = np.array(returns_list)
    exp_vol = arr.std(ddof=1) * np.sqrt(252)
    exp_sharpe = arr.mean() / arr.std(ddof=1) * np.sqrt(252)
    exp_dd_dev = np.sqrt(np.mean(np.minimum(arr, 0.0) ** 2))
    exp_sortino = arr.mean() / exp_dd_dev * np.sqrt(252)
    exp_cagr = (equity.iloc[-1] / equity.iloc[0]) ** (252 / 4) - 1.0

    assert m.annualized_vol == pytest.approx(exp_vol, rel=1e-12)
    assert m.sharpe == pytest.approx(exp_sharpe, rel=1e-12)
    assert m.sortino == pytest.approx(exp_sortino, rel=1e-12)
    assert m.cagr == pytest.approx(exp_cagr, rel=1e-12)
    # sanity on the hand values in the comment:
    assert m.annualized_vol == pytest.approx(0.289828, rel=1e-4)
    assert m.sharpe == pytest.approx(8.69502, rel=1e-4)
    assert m.sortino == pytest.approx(31.7490, rel=1e-4)


def test_monthly_returns_and_win_rate() -> None:
    # 40 business days spanning Jan/Feb 2024; constant +0.1%/day.
    dates = pd.bdate_range("2024-01-02", periods=40)
    returns = pd.Series([0.001] * 40, index=dates)
    equity = pd.Series(
        np.concatenate([[100.0], 100.0 * np.cumprod(1.0 + returns.to_numpy())]),
        index=pd.bdate_range("2024-01-01", periods=41),
    )
    m = compute_metrics(returns, equity)
    assert set(m.monthly_returns) == {"2024-01", "2024-02"}
    assert m.win_rate_monthly == 1.0  # every month positive
    assert m.best_month is not None and m.best_month > 0
    assert m.n_sessions == 41


def test_exposure_turnover_costs_from_optional_inputs() -> None:
    returns = _returns_series([0.01, 0.01, 0.01, 0.01])
    equity = _equity_from([0.01, 0.01, 0.01, 0.01])
    weights = pd.DataFrame(
        {"A": [0.5, 0.5, 0.5, 0.5, 0.5]}, index=equity.index
    )
    turnover = pd.Series([1.0, 0.0, 0.0, 0.0], index=returns.index)
    costs = pd.Series([25.0, 0.0, 0.0, 0.0], index=returns.index)
    m = compute_metrics(returns, equity, weights=weights, turnover=turnover, costs=costs)
    assert m.exposure_avg == pytest.approx(0.5)
    assert m.total_costs == pytest.approx(25.0)
    # annual_turnover = sum(turnover) / (n_returns / 252) = 1.0 / (4/252) = 63
    assert m.annual_turnover == pytest.approx(63.0, rel=1e-9)


def test_benchmark_metrics_populated() -> None:
    returns = _returns_series([0.01, -0.02, 0.03, 0.01])
    equity = _equity_from([0.01, -0.02, 0.03, 0.01])
    bench = _returns_series([0.00, -0.01, 0.02, 0.00])
    m = compute_metrics(returns, equity, benchmark_returns=bench)
    assert m.benchmark_cagr is not None
    assert m.benchmark_max_drawdown is not None
    assert m.benchmark_max_drawdown <= 0.0
