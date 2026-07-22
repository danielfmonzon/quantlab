"""Crypto vs equity broker order semantics (all HTTP mocked; no keys/live calls).

Guards: crypto uses BTC/USD + time_in_force=gtc; equity order construction is
byte-identical to before; canonical<->Alpaca symbol round-trips; positions come
back in canonical form.
"""

from __future__ import annotations

from typing import Any

import yaml

from quantlab.broker.alpaca_trading import AlpacaTradingClient, Position
from quantlab.broker.assets import (
    CRYPTO_SYMBOLS,
    asset_class,
    to_alpaca_symbol,
    to_canonical_symbol,
)
from quantlab.constants import CRYPTO_UNIVERSE_YAML

FAKE_KEY_ID = "AKFAKETRADEKEYID0000000"
FAKE_SECRET = "fakesecret-never-in-any-url-or-log-trade"

EQUITY_ORDER = {
    "id": "order-eq", "client_order_id": "ql-voltarget-20260709-SPY-buy",
    "symbol": "SPY", "side": "buy", "notional": "500.00",
    "status": "accepted", "submitted_at": "2026-07-09T13:31:00Z",
}
CRYPTO_ORDER = {
    "id": "order-btc", "client_order_id": "ql-crypto_trend-20260711-BTC-USD-buy",
    "symbol": "BTC/USD", "side": "buy", "notional": "1000.00",
    "status": "accepted", "submitted_at": "2026-07-11T13:31:00Z",
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


# -- Symbol / asset-class helpers -------------------------------------------


def test_asset_class_from_explicit_registry() -> None:
    assert asset_class("BTC-USD") == "crypto"
    assert asset_class("ETH-USD") == "crypto"
    assert asset_class("BTC/USD") == "crypto"  # any spelling
    assert asset_class("SPY") == "us_equity"
    assert asset_class("IEF") == "us_equity"


def test_symbol_round_trip() -> None:
    assert to_alpaca_symbol("BTC-USD") == "BTC/USD"
    assert to_canonical_symbol("BTC/USD") == "BTC-USD"
    assert to_canonical_symbol("BTCUSD") == "BTC-USD"  # concatenated spelling
    assert to_canonical_symbol(to_alpaca_symbol("ETH-USD")) == "ETH-USD"
    # Equities are identity in both directions.
    assert to_alpaca_symbol("SPY") == "SPY"
    assert to_canonical_symbol("SPY") == "SPY"


def test_registry_matches_crypto_universe_yaml() -> None:
    entries = yaml.safe_load(CRYPTO_UNIVERSE_YAML.read_text(encoding="utf-8"))
    from_yaml = {e["symbol"] for e in entries if e["asset_class"] == "crypto"}
    assert CRYPTO_SYMBOLS == from_yaml  # no drift between registry and config


# -- Order construction -----------------------------------------------------


def test_equity_order_body_is_byte_identical_to_before() -> None:
    session = FakeSession([FakeResponse(200, EQUITY_ORDER)])
    _client(session).submit_order("SPY", "buy", 500.0, EQUITY_ORDER["client_order_id"])
    body = session.calls[0]["json"]
    assert body == {
        "symbol": "SPY",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "notional": "500.00",
        "client_order_id": EQUITY_ORDER["client_order_id"],
    }


def test_crypto_order_uses_slash_symbol_and_gtc() -> None:
    session = FakeSession([FakeResponse(200, CRYPTO_ORDER)])
    order = _client(session).submit_order(
        "BTC-USD", "buy", 1000.0, CRYPTO_ORDER["client_order_id"]
    )
    body = session.calls[0]["json"]
    assert body == {
        "symbol": "BTC/USD",              # slash form for the trading API
        "side": "buy",
        "type": "market",
        "time_in_force": "gtc",           # Alpaca rejects "day" for crypto
        "notional": "1000.00",            # notional market order, as before
        "client_order_id": CRYPTO_ORDER["client_order_id"],
    }
    # The parsed order symbol comes back canonical.
    assert order.symbol == "BTC-USD"


def test_crypto_position_symbol_normalized_to_canonical() -> None:
    payload = [
        {"symbol": "BTC/USD", "qty": "0.5", "market_value": "30000.00",
         "avg_entry_price": "60000.00"},
    ]
    positions = _client(FakeSession([FakeResponse(200, payload)])).get_positions()
    assert [p.symbol for p in positions] == ["BTC-USD"]
    assert isinstance(positions[0], Position)
    assert positions[0].market_value == 30000.0


def test_equity_positions_unchanged() -> None:
    payload = [
        {"symbol": "SPY", "qty": "10.5", "market_value": "5250.00", "avg_entry_price": "500.00"},
        {"symbol": "IEF", "qty": "3", "market_value": "285.00", "avg_entry_price": "95.00"},
    ]
    positions = _client(FakeSession([FakeResponse(200, payload)])).get_positions()
    assert [p.symbol for p in positions] == ["SPY", "IEF"]
    assert positions[0].market_value == 5250.0
