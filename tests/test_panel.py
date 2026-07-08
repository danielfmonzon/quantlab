"""Tests for price-panel construction."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from quantlab.backtest.panel import build_price_panel, returns_panel
from quantlab.data import DataError
from quantlab.data.store import ParquetStore


def _dates(*days: int) -> list[date]:
    return [date(2024, 1, d) for d in days]


def test_internal_gap_raises(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    # A is missing 2024-01-04 (an internal gap once B forces it into the union).
    store.upsert("A", make_frame(_dates(2, 3, 5), adj_close=[10.0, 11.0, 12.0]))
    store.upsert("B", make_frame(_dates(2, 3, 4, 5), adj_close=[20.0, 21.0, 22.0, 23.0]))
    with pytest.raises(DataError, match="internal gap"):
        build_price_panel(store, ["A", "B"])


def test_pre_inception_nan_allowed(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    # A starts late (2024-01-04); leading NaNs are fine.
    store.upsert("A", make_frame(_dates(4, 5), adj_close=[10.0, 11.0]))
    store.upsert("B", make_frame(_dates(2, 3, 4, 5), adj_close=[20.0, 21.0, 22.0, 23.0]))
    panel = build_price_panel(store, ["A", "B"])
    assert list(panel.columns) == ["A", "B"]
    assert len(panel) == 4
    assert np.isnan(panel["A"].iloc[0])  # pre-inception NaN
    assert not panel["A"].iloc[2:].isna().any()  # live region intact


def test_returns_panel_matches_pct_change(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    store.upsert("A", make_frame(_dates(2, 3, 4), adj_close=[100.0, 110.0, 99.0]))
    panel = build_price_panel(store, ["A"])
    rets = returns_panel(panel)
    assert np.isnan(rets["A"].iloc[0])
    assert rets["A"].iloc[1] == pytest.approx(0.10)
    assert rets["A"].iloc[2] == pytest.approx(99.0 / 110.0 - 1.0)


def test_start_end_filtering(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    store.upsert("A", make_frame(_dates(2, 3, 4, 5), adj_close=[10.0, 11.0, 12.0, 13.0]))
    panel = build_price_panel(store, ["A"], start=date(2024, 1, 3), end=date(2024, 1, 4))
    assert panel.index.min().date() == date(2024, 1, 3)
    assert panel.index.max().date() == date(2024, 1, 4)
