"""Tests for the Coinbase candle client (all HTTP mocked; no network)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from quantlab.data import CANONICAL_COLUMNS, DataError
from quantlab.data.coinbase_client import _MAX_CANDLES, CoinbaseClient

# Coinbase rows are [time, low, high, open, close, volume] — deliberately with
# low/high BEFORE open/close so the mapper's column ordering is exercised.
# Unix seconds: 2024-01-01 = 1704067200, +86400 per day. Rows are newest-first.
CANDLES_NEWEST_FIRST: list[list[float]] = [
    [1704240000, 43.0, 46.0, 44.0, 45.0, 300.0],  # 2024-01-03
    [1704153600, 40.5, 43.5, 41.0, 42.0, 200.0],  # 2024-01-02
    [1704067200, 39.0, 42.0, 40.0, 41.0, 100.0],  # 2024-01-01
]


class FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Records every GET and returns queued responses in order."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: Any = None, headers: Any = None, timeout: Any = None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self._responses.pop(0)


def _client(session: FakeSession) -> CoinbaseClient:
    return CoinbaseClient(session=session, rate_limit_s=0.0, backoff_base=0.0)


def test_maps_unusual_row_order_into_canonical_schema() -> None:
    session = FakeSession([FakeResponse(200, CANDLES_NEWEST_FIRST)])
    df = _client(session).fetch_candles("BTC-USD", date(2024, 1, 1), date(2024, 1, 3))

    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 3
    # Sorted ascending (newest-first input reversed).
    assert [ts.date() for ts in df["date"]] == [
        date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)
    ]
    # Column mapping: open from idx 3, high idx 2, low idx 1, close idx 4, vol idx 5.
    assert df["open"].tolist() == [40.0, 41.0, 44.0]
    assert df["high"].tolist() == [42.0, 43.5, 46.0]
    assert df["low"].tolist() == [39.0, 40.5, 43.0]
    assert df["close"].tolist() == [41.0, 42.0, 45.0]
    assert df["volume"].tolist() == [100.0, 200.0, 300.0]
    # Crypto: adjusted == raw, no dividends/splits.
    assert df["adj_close"].tolist() == df["close"].tolist()
    assert df["adj_open"].tolist() == df["open"].tolist()
    assert df["dividend"].tolist() == [0.0, 0.0, 0.0]
    assert df["split_factor"].tolist() == [1.0, 1.0, 1.0]
    assert str(df["date"].dtype) == "datetime64[ns]"


def test_single_window_issues_one_request_with_daily_granularity() -> None:
    session = FakeSession([FakeResponse(200, CANDLES_NEWEST_FIRST)])
    _client(session).fetch_candles("BTC-USD", date(2024, 1, 1), date(2024, 1, 3))

    assert len(session.calls) == 1
    params = session.calls[0]["params"]
    assert params["granularity"] == "86400"
    assert params["start"] == "2024-01-01"
    assert params["end"] == "2024-01-03"
    assert "BTC-USD" in session.calls[0]["url"]


def test_empty_payload_returns_empty_canonical_frame() -> None:
    session = FakeSession([FakeResponse(200, [])])
    df = _client(session).fetch_candles("BTC-USD", date(2024, 1, 1), date(2024, 1, 3))
    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 0


def test_paginates_long_range_in_contiguous_windows() -> None:
    # A >300-day range must be split into multiple <=300-day windows that tile the
    # requested span contiguously with no gaps or overlaps.
    session = FakeSession([FakeResponse(200, []), FakeResponse(200, [])])
    start, end = date(2020, 1, 1), date(2020, 12, 31)  # 366 days -> 2 windows
    _client(session).fetch_candles("BTC-USD", start, end)

    windows = [
        (date.fromisoformat(c["params"]["start"]), date.fromisoformat(c["params"]["end"]))
        for c in session.calls
    ]
    assert len(windows) == 2
    assert windows[0][0] == start
    assert windows[-1][1] == end
    for (_s1, e1), (s2, _e2) in zip(windows, windows[1:], strict=False):
        assert s2 == e1 + timedelta(days=1)  # contiguous, no gap/overlap
    for s, e in windows:
        assert (e - s).days <= _MAX_CANDLES - 1  # <=300 candles per request


def test_retries_on_429_then_succeeds() -> None:
    session = FakeSession(
        [FakeResponse(429, {"message": "rate limited"}), FakeResponse(200, CANDLES_NEWEST_FIRST)]
    )
    df = _client(session).fetch_candles("BTC-USD", date(2024, 1, 1), date(2024, 1, 3))
    assert len(df) == 3
    assert len(session.calls) == 2  # one 429, one successful retry


def test_raises_immediately_on_400_without_retry() -> None:
    session = FakeSession([FakeResponse(400, {"message": "bad product"})])
    with pytest.raises(DataError, match="400"):
        _client(session).fetch_candles("NOPE-USD", date(2024, 1, 1), date(2024, 1, 3))
    assert len(session.calls) == 1  # 4xx (non-429) is permanent, no retry


def test_malformed_candle_row_raises() -> None:
    session = FakeSession([FakeResponse(200, [[1704067200, 39.0, 42.0]])])  # too few fields
    with pytest.raises(DataError, match="malformed"):
        _client(session).fetch_candles("BTC-USD", date(2024, 1, 1), date(2024, 1, 1))


def test_no_credentials_in_request() -> None:
    session = FakeSession([FakeResponse(200, CANDLES_NEWEST_FIRST)])
    _client(session).fetch_candles("BTC-USD", date(2024, 1, 1), date(2024, 1, 3))
    headers = session.calls[0]["headers"]
    assert "Authorization" not in headers
    assert "APCA-API-KEY-ID" not in headers
