"""Volatility-targeting overlay on a single risk asset."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.backtest.signals import month_end_sessions, trailing_daily_returns
from quantlab.backtest.strategy import Strategy

# Scale exposure to a fixed annualized volatility target using trailing realized
# vol. Conventional parameters: 10% target, ~1-month (20 trading day) realized
# window, long-only with no leverage (weight capped at 1.0 always).
_TARGET_VOL = 0.10
_LOOKBACK_DAYS = 20
_MAX_WEIGHT = 1.0
_ANN = 252


class VolTarget(Strategy):
    """Weight = min(max_weight, target_vol / realized_vol); remainder in cash."""

    def __init__(
        self,
        risk_symbol: str = "SPY",
        target_vol: float = _TARGET_VOL,
        lookback_days: int = _LOOKBACK_DAYS,
        max_weight: float = _MAX_WEIGHT,
    ):
        self.risk_symbol = risk_symbol
        self.target_vol = target_vol
        self.lookback_days = lookback_days
        self.max_weight = max_weight

    @property
    def name(self) -> str:
        return "voltarget"

    @property
    def required_symbols(self) -> list[str]:
        return [self.risk_symbol]

    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        return month_end_sessions(dates)

    def is_warmed_up(self, window: pd.DataFrame, current_date: pd.Timestamp) -> bool:
        return trailing_daily_returns(window, self.risk_symbol, self.lookback_days) is not None

    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        returns = trailing_daily_returns(window, self.risk_symbol, self.lookback_days)
        if returns is None:  # warmup: not enough daily history yet -> cash
            return {}
        realized_vol = float(np.std(returns, ddof=1) * np.sqrt(_ANN))
        if not np.isfinite(realized_vol) or realized_vol <= 0.0:
            return {}  # zero/undefined vol -> cash, never inf
        weight = min(self.max_weight, self.target_vol / realized_vol)
        if weight <= 0.0:
            return {}
        return {self.risk_symbol: float(weight)}


__all__ = ["VolTarget"]
