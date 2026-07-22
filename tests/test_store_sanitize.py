"""Tests for symbol -> parquet-filename sanitization.

Guarantees: bare equity tickers keep their exact legacy filenames, while
slash/dash symbols (crypto) collapse to one filesystem-safe stem used by both
the write and read paths.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from quantlab.data.store import ParquetStore, sanitize_symbol


def test_sanitize_equity_ticker_unchanged() -> None:
    assert sanitize_symbol("SPY") == "SPY"
    assert sanitize_symbol("spy") == "SPY"  # only casing normalizes
    assert sanitize_symbol("TLT") == "TLT"


def test_sanitize_crypto_slash_and_dash_collapse() -> None:
    assert sanitize_symbol("BTC/USD") == "BTCUSD"
    assert sanitize_symbol("BTC-USD") == "BTCUSD"
    assert sanitize_symbol("eth-usd") == "ETHUSD"
    # The slash and dash forms of the same pair map to one stem.
    assert sanitize_symbol("BTC/USD") == sanitize_symbol("BTC-USD")


def test_equity_filenames_match_legacy(tmp_path: Path) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    assert store.path_for("SPY").name == "SPY.parquet"
    assert store._meta_path_for("SPY").name == "SPY.meta.json"


def test_crypto_write_read_round_trip(tmp_path: Path, make_frame) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    df = make_frame([date(2024, 1, 1), date(2024, 1, 2)])

    store.upsert("BTC-USD", df)

    # Written to the sanitized filename ...
    assert (tmp_path / "BTCUSD.parquet").exists()
    # ... and the read path sanitizes too, so the original symbol still loads.
    loaded = store.load("BTC-USD")
    assert len(loaded) == 2
    # The slash form resolves to the very same file.
    assert store.exists("BTC/USD")
    assert len(store.load("BTC/USD")) == 2


def test_crypto_metadata_round_trip(tmp_path: Path) -> None:
    store = ParquetStore(eod_dir=tmp_path)
    store.save_metadata("BTC-USD", date(2015, 7, 20), requested_start=date(2016, 1, 1))

    assert (tmp_path / "BTCUSD.meta.json").exists()
    meta = store.load_metadata("BTC/USD")  # slash form reads the same metadata
    assert meta is not None
    assert meta.inception_date == date(2015, 7, 20)
    assert meta.requested_start == date(2016, 1, 1)
