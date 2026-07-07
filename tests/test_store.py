"""Tests for the parquet store and its DuckDB view."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from quantlab.data.store import ParquetStore


def _dates(*days: int) -> list[date]:
    return [date(2024, 1, d) for d in days]


def test_upsert_is_idempotent(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    df = make_frame(_dates(2, 3, 4))

    first = store.upsert("SPY", df)
    second = store.upsert("SPY", df)  # same data again

    pd.testing.assert_frame_equal(first, second)
    assert len(second) == 3
    assert second["date"].is_unique


def test_upsert_merges_overlapping_ranges_new_wins(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    older = make_frame(_dates(1, 2, 3), close=[10.0, 20.0, 30.0])
    newer = make_frame(_dates(2, 3, 4), close=[200.0, 300.0, 400.0])

    store.upsert("SPY", older)
    merged = store.upsert("SPY", newer)

    assert merged["date"].dt.day.tolist() == [1, 2, 3, 4]
    close_by_day = dict(zip(merged["date"].dt.day, merged["close"], strict=True))
    assert close_by_day[1] == 10.0  # only in older
    assert close_by_day[2] == 200.0  # newer wins
    assert close_by_day[3] == 300.0  # newer wins
    assert close_by_day[4] == 400.0  # only in newer


def test_load_filters_by_date_range(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    store.upsert("SPY", make_frame(_dates(1, 2, 3, 4, 5)))

    subset = store.load("SPY", start=date(2024, 1, 2), end=date(2024, 1, 4))
    assert subset["date"].dt.day.tolist() == [2, 3, 4]


def test_duckdb_view_counts_across_two_symbols(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    store.upsert("SPY", make_frame(_dates(1, 2, 3)))
    store.upsert("QQQ", make_frame(_dates(1, 2)))

    con = store.duckdb_connection()
    try:
        total = con.execute("SELECT COUNT(*) FROM eod_prices").fetchone()[0]
        rows = con.execute(
            "SELECT symbol, COUNT(*) FROM eod_prices GROUP BY symbol ORDER BY symbol"
        ).fetchall()
    finally:
        con.close()

    assert total == 5
    assert dict(rows) == {"QQQ": 2, "SPY": 3}


def test_duckdb_view_empty_when_no_data(tmp_path: Path) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    con = store.duckdb_connection()
    try:
        count = con.execute("SELECT COUNT(*) FROM eod_prices").fetchone()[0]
    finally:
        con.close()
    assert count == 0


def test_metadata_round_trip(tmp_path: Path) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    store.save_metadata("SPY", date(1993, 1, 29), requested_start=date(2000, 1, 1))
    meta = store.load_metadata("SPY")
    assert meta is not None
    assert meta.inception_date == date(1993, 1, 29)
    assert meta.requested_start == date(2000, 1, 1)
    assert store.load_metadata("UNKNOWN") is None
