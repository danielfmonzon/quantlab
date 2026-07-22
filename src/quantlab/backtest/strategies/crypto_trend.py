"""Faber (2007) 10-month SMA timing model applied to BTC-USD (crypto, cash-safe).

Research-only. This mirrors the equity ``TrendSMA10`` rule verbatim, changed only
where crypto requires: it trades BTC-USD, has **no safe asset** (below the SMA
means 100% cash, not a bond substitute), and annualizes metrics on a 365-day
grid. Because the CryptoCalendar emits every UTC day, ``month_end_sessions``
already resolves each month-end to the last UTC calendar day of the month.

IRON RULE (as for every quantlab strategy): the parameters here — a 10-month SMA,
month-end rebalance, 365-day annualization — are fixed from the source literature
and crypto conventions. They are pre-registered and must NEVER be tuned against
backtest results.
"""

from __future__ import annotations

import pandas as pd

from quantlab.backtest.signals import month_end_sessions, trailing_month_end_closes
from quantlab.backtest.strategy import Strategy

# Faber, M. (2007), "A Quantitative Approach to Tactical Asset Allocation":
# hold the risk asset while its price is above its 10-month simple moving average
# (evaluated on month-end closes), otherwise move to cash (no safe asset here).
_N_MONTHS = 10
_CRYPTO_PERIODS_PER_YEAR = 365


class CryptoTrendBTC(Strategy):
    """Risk-on (100% BTC-USD) above the 10-month SMA, 100% CASH below it."""

    def __init__(self, risk_symbol: str = "BTC-USD", n_months: int = _N_MONTHS):
        self.risk_symbol = risk_symbol
        self.n_months = n_months

    @property
    def name(self) -> str:
        return "crypto_trend_btc"

    @property
    def required_symbols(self) -> list[str]:
        return [self.risk_symbol]

    # all_symbols inherits the default (== required_symbols): there is no safe
    # asset, so cash is the only alternative to holding BTC-USD.

    @property
    def periods_per_year(self) -> int:
        return _CRYPTO_PERIODS_PER_YEAR

    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        return month_end_sessions(dates)

    def is_warmed_up(self, window: pd.DataFrame, current_date: pd.Timestamp) -> bool:
        return trailing_month_end_closes(window, self.risk_symbol, self.n_months) is not None

    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        closes = trailing_month_end_closes(window, self.risk_symbol, self.n_months)
        if closes is None:  # warmup: fewer than n_months month-ends -> cash
            return {}
        sma = float(closes.mean())
        current = float(closes[-1])
        if current > sma:
            return {self.risk_symbol: 1.0}
        return {}  # below the SMA -> 100% cash (no safe-asset substitute)


__all__ = ["CryptoTrendBTC"]
