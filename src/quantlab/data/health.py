"""Data-health preflight gate (read-only report).

Produces a :class:`HealthReport` summarizing, per symbol, how many completed
NYSE sessions the stored data is behind, plus overall data freshness and the
live market-open state. This object is a pure report today; in Phase 4 it will
become the risk engine's no-trade gate. It performs no trading actions.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel

from quantlab.data.alpaca_client import ClockInfo
from quantlab.data.calendar import TradingCalendar
from quantlab.data.store import ParquetStore
from quantlab.data.validate import staleness_sessions

# Sentinel staleness for a symbol with no stored data (n/a rather than a count).
NO_DATA_STALENESS = -1

# A symbol is "fresh" if at most this many completed sessions behind.
MAX_FRESH_STALENESS = 1


class SymbolHealth(BaseModel):
    """Per-symbol freshness within a :class:`HealthReport`."""

    symbol: str
    has_data: bool
    last_date: date | None
    staleness_sessions: int


class HealthReport(BaseModel):
    """Overall data-health snapshot across the stored universe."""

    generated_at: datetime
    market_open: bool | None
    data_fresh: bool
    symbols: list[SymbolHealth]
    blocking_reasons: list[str]


def preflight(
    symbols: list[str],
    store: ParquetStore,
    calendar: TradingCalendar,
    clock: ClockInfo | None,
    now: datetime,
) -> HealthReport:
    """Build a read-only :class:`HealthReport` for ``symbols``.

    ``data_fresh`` is True iff every symbol has data and is at most
    ``MAX_FRESH_STALENESS`` completed sessions behind the last NYSE close.
    """
    per_symbol: list[SymbolHealth] = []
    blocking_reasons: list[str] = []

    for symbol in symbols:
        df = store.load(symbol)
        if df.empty:
            per_symbol.append(
                SymbolHealth(
                    symbol=symbol,
                    has_data=False,
                    last_date=None,
                    staleness_sessions=NO_DATA_STALENESS,
                )
            )
            blocking_reasons.append(f"{symbol}: no stored data")
            continue

        last_date = pd.to_datetime(df["date"]).max().date()
        stale = staleness_sessions(calendar, last_date, now)
        per_symbol.append(
            SymbolHealth(
                symbol=symbol,
                has_data=True,
                last_date=last_date,
                staleness_sessions=stale,
            )
        )
        if stale > MAX_FRESH_STALENESS:
            blocking_reasons.append(
                f"{symbol}: {stale} completed session(s) behind the last NYSE close"
            )

    data_fresh = all(
        sh.has_data and sh.staleness_sessions <= MAX_FRESH_STALENESS for sh in per_symbol
    )
    market_open = clock.is_open if clock is not None else None

    return HealthReport(
        generated_at=now,
        market_open=market_open,
        data_fresh=data_fresh,
        symbols=per_symbol,
        blocking_reasons=blocking_reasons,
    )


__all__ = ["HealthReport", "SymbolHealth", "preflight"]
