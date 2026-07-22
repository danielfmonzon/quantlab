"""Strategy implementations — a single import surface.

Re-exports the baseline strategies (defined in ``backtest.strategy``) alongside
the tactical strategies so callers can ``from quantlab.backtest.strategies
import BuyAndHold, TrendSMA10, ...``.
"""

from __future__ import annotations

from quantlab.backtest.strategies.crypto_trend import CryptoTrendBTC
from quantlab.backtest.strategies.crypto_voltarget import CryptoVolTargetBTC
from quantlab.backtest.strategies.momentum import DualMomentum
from quantlab.backtest.strategies.trend import TrendSMA10
from quantlab.backtest.strategies.voltarget import VolTarget
from quantlab.backtest.strategy import BuyAndHold, FixedWeights, Strategy

__all__ = [
    "Strategy",
    "BuyAndHold",
    "FixedWeights",
    "TrendSMA10",
    "DualMomentum",
    "VolTarget",
    "CryptoTrendBTC",
    "CryptoVolTargetBTC",
]
