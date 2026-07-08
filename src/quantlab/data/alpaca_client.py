"""Alpaca market-data client (DATA API + read-only clock).

Scope: only the market DATA API (daily bars) and the read-only ``/v2/clock``
endpoint are touched here. No trading endpoints (orders, positions) are used.

Security posture: credentials are sent ONLY in the ``APCA-API-KEY-ID`` and
``APCA-API-SECRET-KEY`` headers — never in a URL, query string, or log line.

Free-plan note: the free feed serves IEX data. IEX daily bars are built only
from trades on the IEX exchange, so closes can differ slightly from the
consolidated tape and IEX volume is a small fraction of consolidated volume.
Callers that reconcile against another source must compare closes (with a
tolerance) and must never compare volume across sources.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
from pydantic import BaseModel, ConfigDict
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quantlab.constants import ALPACA_PAPER_BASE_URL
from quantlab.data import DataError

ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"

# Schema returned by fetch_daily_bars (volume is intentionally single-source only).
ALPACA_BAR_COLUMNS: tuple[str, ...] = ("date", "open", "high", "low", "close", "volume")

# Alpaca bar field -> our column.
_BAR_FIELD_MAP: dict[str, str] = {
    "t": "date",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
}


class _RetryableError(Exception):
    """Transient failure (429 / 5xx / network) that warrants a retry."""


class ClockInfo(BaseModel):
    """Read-only market clock from the paper trading API ``/v2/clock``."""

    model_config = ConfigDict(extra="ignore")

    is_open: bool
    next_open: datetime
    next_close: datetime
    timestamp: datetime


class AlpacaDataClient:
    """Fetch daily bars from the Alpaca market DATA API and the paper clock.

    Args:
        api_key: Alpaca key id (header ``APCA-API-KEY-ID``).
        secret_key: Alpaca secret (header ``APCA-API-SECRET-KEY``).
        base_data_url: market data API base.
        base_trading_url: paper trading API base for the read-only clock. The
            Batch-1 safety gate restricts this to the paper endpoint.
        session: optional injected ``requests.Session`` (used by tests).
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_data_url: str = ALPACA_DATA_BASE_URL,
        base_trading_url: str = ALPACA_PAPER_BASE_URL,
        session: requests.Session | None = None,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        timeout: float = 30.0,
    ):
        if not api_key or not secret_key:
            raise DataError("AlpacaDataClient requires non-empty api_key and secret_key")
        self._api_key = api_key
        self._secret_key = secret_key
        self._base_data_url = base_data_url.rstrip("/")
        self._base_trading_url = base_trading_url.rstrip("/")
        self._session = session if session is not None else requests.Session()
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        # Header-only auth: credentials never appear in a URL/query string.
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Accept": "application/json",
        }

    # -- HTTP with retry -----------------------------------------------------

    def _do_request(self, url: str, params: dict[str, str]) -> Any:
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers, timeout=self._timeout
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise _RetryableError(f"network error contacting Alpaca: {exc}") from exc

        status = resp.status_code
        if status == 429 or 500 <= status < 600:
            raise _RetryableError(f"transient Alpaca response {status} for {url}")
        if status >= 400:
            # 4xx (other than 429), e.g. 403 forbidden: permanent, do not retry.
            raise DataError(f"Alpaca request failed with HTTP {status} for {url}")
        return resp.json()

    def _request(self, url: str, params: dict[str, str]) -> Any:
        retryer = Retrying(
            retry=retry_if_exception_type(_RetryableError),
            wait=wait_exponential(multiplier=self._backoff_base, min=self._backoff_base, max=30),
            stop=stop_after_attempt(self._max_attempts),
            reraise=True,
        )
        return retryer(self._do_request, url, params)

    # -- Public API ----------------------------------------------------------

    def fetch_daily_bars(
        self,
        symbol: str,
        start: date | str,
        end: date | str,
        adjustment: str = "all",
        feed: str = "iex",
    ) -> pd.DataFrame:
        """Fetch 1-day bars, following ``next_page_token`` until exhausted.

        Returns a DataFrame with columns
        ``date, open, high, low, close, volume`` (date tz-naive, normalized).
        """
        url = f"{self._base_data_url}/v2/stocks/{symbol}/bars"
        base_params = {
            "timeframe": "1Day",
            "start": _as_iso(start),
            "end": _as_iso(end),
            "adjustment": adjustment,
            "feed": feed,
            "limit": "10000",
        }

        all_bars: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = dict(base_params)
            if page_token:
                params["page_token"] = page_token
            payload = self._request(url, params)
            if not isinstance(payload, dict):
                raise DataError(f"Unexpected bars payload for {symbol}: {type(payload)}")
            bars = payload.get("bars") or []
            all_bars.extend(bars)
            page_token = payload.get("next_page_token")
            if not page_token:
                break

        return self._bars_to_frame(all_bars, symbol)

    def fetch_clock(self) -> ClockInfo:
        """Fetch the read-only market clock from the paper trading API."""
        url = f"{self._base_trading_url}/v2/clock"
        payload = self._request(url, {})
        if not isinstance(payload, dict):
            raise DataError(f"Unexpected clock payload: {type(payload)}")
        return ClockInfo(**payload)

    # -- Parsing -------------------------------------------------------------

    @staticmethod
    def _bars_to_frame(bars: list[dict[str, Any]], symbol: str) -> pd.DataFrame:
        if not bars:
            empty = pd.DataFrame({c: pd.Series(dtype="float64") for c in ALPACA_BAR_COLUMNS})
            empty["date"] = pd.Series(dtype="datetime64[ns]")
            return empty[list(ALPACA_BAR_COLUMNS)]

        raw = pd.DataFrame(bars)
        missing = [src for src in _BAR_FIELD_MAP if src not in raw.columns]
        if missing:
            joined = ", ".join(sorted(missing))
            raise DataError(f"Alpaca bars for {symbol} missing fields: {joined}")

        parsed = pd.to_datetime(raw["t"], utc=True).dt.tz_localize(None).dt.normalize()
        df = pd.DataFrame(
            {
                "date": parsed.astype("datetime64[ns]"),
                "open": pd.to_numeric(raw["o"], errors="coerce"),
                "high": pd.to_numeric(raw["h"], errors="coerce"),
                "low": pd.to_numeric(raw["l"], errors="coerce"),
                "close": pd.to_numeric(raw["c"], errors="coerce"),
                "volume": pd.to_numeric(raw["v"], errors="coerce"),
            }
        )
        df = df.sort_values("date").reset_index(drop=True)
        return df[list(ALPACA_BAR_COLUMNS)]


def _as_iso(value: date | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


__all__ = ["AlpacaDataClient", "ClockInfo", "ALPACA_BAR_COLUMNS"]
