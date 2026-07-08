"""Strategy interface and baseline strategies.

A strategy is observation-only: it receives a window of prices with
``date <= current_date`` (the engine enforces the slice) and returns target
weights. The engine applies those weights with one full session of lag, so a
strategy can never peek at or trade on same-day-or-future information.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """Abstract base for weight-emitting strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name (used in logs/reports)."""

    @abstractmethod
    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        """Subset of ``dates`` on which the strategy re-emits target weights."""

    @abstractmethod
    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        """Target weights given prices observed through ``current_date``.

        ``window`` contains only rows with ``date <= current_date``.
        """


def month_end_sessions(dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """Return the last session of each calendar month present in ``dates``."""
    last_by_month: dict[tuple[int, int], pd.Timestamp] = {}
    for d in dates:
        last_by_month[(d.year, d.month)] = d  # dates ascending -> last wins
    return sorted(last_by_month.values())


class BuyAndHold(Strategy):
    """Hold a single symbol at weight 1.0; rebalance once, at the start."""

    def __init__(self, symbol: str = "SPY"):
        self.symbol = symbol

    @property
    def name(self) -> str:
        return f"buyhold_{self.symbol}"

    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        return [dates[0]] if dates else []

    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        return {self.symbol: 1.0}


class FixedWeights(Strategy):
    """Hold fixed target weights, re-normalized at each month end.

    Also rebalances on the first session so the portfolio is invested from the
    start rather than sitting in cash until the first month end. Between
    rebalances the weights drift with relative performance.
    """

    def __init__(self, weights: dict[str, float] | None = None, name: str = "fixed_weights"):
        self._weights = dict(weights) if weights else {"SPY": 0.6, "IEF": 0.4}
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
        if not dates:
            return []
        return sorted({dates[0], *month_end_sessions(dates)})

    def target_weights(
        self, window: pd.DataFrame, current_date: pd.Timestamp
    ) -> dict[str, float]:
        return dict(self._weights)


__all__ = ["Strategy", "BuyAndHold", "FixedWeights", "month_end_sessions"]
