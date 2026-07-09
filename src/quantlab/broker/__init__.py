"""Alpaca paper trading (order endpoints).

This package is the FIRST in quantlab to touch trading endpoints. It is
paper-only by construction: the trading client's ``base_url`` comes from
``Settings.ALPACA_BASE_URL``, whose Batch-1 safety gate rejects any live
endpoint. There is no code path here that can reach ``api.alpaca.markets``.
"""

from __future__ import annotations

from quantlab.broker.alpaca_trading import (
    AccountInfo,
    AlpacaTradingClient,
    OrderInfo,
    Position,
)

__all__ = ["AlpacaTradingClient", "AccountInfo", "Position", "OrderInfo"]
