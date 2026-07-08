"""Price panel construction for backtesting.

A price panel is a DataFrame indexed by session date with one ``adj_close``
column per symbol. It is the outer-join (union) of every symbol's sessions, so a
late-inception symbol carries leading NaNs before it began trading. Leading NaNs
are allowed; an *internal* gap (a NaN after a symbol's first valid price) is a
data defect and fails loudly.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from quantlab.data import DataError
from quantlab.data.store import ParquetStore


def build_price_panel(
    store: ParquetStore,
    symbols: list[str],
    start: date | str | None = None,
    end: date | str | None = None,
) -> pd.DataFrame:
    """Build an adj_close price panel (union of sessions) for ``symbols``.

    Raises :class:`DataError` if any symbol has an internal gap (a NaN after its
    first valid date). Pre-inception leading NaNs are allowed.
    """
    if not symbols:
        raise DataError("build_price_panel requires at least one symbol")

    columns: dict[str, pd.Series] = {}
    for symbol in symbols:
        df = store.load(symbol)
        if df.empty:
            columns[symbol] = pd.Series(dtype="float64")
            continue
        series = df.set_index("date")["adj_close"]
        columns[symbol] = series

    panel = pd.DataFrame(columns).sort_index()
    if start is not None:
        panel = panel[panel.index >= pd.Timestamp(start)]
    if end is not None:
        panel = panel[panel.index <= pd.Timestamp(end)]
    panel.index.name = "date"

    _check_no_internal_gaps(panel)
    return panel


def _check_no_internal_gaps(panel: pd.DataFrame) -> None:
    for col in panel.columns:
        series = panel[col]
        first = series.first_valid_index()
        if first is None:
            continue  # all-NaN within the window: symbol simply never appears
        live = series.loc[first:]
        if live.isna().any():
            gaps = [ts.date().isoformat() for ts in live[live.isna()].index[:5]]
            raise DataError(
                f"internal gap in '{col}' after first valid date "
                f"{first.date().isoformat()}: {gaps}"
            )


def returns_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Daily simple returns per symbol: r_t = adj_close_t / adj_close_{t-1} - 1.

    The first row and any pre-inception rows are NaN (no prior price).
    """
    return panel.pct_change(fill_method=None)


__all__ = ["build_price_panel", "returns_panel"]
