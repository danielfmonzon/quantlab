"""Data ingestion, storage, calendar, and validation for quantlab."""

from __future__ import annotations

# Canonical EOD schema. Every ingested/stored frame uses exactly these columns
# in this order. ``date`` is a tz-naive datetime64[ns] normalized to midnight.
CANONICAL_COLUMNS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "adj_volume",
    "dividend",
    "split_factor",
)

# Numeric (non-date) canonical columns.
NUMERIC_COLUMNS: tuple[str, ...] = CANONICAL_COLUMNS[1:]

# Price columns that must always be strictly positive.
PRICE_COLUMNS: tuple[str, ...] = (
    "open",
    "high",
    "low",
    "close",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
)


class DataError(Exception):
    """Raised when fetched or stored data violates the canonical schema."""


__all__ = [
    "CANONICAL_COLUMNS",
    "NUMERIC_COLUMNS",
    "PRICE_COLUMNS",
    "DataError",
]
