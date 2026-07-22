"""Coinbase Exchange daily-candle client (public endpoint, no API key).

Fetches daily OHLCV candles from the public Coinbase Exchange REST endpoint
``GET /products/{product_id}/candles`` and maps them into quantlab's canonical
EOD schema, so crypto history flows through the *same* parquet store as
equities. No credentials are used or sent — this is a public market-data
endpoint.

Endpoint facts this client handles:

* ``granularity=86400`` (daily) with ISO ``start``/``end`` params.
* At most **300 candles per request** — long ranges are paginated forward in
  <=300-day windows.
* Responses are ordered **newest-first**; rows are sorted ascending before use.
* Row layout is the unusual ``[time, low, high, open, close, volume]`` (note the
  low/high before open/close) — mapped carefully into the canonical columns.
* Public rate limit is ~3 req/s; we sleep ~0.34s between requests and retry
  429/5xx and network errors with exponential backoff.

Crypto has no corporate actions, so the adjusted columns equal the raw columns
and ``dividend`` / ``split_factor`` are 0.0 / 1.0.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import requests
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quantlab.data import CANONICAL_COLUMNS, DataError

COINBASE_BASE_URL = "https://api.exchange.coinbase.com"

# Daily candles; the public endpoint returns at most 300 candles per request.
_GRANULARITY_DAILY = 86400
_MAX_CANDLES = 300

# Public rate limit is ~3 requests/sec; ~0.34s between requests stays under it.
_RATE_LIMIT_S = 0.34

# Coinbase candle row layout (note the UNUSUAL order — low/high precede open/close):
#   [ time, low, high, open, close, volume ]
_IDX_TIME = 0
_IDX_LOW = 1
_IDX_HIGH = 2
_IDX_OPEN = 3
_IDX_CLOSE = 4
_IDX_VOLUME = 5


class _RetryableError(Exception):
    """Transient failure (429 / 5xx / network) that warrants a retry."""


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


class CoinbaseClient:
    """Fetch daily candles from the public Coinbase Exchange API.

    Args:
        session: optional injected ``requests.Session`` (used by tests).
        rate_limit_s: courtesy sleep after each request (set 0 in tests).
        max_attempts: max tenacity attempts on transient errors (default 6 ==
            one initial call plus five retries).
        backoff_base: exponential-backoff multiplier (set 0 in tests).
        timeout: per-request timeout in seconds.
    """

    def __init__(
        self,
        session: requests.Session | None = None,
        rate_limit_s: float = _RATE_LIMIT_S,
        max_attempts: int = 6,
        backoff_base: float = 1.0,
        timeout: float = 30.0,
    ):
        self._session = session if session is not None else requests.Session()
        self._rate_limit_s = rate_limit_s
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        # Public endpoint: no credentials. A User-Agent is polite and avoids some
        # edge-provider blocks; it carries nothing sensitive.
        return {"Accept": "application/json", "User-Agent": "quantlab/1.0"}

    # -- HTTP with retry -----------------------------------------------------

    def _do_request(self, url: str, params: dict[str, str]) -> Any:
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers, timeout=self._timeout
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise _RetryableError(f"network error contacting Coinbase: {exc}") from exc

        status = resp.status_code
        if status == 429 or 500 <= status < 600:
            raise _RetryableError(f"transient Coinbase response {status} for {url}")
        if status >= 400:
            # 4xx (other than 429): permanent client error, do not retry.
            raise DataError(f"Coinbase request failed with HTTP {status} for {url}")
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

    def fetch_candles(
        self,
        product_id: str,
        start: date | str,
        end: date | str | None = None,
    ) -> pd.DataFrame:
        """Fetch daily candles for ``product_id`` over [start, end] as a canonical frame.

        ``end`` defaults to today (UTC). The range is paginated forward in
        <=300-day windows to respect the per-request candle cap; all rows are
        concatenated, sorted ascending, and de-duplicated on date.
        """
        start_d = _as_date(start)
        end_d = _as_date(end) if end is not None else datetime.now(UTC).date()

        url = f"{COINBASE_BASE_URL}/products/{product_id}/candles"
        rows: list[list[Any]] = []
        win_start = start_d
        while win_start <= end_d:
            # Inclusive window of at most 300 daily candles.
            win_end = min(win_start + timedelta(days=_MAX_CANDLES - 1), end_d)
            payload = self._request(
                url,
                {
                    "granularity": str(_GRANULARITY_DAILY),
                    "start": win_start.isoformat(),
                    "end": win_end.isoformat(),
                },
            )
            if not isinstance(payload, list):
                raise DataError(
                    f"Unexpected candles payload for {product_id}: {type(payload)}"
                )
            rows.extend(payload)
            win_start = win_end + timedelta(days=1)
            if self._rate_limit_s:
                time.sleep(self._rate_limit_s)

        return self._to_canonical(rows, product_id)

    # -- Parsing -------------------------------------------------------------

    @staticmethod
    def _to_canonical(rows: list[list[Any]], product_id: str) -> pd.DataFrame:
        if not rows:
            empty = pd.DataFrame({c: pd.Series(dtype="float64") for c in CANONICAL_COLUMNS})
            empty["date"] = pd.Series(dtype="datetime64[ns]")
            return empty[list(CANONICAL_COLUMNS)]

        for row in rows:
            if len(row) < 6:
                raise DataError(f"malformed Coinbase candle for {product_id}: {row!r}")

        # Map the unusual [time, low, high, open, close, volume] layout explicitly.
        raw = pd.DataFrame(
            {
                "time": [r[_IDX_TIME] for r in rows],
                "open": [r[_IDX_OPEN] for r in rows],
                "high": [r[_IDX_HIGH] for r in rows],
                "low": [r[_IDX_LOW] for r in rows],
                "close": [r[_IDX_CLOSE] for r in rows],
                "volume": [r[_IDX_VOLUME] for r in rows],
            }
        )

        # Unix seconds -> tz-naive datetime64[ns] normalized to midnight (matches
        # the store's canonical date dtype).
        parsed = (
            pd.to_datetime(raw["time"], unit="s", utc=True).dt.tz_localize(None).dt.normalize()
        )
        df = pd.DataFrame(
            {
                "date": parsed.astype("datetime64[ns]"),
                "open": pd.to_numeric(raw["open"], errors="coerce"),
                "high": pd.to_numeric(raw["high"], errors="coerce"),
                "low": pd.to_numeric(raw["low"], errors="coerce"),
                "close": pd.to_numeric(raw["close"], errors="coerce"),
                "volume": pd.to_numeric(raw["volume"], errors="coerce"),
            }
        )

        # Crypto has no corporate actions: adjusted == raw, no dividends/splits.
        df["adj_open"] = df["open"]
        df["adj_high"] = df["high"]
        df["adj_low"] = df["low"]
        df["adj_close"] = df["close"]
        df["adj_volume"] = df["volume"]
        df["dividend"] = 0.0
        df["split_factor"] = 1.0

        # Candles arrive newest-first; sort ascending and drop any duplicate days.
        df = (
            df[list(CANONICAL_COLUMNS)]
            .drop_duplicates(subset="date", keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
        return df


__all__ = ["CoinbaseClient", "COINBASE_BASE_URL"]
