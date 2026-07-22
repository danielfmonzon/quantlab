"""Tests for the parameterized annualization factor in compute_metrics."""

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


RETURNS = [0.02, -0.01, 0.03, 0.00]


def test_default_is_252_and_unchanged() -> None:
    returns = _returns_series(RETURNS)
    equity = _equity_from(RETURNS)
    default = compute_metrics(returns, equity)
    explicit_252 = compute_metrics(returns, equity, periods_per_year=252)

    arr = np.array(RETURNS)
    exp_vol = arr.std(ddof=1) * np.sqrt(252)
    exp_sharpe = arr.mean() / arr.std(ddof=1) * np.sqrt(252)
    exp_cagr = (equity.iloc[-1] / equity.iloc[0]) ** (252 / 4) - 1.0

    # Omitting the parameter is identical to passing 252 (equities unchanged).
    assert default.annualized_vol == pytest.approx(explicit_252.annualized_vol, rel=1e-15)
    assert default.sharpe == pytest.approx(explicit_252.sharpe, rel=1e-15)
    assert default.cagr == pytest.approx(explicit_252.cagr, rel=1e-15)
    assert default.annualized_vol == pytest.approx(exp_vol, rel=1e-12)
    assert default.sharpe == pytest.approx(exp_sharpe, rel=1e-12)
    assert default.cagr == pytest.approx(exp_cagr, rel=1e-12)


def test_365_scales_vol_and_sharpe_correctly() -> None:
    returns = _returns_series(RETURNS)
    equity = _equity_from(RETURNS)
    m = compute_metrics(returns, equity, periods_per_year=365)

    arr = np.array(RETURNS)
    exp_vol = arr.std(ddof=1) * np.sqrt(365)
    exp_sharpe = arr.mean() / arr.std(ddof=1) * np.sqrt(365)
    exp_dd_dev = np.sqrt(np.mean(np.minimum(arr, 0.0) ** 2))
    exp_sortino = arr.mean() / exp_dd_dev * np.sqrt(365)
    exp_cagr = (equity.iloc[-1] / equity.iloc[0]) ** (365 / 4) - 1.0

    assert m.annualized_vol == pytest.approx(exp_vol, rel=1e-12)
    assert m.sharpe == pytest.approx(exp_sharpe, rel=1e-12)
    assert m.sortino == pytest.approx(exp_sortino, rel=1e-12)
    assert m.cagr == pytest.approx(exp_cagr, rel=1e-12)


def test_365_vs_252_differ_by_sqrt_ratio_on_vol_and_sharpe() -> None:
    returns = _returns_series(RETURNS)
    equity = _equity_from(RETURNS)
    m252 = compute_metrics(returns, equity, periods_per_year=252)
    m365 = compute_metrics(returns, equity, periods_per_year=365)

    ratio = np.sqrt(365 / 252)
    assert m365.annualized_vol == pytest.approx(m252.annualized_vol * ratio, rel=1e-12)
    assert m365.sharpe == pytest.approx(m252.sharpe * ratio, rel=1e-12)
    # A different annualization must actually move the numbers.
    assert m365.sharpe != pytest.approx(m252.sharpe, rel=1e-6)


def test_365_scales_annual_turnover() -> None:
    returns = _returns_series(RETURNS)
    equity = _equity_from(RETURNS)
    turnover = pd.Series([1.0, 0.0, 0.0, 0.0], index=returns.index)
    m = compute_metrics(returns, equity, turnover=turnover, periods_per_year=365)
    # annual_turnover = sum(turnover) / (n_returns / ppy) = 1.0 / (4/365) = 91.25
    assert m.annual_turnover == pytest.approx(365.0 / 4.0, rel=1e-12)
