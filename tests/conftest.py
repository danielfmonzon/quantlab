"""Shared pytest fixtures for quantlab tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

import pandas as pd
import pytest

from quantlab.data import CANONICAL_COLUMNS

FrameFactory = Callable[..., pd.DataFrame]


@pytest.fixture
def make_frame() -> FrameFactory:
    """Return a builder producing a valid canonical EOD frame.

    Pass ``dates`` (a sequence of ``date``) plus any canonical column as a keyword
    to override its default column values, e.g. ``make_frame(dates, close=[...])``.
    """

    def _make(dates: Sequence[date], **overrides: object) -> pd.DataFrame:
        n = len(dates)
        data: dict[str, object] = {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000] * n,
            "adj_open": [100.0] * n,
            "adj_high": [101.0] * n,
            "adj_low": [99.0] * n,
            "adj_close": [100.5] * n,
            "adj_volume": [1000] * n,
            "dividend": [0.0] * n,
            "split_factor": [1.0] * n,
        }
        data.update(overrides)
        frame = pd.DataFrame({"date": pd.to_datetime(list(dates)), **data})
        return frame[list(CANONICAL_COLUMNS)]

    return _make
