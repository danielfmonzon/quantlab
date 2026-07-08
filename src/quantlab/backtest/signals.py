"""Shared signal helpers for strategies.

Lives at ``backtest.signals`` (not inside ``backtest.strategies``) so that both
``backtest.strategy`` and the tactical modules in ``backtest.strategies`` can
import it without a circular import (the ``strategies`` package re-exports the
baseline strategies defined in ``backtest.strategy``).

Each helper returns ``None`` cleanly on insufficient history so strategies stay
thin and never raise or emit NaN weights during warmup.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def month_end_sessions(dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """Return the last session of each calendar month present in ``dates``."""
    last_by_month: dict[tuple[int, int], pd.Timestamp] = {}
    for d in dates:
        last_by_month[(d.year, d.month)] = d  # dates ascending -> last wins
    return sorted(last_by_month.values())


def trailing_month_end_closes(
    window: pd.DataFrame, symbol: str, n: int
) -> np.ndarray | None:
    """Last ``n`` valid month-end closes of ``symbol`` (including the current one).

    Returns ``None`` if the symbol is absent or has fewer than ``n`` valid
    month-end observations in ``window``.
    """
    if symbol not in window.columns:
        return None
    me = month_end_sessions(list(window.index))
    if not me:
        return None
    series = window[symbol].reindex(me).dropna()
    if len(series) < n:
        return None
    return series.to_numpy(dtype=float)[-n:]


def trailing_daily_returns(
    window: pd.DataFrame, symbol: str, n: int
) -> np.ndarray | None:
    """Last ``n`` daily simple returns of ``symbol``.

    Returns ``None`` if fewer than ``n + 1`` valid prices are available (need one
    extra price to form ``n`` returns).
    """
    if symbol not in window.columns:
        return None
    series = window[symbol].dropna()
    if len(series) < n + 1:
        return None
    returns = series.pct_change(fill_method=None).dropna().to_numpy(dtype=float)
    if len(returns) < n:
        return None
    return returns[-n:]


def safe_or_cash(
    window: pd.DataFrame, current_date: pd.Timestamp, safe_symbol: str
) -> dict[str, float]:
    """Weight the safe symbol fully if it has a price today, else hold cash."""
    if safe_symbol in window.columns and pd.notna(window[safe_symbol].loc[current_date]):
        return {safe_symbol: 1.0}
    return {}


__all__ = [
    "month_end_sessions",
    "trailing_month_end_closes",
    "trailing_daily_returns",
    "safe_or_cash",
]
