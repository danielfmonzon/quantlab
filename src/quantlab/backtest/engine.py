"""Daily backtest engine.

EXECUTION SEMANTICS (authoritative — the test oracle mirrors these exactly):

* Returns use adj_close: ``r_t = adj_close_t / adj_close_{t-1} - 1`` per asset.
* Signal lag: a strategy observes data through the close of session ``t`` (a
  rebalance date) and emits target weights; those weights become *effective* at
  the close of session ``t+1``. One full session of lag — no lookahead is
  possible by construction. Weights emitted on the final session never take
  effect (there is no ``t+1``).
* Drift: between rebalances, weights drift with relative asset performance; they
  are NOT re-normalized daily. Cash (any shortfall of the risky weights from 1)
  earns 0%.
* Bounds: weights are long-only, each in [0, 1], and sum to <= 1.
* Costs: ``cost_bps`` (default 5.0) is applied to one-way turnover measured in
  weight space:

      turnover_t = sum_i |w_effective_i,t - w_drifted_i,t|
      cost_t     = cost_bps / 1e4 * turnover_t         (a fraction of value)

  On a day weights change, the portfolio value after drift ``V_drift`` becomes
  ``V_t = V_drift * (1 - cost_t)`` — equivalently the day's return is the drift
  return minus ``cost_t``. Assets are traded to their target dollar amounts
  ``w_eff_i * V_drift`` and the cost is borne by cash. On non-rebalance days
  ``w_effective == w_drifted`` so turnover and cost are 0.
* A symbol contributes only from its inception. A NaN price before inception
  must carry weight 0; the engine RAISES if a strategy assigns nonzero weight to
  a symbol whose price is NaN on the effective date.

Hard failures (raise DataError): empty panel, weights out of bounds, weight sum
> 1 + 1e-9, nonzero weight on a NaN price, or a strategy window that leaks a date
beyond ``current_date``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from quantlab.backtest.strategy import Strategy
from quantlab.data import DataError

_SUM_TOL = 1e-9


@dataclass
class BacktestResult:
    """Outputs of a backtest run."""

    equity: pd.Series
    daily_returns: pd.Series
    weights_history: pd.DataFrame
    turnover: pd.Series
    costs_paid: pd.Series
    config: dict[str, Any] = field(default_factory=dict)


def _validate_and_vectorize(
    weights: dict[str, float], symbols: list[str], where: str
) -> np.ndarray:
    for sym, w in weights.items():
        if sym not in symbols:
            raise DataError(f"strategy weighted unknown symbol {sym!r} ({where})")
        if w < -_SUM_TOL or w > 1.0 + _SUM_TOL:
            raise DataError(f"weight for {sym} out of bounds [0,1]: {w} ({where})")
    total = sum(weights.values())
    if total > 1.0 + _SUM_TOL:
        raise DataError(f"weights sum to {total} > 1 ({where})")
    return np.array([float(weights.get(s, 0.0)) for s in symbols], dtype=float)


def run_backtest(
    panel: pd.DataFrame,
    strategy: Strategy,
    cost_bps: float = 5.0,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """Run ``strategy`` over ``panel`` (adj_close). See module docstring."""
    if panel is None or panel.empty or panel.shape[1] == 0:
        raise DataError("empty panel: nothing to backtest")

    symbols = list(panel.columns)
    dates = list(panel.index)
    n = len(dates)
    rate = cost_bps / 1e4

    price_vals = panel.to_numpy(dtype=float)
    ret_vals = panel.pct_change(fill_method=None).to_numpy(dtype=float)

    # -- Emissions -> effective-day target weights (one session of lag) ------
    pos = {d: i for i, d in enumerate(dates)}
    effective: dict[int, np.ndarray] = {}
    for r in strategy.rebalance_dates(dates):
        i = pos[r]
        if i + 1 >= n:
            continue  # emitted on the last session: never takes effect
        window = panel.loc[:r]
        # Enforce no-lookahead: the strategy only ever sees date <= current_date.
        if len(window) and window.index.max() > r:
            raise DataError("window leaked a date beyond current_date")
        weights = strategy.target_weights(window, r)
        effective[i + 1] = _validate_and_vectorize(
            weights, symbols, where=f"emit@{r.date().isoformat()}"
        )

    # -- Day-by-day recursion (weights + equity) -----------------------------
    equity = np.empty(n, dtype=float)
    weights_hist = np.zeros((n, len(symbols)), dtype=float)
    daily_ret = np.zeros(n, dtype=float)
    turnover_arr = np.zeros(n, dtype=float)
    costs_arr = np.zeros(n, dtype=float)

    w_prev = np.zeros(len(symbols), dtype=float)  # start fully in cash
    equity[0] = initial_capital
    e_prev = initial_capital

    for k in range(1, n):
        r_t = ret_vals[k]
        held = w_prev != 0.0
        if np.any(held & ~np.isfinite(r_t)):
            bad = [symbols[j] for j in np.where(held & ~np.isfinite(r_t))[0]]
            raise DataError(f"nonzero weight on NaN return for {bad} on {dates[k].date()}")

        contrib = np.where(held, w_prev * r_t, 0.0)
        growth = 1.0 + contrib.sum()
        e_drift = e_prev * growth

        drifted_val = np.where(held, w_prev * (1.0 + r_t), 0.0)
        w_drift = drifted_val / growth  # drifted asset weights (cash is the remainder)

        if k in effective:
            w_eff = effective[k]
            price_row = price_vals[k]
            bad_price = (w_eff > 0.0) & ~np.isfinite(price_row)
            if np.any(bad_price):
                names = [symbols[j] for j in np.where(bad_price)[0]]
                raise DataError(f"nonzero weight on NaN price for {names} on {dates[k].date()}")
            turnover = float(np.abs(w_eff - w_drift).sum())
        else:
            w_eff = w_drift
            turnover = 0.0

        cost = rate * turnover
        e_t = e_drift * (1.0 - cost)

        equity[k] = e_t
        daily_ret[k] = e_t / e_prev - 1.0
        weights_hist[k] = w_eff
        turnover_arr[k] = turnover
        costs_arr[k] = cost * e_drift  # dollars

        # Actual holding fractions of the post-cost value carry into next day.
        w_prev = w_eff / (1.0 - cost) if cost > 0.0 else w_eff
        e_prev = e_t

    idx = pd.Index(dates, name="date")
    result = BacktestResult(
        equity=pd.Series(equity, index=idx, name="equity"),
        daily_returns=pd.Series(daily_ret[1:], index=idx[1:], name="return"),
        weights_history=pd.DataFrame(weights_hist, index=idx, columns=symbols),
        turnover=pd.Series(turnover_arr[1:], index=idx[1:], name="turnover"),
        costs_paid=pd.Series(costs_arr[1:], index=idx[1:], name="cost"),
        config={
            "strategy": strategy.name,
            "cost_bps": cost_bps,
            "initial_capital": initial_capital,
            "symbols": symbols,
            "start": dates[0].date().isoformat() if n else None,
            "end": dates[-1].date().isoformat() if n else None,
        },
    )
    return result


__all__ = ["BacktestResult", "run_backtest"]
