"""Independent, deliberately naive backtest oracle (test-only ground truth).

This tracks per-asset DOLLAR holdings and cash explicitly in a plain Python loop
with no vectorization and no cleverness. It mirrors the engine's documented
semantics: drift each asset by its price ratio, and on effective-rebalance days
(one session after emission) trade to target dollar amounts, charging
``cost_bps / 1e4 * dollars_traded``. It exists solely to cross-check the engine.
"""

from __future__ import annotations

import pandas as pd

from quantlab.backtest.strategy import Strategy


def run_backtest_oracle(
    panel: pd.DataFrame,
    strategy: Strategy,
    cost_bps: float,
    initial_capital: float = 100_000.0,
) -> pd.Series:
    """Return the equity curve computed by explicit dollar bookkeeping."""
    symbols = list(panel.columns)
    dates = list(panel.index)
    rate = cost_bps / 1e4

    pos = {d: i for i, d in enumerate(dates)}
    effective: dict[pd.Timestamp, dict[str, float]] = {}
    for r in strategy.rebalance_dates(dates):
        i = pos[r]
        if i + 1 >= len(dates):
            continue
        window = panel.loc[:r]
        effective[dates[i + 1]] = dict(strategy.target_weights(window, r))

    holdings = {s: 0.0 for s in symbols}  # dollars per asset
    cash = initial_capital
    equity = [initial_capital]  # value at dates[0]

    for k in range(1, len(dates)):
        d, prev = dates[k], dates[k - 1]

        # 1) Drift each held asset by its price ratio.
        for s in symbols:
            if holdings[s] != 0.0:
                ratio = float(panel.at[d, s]) / float(panel.at[prev, s])
                holdings[s] *= ratio
        v_drift = sum(holdings.values()) + cash

        # 2) On an effective-rebalance day, trade to target dollar amounts.
        if d in effective:
            w = effective[d]
            targets = {s: w.get(s, 0.0) * v_drift for s in symbols}
            dollars_traded = sum(abs(targets[s] - holdings[s]) for s in symbols)
            cost = rate * dollars_traded
            for s in symbols:
                holdings[s] = targets[s]
            cash = v_drift - sum(targets.values()) - cost

        equity.append(sum(holdings.values()) + cash)

    return pd.Series(equity, index=pd.Index(dates, name="date"), name="equity")
