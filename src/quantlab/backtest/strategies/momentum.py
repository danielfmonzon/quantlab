"""Antonacci (2014) Global Equities Momentum (GEM) structure."""

from __future__ import annotations

import pandas as pd

from quantlab.backtest.signals import (
    month_end_sessions,
    safe_or_cash,
    trailing_month_end_closes,
)
from quantlab.backtest.strategy import Strategy

# Antonacci, G. (2014), "Dual Momentum Investing": rank equity assets by their
# trailing 12-month total return (relative momentum), then hold the winner only
# if its 12-month return is positive (absolute momentum), else the safe asset.
_LOOKBACK_MONTHS = 12


class DualMomentum(Strategy):
    """Relative momentum between equities, gated by absolute momentum."""

    def __init__(
        self,
        equity_symbols: tuple[str, ...] = ("SPY", "EFA"),
        safe_symbol: str = "IEF",
        lookback_months: int = _LOOKBACK_MONTHS,
    ):
        self.equity_symbols = tuple(equity_symbols)
        self.safe_symbol = safe_symbol
        self.lookback_months = lookback_months

    @property
    def name(self) -> str:
        return "dualmom"

    @property
    def required_symbols(self) -> list[str]:
        return list(self.equity_symbols)

    @property
    def all_symbols(self) -> list[str]:
        return [*self.equity_symbols, self.safe_symbol]

    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        return month_end_sessions(dates)

    def _trailing_return(self, window: pd.DataFrame, symbol: str) -> float | None:
        closes = trailing_month_end_closes(window, symbol, self.lookback_months)
        if closes is None:
            return None
        # 12 month-ends: current vs the earliest of the 12 (== the 12-back close).
        return float(closes[-1] / closes[0] - 1.0)

    def is_warmed_up(self, window: pd.DataFrame, current_date: pd.Timestamp) -> bool:
        return all(self._trailing_return(window, s) is not None for s in self.equity_symbols)

    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        returns: dict[str, float] = {}
        for symbol in self.equity_symbols:
            r = self._trailing_return(window, symbol)
            if r is None:  # warmup: not enough month-ends for every equity leg
                return safe_or_cash(window, current_date, self.safe_symbol)
            returns[symbol] = r

        winner = max(returns, key=lambda s: returns[s])  # relative momentum
        if returns[winner] > 0.0:  # absolute momentum
            return {winner: 1.0}
        return safe_or_cash(window, current_date, self.safe_symbol)


__all__ = ["DualMomentum"]
