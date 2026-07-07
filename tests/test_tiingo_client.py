"""Tests for the Tiingo client (all HTTP mocked; no real keys, no live calls)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from quantlab.data import CANONICAL_COLUMNS, DataError
from quantlab.data.tiingo_client import TiingoClient

FAKE_KEY = "abcd1234-secret-token-never-log"

META_PAYLOAD = {
    "ticker": "SPY",
    "name": "SPDR S&P 500 ETF",
    "startDate": "1993-01-29",
    "endDate": "2024-01-05",
}

PRICES_PAYLOAD = [
    {
        "date": "2024-01-04T00:00:00.000Z",
        "open": 470.0, "high": 475.0, "low": 469.0, "close": 474.0, "volume": 1000000,
        "adjOpen": 469.5, "adjHigh": 474.5, "adjLow": 468.5, "adjClose": 473.5,
        "adjVolume": 1000000, "divCash": 0.0, "splitFactor": 1.0,
    },
    {
        "date": "2024-01-05T00:00:00.000Z",
        "open": 474.0, "high": 478.0, "low": 473.0, "close": 477.0, "volume": 1100000,
        "adjOpen": 473.5, "adjHigh": 477.5, "adjLow": 472.5, "adjClose": 476.5,
        "adjVolume": 1100000, "divCash": 0.0, "splitFactor": 1.0,
    },
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


def _client(session: FakeSession) -> TiingoClient:
    return TiingoClient(FAKE_KEY, session=session, rate_limit_s=0.0, backoff_base=0.0)


def test_parses_fixture_to_canonical_schema() -> None:
    session = FakeSession([FakeResponse(200, META_PAYLOAD), FakeResponse(200, PRICES_PAYLOAD)])
    df = _client(session).fetch("SPY", date(2000, 1, 1))

    assert list(df.columns) == list(CANONICAL_COLUMNS)
    assert len(df) == 2
    assert df["adj_close"].tolist() == [473.5, 476.5]
    assert df["dividend"].tolist() == [0.0, 0.0]
    # date is tz-naive datetime64
    assert str(df["date"].dtype) == "datetime64[ns]"
    assert df["date"].iloc[0].date() == date(2024, 1, 4)


def test_auth_is_header_based_and_url_has_no_key() -> None:
    session = FakeSession([FakeResponse(200, META_PAYLOAD), FakeResponse(200, PRICES_PAYLOAD)])
    _client(session).fetch("SPY", date(2000, 1, 1))

    assert session.calls, "expected at least one HTTP call"
    for call in session.calls:
        # Key must never appear in the URL or query params.
        assert FAKE_KEY not in call["url"]
        assert FAKE_KEY not in json.dumps(call["params"])
        assert "token" not in call["url"].lower()
        assert "token" not in json.dumps(call["params"]).lower()
        # Key is carried only in the Authorization header, as "Token <key>".
        assert call["headers"]["Authorization"] == f"Token {FAKE_KEY}"


def test_retries_on_429_then_succeeds() -> None:
    session = FakeSession(
        [
            FakeResponse(200, META_PAYLOAD),  # metadata succeeds
            FakeResponse(429, {"detail": "rate limited"}),  # prices: transient
            FakeResponse(200, PRICES_PAYLOAD),  # prices: retry succeeds
        ]
    )
    df = _client(session).fetch("SPY", date(2000, 1, 1))
    assert len(df) == 2
    # metadata (1) + prices attempt 1 (429) + prices attempt 2 (200) == 3 calls
    assert len(session.calls) == 3


def test_raises_immediately_on_404_without_retry() -> None:
    session = FakeSession([FakeResponse(200, META_PAYLOAD), FakeResponse(404, {"detail": "no"})])
    with pytest.raises(DataError, match="404"):
        _client(session).fetch("SPY", date(2000, 1, 1))
    # metadata (1) + a single prices attempt (404, no retry) == 2 calls
    assert len(session.calls) == 2


def test_missing_price_fields_raise_data_error() -> None:
    broken = [{"date": "2024-01-04T00:00:00.000Z", "open": 1.0}]  # missing most fields
    session = FakeSession([FakeResponse(200, META_PAYLOAD), FakeResponse(200, broken)])
    with pytest.raises(DataError, match="missing fields"):
        _client(session).fetch("SPY", date(2000, 1, 1))


def test_inception_clamps_requested_start() -> None:
    session = FakeSession([FakeResponse(200, META_PAYLOAD), FakeResponse(200, PRICES_PAYLOAD)])
    _client(session).fetch("SPY", date(1980, 1, 1))
    prices_call = session.calls[1]
    # requested 1980 but inception is 1993 -> effective startDate must be clamped.
    assert prices_call["params"]["startDate"] == "1993-01-29"
