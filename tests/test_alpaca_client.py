"""Tests for the Alpaca data client (all HTTP mocked; no real keys/live calls)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from quantlab.data import DataError
from quantlab.data.alpaca_client import ALPACA_BAR_COLUMNS, AlpacaDataClient, ClockInfo

FAKE_KEY_ID = "AKFAKEKEYID00000SECRET"
FAKE_SECRET = "fakesecret-never-in-any-url-or-log"


def _bar(day: str, close: float) -> dict[str, Any]:
    return {"t": f"{day}T05:00:00Z", "o": close - 1, "h": close + 1,
            "l": close - 2, "c": close, "v": 12345, "n": 100, "vw": close}


PAGE1 = {
    "bars": [_bar("2024-01-02", 470.0), _bar("2024-01-03", 471.0)],
    "symbol": "SPY",
    "next_page_token": "PAGE2TOKEN",
}
PAGE2 = {
    "bars": [_bar("2024-01-04", 472.0)],
    "symbol": "SPY",
    "next_page_token": None,
}
SINGLE = {"bars": [_bar("2024-01-02", 470.0)], "symbol": "SPY", "next_page_token": None}

CLOCK_PAYLOAD = {
    "timestamp": "2026-07-08T12:00:00Z",
    "is_open": True,
    "next_open": "2026-07-09T13:30:00Z",
    "next_close": "2026-07-08T20:00:00Z",
}


class FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: Any = None, headers: Any = None, timeout: Any = None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self._responses.pop(0)


def _client(session: FakeSession) -> AlpacaDataClient:
    return AlpacaDataClient(FAKE_KEY_ID, FAKE_SECRET, session=session, backoff_base=0.0)


def test_parses_fixture_to_schema() -> None:
    session = FakeSession([FakeResponse(200, SINGLE)])
    df = _client(session).fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 1, 31))

    assert list(df.columns) == list(ALPACA_BAR_COLUMNS)
    assert len(df) == 1
    assert df["close"].tolist() == [470.0]
    assert str(df["date"].dtype) == "datetime64[ns]"
    assert df["date"].iloc[0].date() == date(2024, 1, 2)


def test_pagination_concatenates_two_pages() -> None:
    session = FakeSession([FakeResponse(200, PAGE1), FakeResponse(200, PAGE2)])
    df = _client(session).fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 1, 31))

    assert len(df) == 3
    assert df["date"].dt.day.tolist() == [2, 3, 4]
    # Second request must carry the page token from page 1.
    assert len(session.calls) == 2
    assert session.calls[0]["params"].get("page_token") is None
    assert session.calls[1]["params"].get("page_token") == "PAGE2TOKEN"


def test_auth_is_header_based_and_url_has_no_key() -> None:
    session = FakeSession([FakeResponse(200, SINGLE)])
    _client(session).fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 1, 31))

    assert session.calls
    for call in session.calls:
        blob = call["url"] + json.dumps(call["params"])
        assert FAKE_KEY_ID not in blob
        assert FAKE_SECRET not in blob
        assert call["headers"]["APCA-API-KEY-ID"] == FAKE_KEY_ID
        assert call["headers"]["APCA-API-SECRET-KEY"] == FAKE_SECRET


def test_retries_on_429_then_succeeds() -> None:
    session = FakeSession([FakeResponse(429, {"m": "slow down"}), FakeResponse(200, SINGLE)])
    df = _client(session).fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 1, 31))
    assert len(df) == 1
    assert len(session.calls) == 2


def test_raises_immediately_on_403_without_retry() -> None:
    session = FakeSession([FakeResponse(403, {"message": "forbidden"})])
    with pytest.raises(DataError, match="403"):
        _client(session).fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 1, 31))
    assert len(session.calls) == 1  # no retry on 4xx


def test_empty_bars_returns_empty_frame() -> None:
    session = FakeSession([FakeResponse(200, {"bars": None, "next_page_token": None})])
    df = _client(session).fetch_daily_bars("SPY", date(2024, 1, 1), date(2024, 1, 31))
    assert df.empty
    assert list(df.columns) == list(ALPACA_BAR_COLUMNS)


def test_fetch_clock_parses_model() -> None:
    session = FakeSession([FakeResponse(200, CLOCK_PAYLOAD)])
    clock = _client(session).fetch_clock()
    assert isinstance(clock, ClockInfo)
    assert clock.is_open is True
    # Clock must hit the paper trading base, never the data base.
    assert "paper-api.alpaca.markets" in session.calls[0]["url"]
    assert session.calls[0]["url"].endswith("/v2/clock")
