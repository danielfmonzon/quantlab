"""Tiingo EOD data client.

Security posture: the API key is sent ONLY in the ``Authorization: Token <key>``
HTTP header. It is never placed in a URL or query string, so it cannot leak into
logged request URLs. Request headers are never logged by this module.
"""

from __future__ import annotations

import time
from datetime import date
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

TIINGO_BASE_URL = "https://api.tiingo.com"

# Tiingo prices field -> canonical column.
_FIELD_MAP: dict[str, str] = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "adjOpen": "adj_open",
    "adjHigh": "adj_high",
    "adjLow": "adj_low",
    "adjClose": "adj_close",
    "adjVolume": "adj_volume",
    "divCash": "dividend",
    "splitFactor": "split_factor",
}


class _RetryableError(Exception):
    """Transient failure (429 / 5xx / network) that warrants a retry."""


class TiingoMetadata:
    """Symbol metadata: inception (startDate) and last-available (endDate)."""

    def __init__(self, ticker: str, start_date: date | None, end_date: date | None):
        self.ticker = ticker
        self.start_date = start_date
        self.end_date = end_date


class TiingoClient:
    """Fetch daily EOD history and symbol metadata from Tiingo.

    Args:
        api_key: Tiingo API token. Sent only via the Authorization header.
        session: optional injected ``requests.Session`` (used by tests).
        rate_limit_s: courtesy sleep after each symbol fetch (free-tier friendly).
        max_attempts: max tenacity attempts on transient errors.
        backoff_base: exponential-backoff multiplier (set 0 in tests).
    """

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        rate_limit_s: float = 1.2,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise DataError("TiingoClient requires a non-empty api_key")
        self._api_key = api_key
        self._session = session if session is not None else requests.Session()
        self._rate_limit_s = rate_limit_s
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        # Header-only auth: the key never appears in a URL/query string.
        return {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # -- HTTP with retry -----------------------------------------------------

    def _do_request(self, url: str, params: dict[str, str]) -> Any:
        try:
            resp = self._session.get(
                url, params=params, headers=self._headers, timeout=self._timeout
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            raise _RetryableError(f"network error contacting Tiingo: {exc}") from exc

        status = resp.status_code
        if status == 429 or 500 <= status < 600:
            raise _RetryableError(f"transient Tiingo response {status} for {url}")
        if status >= 400:
            # 4xx (other than 429): permanent client error, do not retry.
            raise DataError(f"Tiingo request failed with HTTP {status} for {url}")
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

    def get_metadata(self, ticker: str) -> TiingoMetadata:
        """Fetch symbol metadata (inception/end dates)."""
        url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker}"
        payload = self._request(url, params={})
        if not isinstance(payload, dict):
            raise DataError(f"Unexpected metadata payload for {ticker}: {type(payload)}")
        return TiingoMetadata(
            ticker=ticker,
            start_date=_parse_opt_date(payload.get("startDate")),
            end_date=_parse_opt_date(payload.get("endDate")),
        )

    def fetch(
        self,
        ticker: str,
        start: date,
        end: date | None = None,
    ) -> pd.DataFrame:
        """Fetch EOD prices as a canonical DataFrame.

        The effective start is clamped to ``max(start, inception)`` so requesting
        dates before the symbol began trading does not error.
        """
        metadata = self.get_metadata(ticker)
        effective_start = start
        if metadata.start_date is not None and metadata.start_date > start:
            effective_start = metadata.start_date

        params = {"startDate": effective_start.isoformat(), "format": "json"}
        if end is not None:
            params["endDate"] = end.isoformat()

        url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker}/prices"
        payload = self._request(url, params)
        df = self._to_canonical(payload, ticker)

        # Stash inception so callers (e.g. the ingest CLI) can persist it without
        # a second metadata call. attrs do not survive parquet round-trips.
        df.attrs["symbol"] = ticker
        df.attrs["inception_date"] = metadata.start_date

        if self._rate_limit_s:
            time.sleep(self._rate_limit_s)
        return df

    # -- Parsing -------------------------------------------------------------

    @staticmethod
    def _to_canonical(payload: Any, ticker: str) -> pd.DataFrame:
        if not isinstance(payload, list):
            raise DataError(f"Expected a list of price rows for {ticker}, got {type(payload)}")
        if not payload:
            # Empty but valid: return an empty canonical frame.
            empty = pd.DataFrame({c: pd.Series(dtype="float64") for c in CANONICAL_COLUMNS})
            empty["date"] = pd.Series(dtype="datetime64[ns]")
            return empty[list(CANONICAL_COLUMNS)]

        raw = pd.DataFrame(payload)
        missing_src = [src for src in _FIELD_MAP if src not in raw.columns]
        if missing_src:
            raise DataError(
                f"Tiingo response for {ticker} missing fields: {', '.join(sorted(missing_src))}"
            )

        df = raw.rename(columns=_FIELD_MAP)[list(CANONICAL_COLUMNS)].copy()
        # Pin to datetime64[ns] so the dtype is stable across pandas versions and
        # parquet round-trips (pandas >=3 otherwise picks [s]/[us]/[ms]).
        parsed = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize()
        df["date"] = parsed.astype("datetime64[ns]")
        for col in CANONICAL_COLUMNS[1:]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)

        missing_cols = [c for c in CANONICAL_COLUMNS if c not in df.columns]
        if missing_cols:
            raise DataError(f"Canonical columns missing after parse: {missing_cols}")
        return df


def _parse_opt_date(value: Any) -> date | None:
    if value in (None, "", "null"):
        return None
    return pd.to_datetime(value).date()


__all__ = ["TiingoClient", "TiingoMetadata"]
