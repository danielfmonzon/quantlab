"""Alpaca paper TRADING client tests (all HTTP mocked; no keys/live calls)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from quantlab.broker.alpaca_trading import (
    AccountInfo,
    AlpacaTradingClient,
    OrderInfo,
    Position,
    TradingError,
)

FAKE_KEY_ID = "AKFAKETRADEKEYID0000000"
FAKE_SECRET = "fakesecret-never-in-any-url-or-log-trade"

ACCOUNT = {
    "equity": "100000.55", "cash": "25000.25", "currency": "USD",
    "account_blocked": False, "trading_blocked": False, "id": "acct-1",
}
POSITIONS = [
    {"symbol": "SPY", "qty": "10.5", "market_value": "5250.00", "avg_entry_price": "500.00"},
    {"symbol": "IEF", "qty": "3", "market_value": "285.00", "avg_entry_price": "95.00"},
]
ORDER = {
    "id": "order-abc", "client_order_id": "ql-voltarget-20260709-SPY-buy",
    "symbol": "SPY", "side": "buy", "notional": "500.00",
    "status": "accepted", "submitted_at": "2026-07-09T13:31:00Z",
}


class FakeResponse:
    def __init__(self, status_code: int, payload: Any, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, params: Any = None, json: Any = None,
                headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "params": params or {},
                           "json": json, "headers": headers or {}})
        return self._responses.pop(0)


def _client(session: FakeSession) -> AlpacaTradingClient:
    return AlpacaTradingClient(FAKE_KEY_ID, FAKE_SECRET, session=session, backoff_base=0.0)


def test_parses_account_fixture() -> None:
    account = _client(FakeSession([FakeResponse(200, ACCOUNT)])).get_account()
    assert isinstance(account, AccountInfo)
    assert account.equity == pytest.approx(100000.55)
    assert account.cash == pytest.approx(25000.25)
    assert account.currency == "USD"
    assert account.account_blocked is False and account.trading_blocked is False


def test_parses_positions_fixture() -> None:
    positions = _client(FakeSession([FakeResponse(200, POSITIONS)])).get_positions()
    assert [p.symbol for p in positions] == ["SPY", "IEF"]
    assert isinstance(positions[0], Position)
    assert positions[0].market_value == pytest.approx(5250.0)


def test_submit_order_parses_and_posts_market_day() -> None:
    session = FakeSession([FakeResponse(200, ORDER)])
    order = _client(session).submit_order("SPY", "buy", 500.0, ORDER["client_order_id"])
    assert isinstance(order, OrderInfo)
    assert order.id == "order-abc"
    assert order.was_duplicate is False
    body = session.calls[0]["json"]
    assert session.calls[0]["method"] == "POST"
    assert body["type"] == "market" and body["time_in_force"] == "day"
    assert body["notional"] == "500.00" and body["side"] == "buy"


def test_no_key_in_url_or_body_only_in_headers() -> None:
    session = FakeSession([FakeResponse(200, ACCOUNT)])
    _client(session).get_account()
    for call in session.calls:
        blob = call["url"] + json.dumps(call["params"]) + json.dumps(call["json"])
        assert FAKE_KEY_ID not in blob
        assert FAKE_SECRET not in blob
        assert call["headers"]["APCA-API-KEY-ID"] == FAKE_KEY_ID
        assert call["headers"]["APCA-API-SECRET-KEY"] == FAKE_SECRET


def test_duplicate_client_order_id_returns_existing_marked_duplicate() -> None:
    # POST rejected (duplicate), then GET lookup returns the pre-existing order.
    session = FakeSession([
        FakeResponse(422, {"message": "client_order_id must be unique"}),
        FakeResponse(200, [ORDER]),
    ])
    order = _client(session).submit_order("SPY", "buy", 500.0, ORDER["client_order_id"])
    assert order.was_duplicate is True
    assert order.id == "order-abc"
    assert session.calls[0]["method"] == "POST"
    assert session.calls[1]["method"] == "GET"


def test_submit_reraises_when_no_existing_order_found() -> None:
    session = FakeSession([
        FakeResponse(422, {"message": "some other rejection"}),
        FakeResponse(200, []),  # lookup finds nothing
    ])
    with pytest.raises(TradingError):
        _client(session).submit_order("SPY", "buy", 500.0, "ql-x")


def test_403_raises_without_retry() -> None:
    session = FakeSession([FakeResponse(403, {"message": "forbidden"})])
    with pytest.raises(TradingError, match="403"):
        _client(session).get_account()
    assert len(session.calls) == 1  # 4xx is permanent: no retry


def test_cancel_all_open_counts_cancellations() -> None:
    session = FakeSession([FakeResponse(207, [{"id": "a", "status": 200},
                                              {"id": "b", "status": 200}])])
    assert _client(session).cancel_all_open() == 2
