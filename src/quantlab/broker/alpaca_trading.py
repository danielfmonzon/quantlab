"""Alpaca paper TRADING client (accounts, positions, orders).

Scope: the paper trading API only. ``base_url`` is supplied by the caller from
``Settings.ALPACA_BASE_URL`` (Batch-1 gate: paper endpoint only), so no live
endpoint is reachable from here.

Security posture: credentials are sent ONLY in the ``APCA-API-KEY-ID`` and
``APCA-API-SECRET-KEY`` headers — never in a URL, query string, body, or log.

Idempotency: :meth:`submit_order` sends a caller-chosen ``client_order_id``. If
Alpaca rejects it as a duplicate, we fetch and return the pre-existing order with
``was_duplicate=True`` — so re-submitting the same logical order is a safe no-op.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quantlab.broker.assets import asset_class, to_alpaca_symbol, to_canonical_symbol
from quantlab.constants import ALPACA_PAPER_BASE_URL
from quantlab.data import DataError


class TradingError(DataError):
    """A permanent (non-retryable) trading API failure; carries the HTTP status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class _RetryableError(Exception):
    """Transient failure (429 / 5xx / network) that warrants a retry."""


class AccountInfo(BaseModel):
    """Subset of the Alpaca account object used by the paper runner."""

    model_config = ConfigDict(extra="ignore")

    equity: float
    cash: float
    currency: str
    account_blocked: bool
    trading_blocked: bool


class Position(BaseModel):
    """An open position."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float


class OrderInfo(BaseModel):
    """A submitted (or looked-up) order."""

    model_config = ConfigDict(extra="ignore")

    id: str
    client_order_id: str
    symbol: str
    side: str
    notional: float | None
    status: str
    submitted_at: datetime | None
    was_duplicate: bool = False


class AlpacaTradingClient:
    """Paper trading client mirroring the data client's auth + retry conventions.

    Args:
        api_key: Alpaca key id (header ``APCA-API-KEY-ID``).
        secret_key: Alpaca secret (header ``APCA-API-SECRET-KEY``).
        base_url: paper trading base URL from ``Settings.ALPACA_BASE_URL``.
        session: optional injected ``requests.Session`` (tests).
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: str = ALPACA_PAPER_BASE_URL,
        session: requests.Session | None = None,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        timeout: float = 30.0,
    ):
        if not api_key or not secret_key:
            raise DataError("AlpacaTradingClient requires non-empty api_key and secret_key")
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._session = session if session is not None else requests.Session()
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        # Header-only auth: credentials never appear in a URL/query string/body.
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Accept": "application/json",
        }

    # -- HTTP with retry -----------------------------------------------------

    def _do_request(
        self, method: str, url: str, params: dict[str, str] | None, json_body: Any
    ) -> Any:
        try:
            resp = self._session.request(
                method, url, params=params, json=json_body,
                headers=self._headers, timeout=self._timeout,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise _RetryableError(f"network error contacting Alpaca: {exc}") from exc

        status = resp.status_code
        if status == 429 or 500 <= status < 600:
            raise _RetryableError(f"transient Alpaca response {status} for {url}")
        if status >= 400:
            raise TradingError(
                f"Alpaca {method} {url} failed with HTTP {status}: {_body_message(resp)}",
                status=status,
            )
        if status == 204:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _request(
        self, method: str, url: str,
        params: dict[str, str] | None = None, json_body: Any = None,
    ) -> Any:
        retryer = Retrying(
            retry=retry_if_exception_type(_RetryableError),
            wait=wait_exponential(multiplier=self._backoff_base, min=self._backoff_base, max=30),
            stop=stop_after_attempt(self._max_attempts),
            reraise=True,
        )
        return retryer(self._do_request, method, url, params, json_body)

    # -- Account / positions -------------------------------------------------

    def get_account(self) -> AccountInfo:
        payload = self._request("GET", f"{self._base_url}/v2/account")
        if not isinstance(payload, dict):
            raise DataError(f"Unexpected account payload: {type(payload)}")
        return AccountInfo(**payload)

    def get_positions(self) -> list[Position]:
        payload = self._request("GET", f"{self._base_url}/v2/positions")
        if not isinstance(payload, list):
            raise DataError(f"Unexpected positions payload: {type(payload)}")
        # Normalize crypto position symbols back to canonical form (BTC/USD ->
        # BTC-USD) so they match strategy target weights; equities are unchanged.
        out: list[Position] = []
        for p in payload:
            pos = Position(**p)
            canon = to_canonical_symbol(pos.symbol)
            out.append(pos if canon == pos.symbol else pos.model_copy(update={"symbol": canon}))
        return out

    # -- Orders --------------------------------------------------------------

    def submit_order(
        self, symbol: str, side: str, notional: float, client_order_id: str
    ) -> OrderInfo:
        """Submit a fractional market DAY order sized by ``notional`` (dollars).

        On a duplicate ``client_order_id`` Alpaca errors; we look up and return
        the existing order with ``was_duplicate=True`` (idempotent by design).

        Asset-class-aware: crypto orders use the slash symbol form and
        ``time_in_force="gtc"`` (Alpaca rejects "day" for crypto); equities keep
        the bare symbol and "day" exactly as before.
        """
        body = {
            "symbol": to_alpaca_symbol(symbol),
            "side": side,
            "type": "market",
            "time_in_force": "gtc" if asset_class(symbol) == "crypto" else "day",
            "notional": f"{notional:.2f}",
            "client_order_id": client_order_id,
        }
        try:
            payload = self._request("POST", f"{self._base_url}/v2/orders", json_body=body)
        except TradingError as submit_exc:
            existing = self._find_order_by_coid(client_order_id)
            if existing is not None:
                return existing.model_copy(update={"was_duplicate": True})
            raise submit_exc
        if not isinstance(payload, dict):
            raise DataError(f"Unexpected order payload: {type(payload)}")
        return _order_from_payload(payload)

    def _find_order_by_coid(self, client_order_id: str) -> OrderInfo | None:
        payload = self._request(
            "GET", f"{self._base_url}/v2/orders",
            params={
                "status": "all",
                "client_order_id": client_order_id,
                "limit": "500",
                "nested": "false",
            },
        )
        if not isinstance(payload, list):
            return None
        for d in payload:
            if isinstance(d, dict) and d.get("client_order_id") == client_order_id:
                return _order_from_payload(d)
        return None

    def get_orders(self, status: str = "all", after: date | None = None) -> list[OrderInfo]:
        params: dict[str, str] = {"status": status, "limit": "500", "nested": "false"}
        if after is not None:
            params["after"] = after.isoformat()
        payload = self._request("GET", f"{self._base_url}/v2/orders", params=params)
        if not isinstance(payload, list):
            raise DataError(f"Unexpected orders payload: {type(payload)}")
        return [_order_from_payload(d) for d in payload if isinstance(d, dict)]

    def cancel_all_open(self) -> int:
        """Cancel every open order; return the number of cancellations reported."""
        payload = self._request("DELETE", f"{self._base_url}/v2/orders")
        if isinstance(payload, list):
            return len(payload)
        return 0


def _order_from_payload(d: dict[str, Any]) -> OrderInfo:
    notional_raw = d.get("notional")
    return OrderInfo(
        id=str(d["id"]),
        client_order_id=str(d.get("client_order_id", "")),
        symbol=to_canonical_symbol(str(d.get("symbol", ""))),
        side=str(d.get("side", "")),
        notional=float(notional_raw) if notional_raw is not None else None,
        status=str(d.get("status", "")),
        submitted_at=d.get("submitted_at"),
        was_duplicate=False,
    )


def _body_message(resp: requests.Response) -> str:
    """Best-effort short error message from a response WITHOUT leaking anything."""
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200] if getattr(resp, "text", "") else "<no body>"
    if isinstance(data, dict):
        return str(data.get("message") or data)
    return str(data)


__all__ = [
    "AlpacaTradingClient",
    "AccountInfo",
    "Position",
    "OrderInfo",
    "TradingError",
]
