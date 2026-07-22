"""Volatility-targeting overlay on BTC-USD (crypto).

Research-only. This mirrors the equity ``VolTarget`` structure exactly, changed
only where crypto requires: it trades BTC-USD, targets 20% annualized volatility,
and annualizes trailing realized vol on a 365-day grid (24/7 market) rather than
252. Long-only, weight capped at 1.0, remainder in cash, month-end rebalance.

IRON RULE (as for every quantlab strategy): these parameters — 20% target vol, a
trailing 20-day realized-vol window, 365-day annualization, weight cap 1.0 — are
pre-registered and FINAL. They must NEVER be tuned against backtest results.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantlab.backtest.signals import month_end_sessions, trailing_daily_returns
from quantlab.backtest.strategy import Strategy

# Scale exposure to a fixed annualized volatility target using trailing realized
# vol. Crypto parameters: 20% target, ~1-month (20 trading day) realized window,
# long-only with no leverage (weight capped at 1.0 always), annualized on 365
# days because crypto trades every calendar day.
_TARGET_VOL = 0.20
_LOOKBACK_DAYS = 20
_MAX_WEIGHT = 1.0
_ANN = 365
_CRYPTO_PERIODS_PER_YEAR = 365


class CryptoVolTargetBTC(Strategy):
    """Weight = min(max_weight, target_vol / realized_vol); remainder in cash."""

    def __init__(
        self,
        risk_symbol: str = "BTC-USD",
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
        return "crypto_voltarget_btc"

    @property
    def required_symbols(self) -> list[str]:
        return [self.risk_symbol]

    @property
    def periods_per_year(self) -> int:
        return _CRYPTO_PERIODS_PER_YEAR

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


__all__ = ["CryptoVolTargetBTC"]
