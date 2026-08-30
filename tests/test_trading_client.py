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
    _numeric,
    _order_from_payload,
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


# --------------------------------------------------------------------------- #
# Fill evidence must never be able to fail an order read (PROP-5 amendments)  #
# --------------------------------------------------------------------------- #

def _order_payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "order-abc", "client_order_id": "ql-x", "symbol": "BTC/USD",
        "side": "sell", "notional": "70218.29", "status": "filled",
        "submitted_at": "2026-08-22T16:24:19.346526Z",
        "filled_qty": "0.921208", "filled_avg_price": "77540.06",
        "filled_at": "2026-08-22T16:24:21.000000Z",
    }
    base.update(over)
    return base


def test_an_unparseable_filled_at_yields_none_and_still_parses() -> None:
    """`filled_at="garbage"` must not raise. Construction failing here aborts a run.

    The poll that reads these fields stands between submitting sells and submitting the
    buys those sells fund. A ValidationError there does not lose a timestamp -- it strands
    the account half-rebalanced. Unknown, not fatal.
    """
    order = _order_from_payload(_order_payload(filled_at="garbage"))

    assert order.filled_at is None
    # ...and nothing else about the order was disturbed by the bad field.
    assert order.status == "filled"
    assert order.filled_qty == pytest.approx(0.921208)
    assert order.filled_avg_price == pytest.approx(77540.06)


@pytest.mark.parametrize(
    "value",
    ["garbage", "", "  ", "2026-13-45T99:99:99Z", [], {}, object(), float("nan")],
)
def test_no_filled_at_value_can_raise(value: Any) -> None:
    """Whatever arrives in that field, the order parses and the field reads None."""
    order = _order_from_payload(_order_payload(filled_at=value))
    assert order.filled_at is None


def test_a_good_filled_at_is_unchanged_by_the_tolerance() -> None:
    """Tolerance may only widen what is accepted, never alter a value that was fine."""
    order = _order_from_payload(_order_payload())
    assert order.filled_at is not None
    assert order.filled_at.year == 2026
    assert order.filled_at.month == 8
    assert order.filled_at.day == 22


@pytest.mark.parametrize("value", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_numeric_rejects_non_finite_strings(value: str) -> None:
    """`float("nan")` and `float("inf")` both SUCCEED, so they had to be excluded here.

    Without this, "unparseable -> None" was not literally true, and a nan reaching
    `markphase.fill_vs_mark_bps` -- which sums filled_qty x filled_avg_price across a
    window -- turns a whole week's attribution into nan while still type-checking as a
    float. A missing figure has to read as missing.
    """
    assert _numeric(value) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_numeric_rejects_non_finite_floats(value: float) -> None:
    assert _numeric(value) is None


def test_non_finite_fill_fields_reach_the_order_as_none() -> None:
    """End to end: a nan quantity and an inf price both land as None, not as nan/inf."""
    order = _order_from_payload(_order_payload(filled_qty="nan", filled_avg_price="inf"))
    assert order.filled_qty is None
    assert order.filled_avg_price is None


def test_numeric_still_parses_the_ordinary_decimal_strings() -> None:
    """The teeth: the rejections above must not have broken the normal case."""
    assert _numeric("0.6284") == pytest.approx(0.6284)
    assert _numeric("77540.06") == pytest.approx(77540.06)
    assert _numeric(0) == 0.0
    assert _numeric(None) is None
    assert _numeric("") is None
    assert _numeric(True) is None          # a bool is not a quantity


def test_constructing_an_order_directly_cannot_fail_on_the_three_fields() -> None:
    """The guarantee is on the MODEL, so it holds for every construction path.

    `_order_from_payload` is not the only way an OrderInfo comes into being, and a future
    caller building one from something other than an Alpaca payload inherits the same
    protection rather than rediscovering the need for it.
    """
    order = OrderInfo(
        id="x", client_order_id="c", symbol="S", side="buy", notional=None,
        status="new", submitted_at=None,
        filled_qty="garbage", filled_avg_price=[], filled_at=object(),
    )
    assert order.filled_qty is None
    assert order.filled_avg_price is None
    assert order.filled_at is None
