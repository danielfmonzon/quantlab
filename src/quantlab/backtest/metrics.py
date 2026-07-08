"""Performance metrics.

Conventions (documented so the unit-test fixtures can be computed by hand):

* Annualization factor: 252 trading days.
* ``cagr = (equity[-1] / equity[0]) ** (252 / n_returns) - 1``.
* ``annualized_vol = std(returns, ddof=1) * sqrt(252)``.
* ``sharpe = mean(returns) / std(returns, ddof=1) * sqrt(252)``   (rf = 0).
* ``sortino = mean(returns) / downside_dev * sqrt(252)`` where
  ``downside_dev = sqrt(mean(min(returns, 0) ** 2))`` (population, target 0).
* ``max_drawdown = min(equity / cummax(equity) - 1)`` (<= 0).
* ``max_drawdown_duration_days`` = longest run of consecutive underwater
  sessions (equity below its running peak).
* ``calmar = cagr / abs(max_drawdown)``.
* Monthly returns compound daily returns within each calendar month.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from pydantic import BaseModel

_ANN = 252


class Metrics(BaseModel):
    """Backtest performance summary."""

    cagr: float
    annualized_vol: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown: float
    max_drawdown_duration_days: int
    monthly_returns: dict[str, float]
    win_rate_monthly: float
    best_month: float | None
    worst_month: float | None
    exposure_avg: float
    annual_turnover: float
    total_costs: float
    n_sessions: int
    start: date
    end: date
    benchmark_cagr: float | None = None
    benchmark_max_drawdown: float | None = None


def _max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def _max_drawdown_duration(equity: pd.Series) -> int:
    if len(equity) == 0:
        return 0
    dd = (equity / equity.cummax() - 1.0).to_numpy()
    longest = current = 0
    for val in dd:
        if val < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _cagr(equity: pd.Series, n_returns: int) -> float:
    if len(equity) < 2 or n_returns <= 0:
        return 0.0
    total_growth = float(equity.iloc[-1] / equity.iloc[0])
    if total_growth <= 0.0:
        return -1.0
    return total_growth ** (_ANN / n_returns) - 1.0


def _monthly_returns(daily_returns: pd.Series) -> pd.Series:
    if daily_returns.empty:
        return pd.Series(dtype="float64")
    r = daily_returns.copy()
    r.index = pd.to_datetime(r.index)
    return (1.0 + r).resample("ME").prod() - 1.0


def compute_metrics(
    daily_returns: pd.Series,
    equity: pd.Series,
    benchmark_returns: pd.Series | None = None,
    *,
    weights: pd.DataFrame | None = None,
    turnover: pd.Series | None = None,
    costs: pd.Series | None = None,
) -> Metrics:
    """Compute performance metrics from a return series and its equity curve."""
    n = len(daily_returns)
    years = n / _ANN if n else 0.0

    if n >= 2:
        vol = float(daily_returns.std(ddof=1)) * np.sqrt(_ANN)
        mean = float(daily_returns.mean())
        std = float(daily_returns.std(ddof=1))
        sharpe = (mean / std * np.sqrt(_ANN)) if std > 0 else None
        neg = np.minimum(daily_returns.to_numpy(), 0.0)
        dd_dev = float(np.sqrt(np.mean(neg**2)))
        sortino = (mean / dd_dev * np.sqrt(_ANN)) if dd_dev > 0 else None
    else:
        vol, sharpe, sortino = 0.0, None, None

    cagr = _cagr(equity, n)
    max_dd = _max_drawdown(equity)
    dd_duration = _max_drawdown_duration(equity)
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else None

    monthly = _monthly_returns(daily_returns)
    monthly_dict = {ts.strftime("%Y-%m"): float(v) for ts, v in monthly.items()}
    win_rate = float((monthly > 0).mean()) if len(monthly) else 0.0
    best_month = float(monthly.max()) if len(monthly) else None
    worst_month = float(monthly.min()) if len(monthly) else None

    exposure_avg = 0.0
    if weights is not None and len(weights):
        exposure_avg = float(weights.sum(axis=1).mean())
    annual_turnover = (
        float(turnover.sum()) / years if turnover is not None and years > 0 else 0.0
    )
    total_costs = float(costs.sum()) if costs is not None else 0.0

    bench_cagr: float | None = None
    bench_max_dd: float | None = None
    if benchmark_returns is not None and len(benchmark_returns) >= 2:
        bench_equity = (1.0 + benchmark_returns.fillna(0.0)).cumprod()
        bench_cagr = _cagr(bench_equity, len(benchmark_returns))
        bench_max_dd = _max_drawdown(bench_equity)

    return Metrics(
        cagr=cagr,
        annualized_vol=vol,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown=max_dd,
        max_drawdown_duration_days=dd_duration,
        monthly_returns=monthly_dict,
        win_rate_monthly=win_rate,
        best_month=best_month,
        worst_month=worst_month,
        exposure_avg=exposure_avg,
        annual_turnover=annual_turnover,
        total_costs=total_costs,
        n_sessions=int(len(equity)),
        start=equity.index[0].date() if len(equity) else date(1970, 1, 1),
        end=equity.index[-1].date() if len(equity) else date(1970, 1, 1),
        benchmark_cagr=bench_cagr,
        benchmark_max_drawdown=bench_max_dd,
    )


__all__ = ["Metrics", "compute_metrics"]
