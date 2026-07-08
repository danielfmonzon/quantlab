"""Faber (2007) 10-month SMA timing model."""

from __future__ import annotations

import pandas as pd

from quantlab.backtest.signals import (
    month_end_sessions,
    safe_or_cash,
    trailing_month_end_closes,
)
from quantlab.backtest.strategy import Strategy

# Faber, M. (2007), "A Quantitative Approach to Tactical Asset Allocation":
# hold the risk asset while its price is above its 10-month simple moving
# average (evaluated on month-end closes), otherwise move to the safe asset.
_N_MONTHS = 10


class TrendSMA10(Strategy):
    """Risk-on above the 10-month SMA, safe-asset (or cash) below it."""

    def __init__(
        self,
        risk_symbol: str = "SPY",
        safe_symbol: str = "IEF",
        n_months: int = _N_MONTHS,
    ):
        self.risk_symbol = risk_symbol
        self.safe_symbol = safe_symbol
        self.n_months = n_months

    @property
    def name(self) -> str:
        return f"trend_sma{self.n_months}"

    @property
    def required_symbols(self) -> list[str]:
        # The safe asset is a fallback (cash if absent), so only the risk asset
        # is required to establish a usable start date.
        return [self.risk_symbol]

    @property
    def all_symbols(self) -> list[str]:
        return [self.risk_symbol, self.safe_symbol]

    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        return month_end_sessions(dates)

    def is_warmed_up(self, window: pd.DataFrame, current_date: pd.Timestamp) -> bool:
        return trailing_month_end_closes(window, self.risk_symbol, self.n_months) is not None

    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        closes = trailing_month_end_closes(window, self.risk_symbol, self.n_months)
        if closes is None:  # warmup: not enough month-ends yet
            return safe_or_cash(window, current_date, self.safe_symbol)
        sma = float(closes.mean())
        current = float(closes[-1])
        if current > sma:
            return {self.risk_symbol: 1.0}
        return safe_or_cash(window, current_date, self.safe_symbol)


__all__ = ["TrendSMA10"]
