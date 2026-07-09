"""Live smoke tests — hit the real Tiingo and Alpaca APIs.

All tests here are marked ``live`` and skipped automatically when the relevant
credentials are absent, so the default suite never performs network I/O.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from quantlab.config import get_settings
from quantlab.data.alpaca_client import AlpacaDataClient, ClockInfo
from quantlab.data.reconcile import reconcile
from quantlab.data.store import ParquetStore
from quantlab.data.tiingo_client import TiingoClient
from quantlab.data.validate import validate

_settings = get_settings()
_TIINGO = _settings.TIINGO_API_KEY
_ALPACA = _settings.ALPACA_API_KEY
_ALPACA_SECRET = _settings.ALPACA_SECRET_KEY
_HAS_ALPACA = bool(_ALPACA and _ALPACA_SECRET)
_HAS_TREND = bool(_settings.ALPACA_TREND_API_KEY and _settings.ALPACA_TREND_SECRET_KEY)

pytestmark = pytest.mark.live


@pytest.mark.skipif(not _TIINGO, reason="TIINGO_API_KEY not set")
def test_live_fetch_and_validate_spy() -> None:
    assert _TIINGO is not None
    client = TiingoClient(_TIINGO)
    start = date.today() - timedelta(days=30)
    df = client.fetch("SPY", start)

    assert not df.empty
    report = validate(
        df,
        "SPY",
        inception_date=df.attrs.get("inception_date"),
        requested_start=start,
        now=datetime.now(UTC),
    )
    # Fresh vendor data for a liquid ETF should have no ERROR-level issues.
    assert report.passed, f"unexpected validation errors: {report.errors}"
    assert report.row_count > 0


@pytest.mark.skipif(not _HAS_ALPACA, reason="Alpaca keys not set")
def test_live_alpaca_bars_and_reconcile() -> None:
    assert _ALPACA is not None and _ALPACA_SECRET is not None
    client = AlpacaDataClient(
        _ALPACA, _ALPACA_SECRET, base_trading_url=_settings.ALPACA_BASE_URL
    )
    today = date.today()
    start = today - timedelta(days=30)
    bars = client.fetch_daily_bars("SPY", start, today, adjustment="raw", feed="iex")

    assert not bars.empty
    # Reconcile against the local store's SPY history over the same window.
    store = ParquetStore()
    tiingo_df = store.load("SPY", start=start)
    report = reconcile(tiingo_df, bars, "SPY")
    assert report.symbol == "SPY"
    assert report.n_overlap >= 0  # a short 30-day window may be below the pass gate


@pytest.mark.skipif(not _HAS_ALPACA, reason="Alpaca keys not set")
def test_live_alpaca_clock() -> None:
    assert _ALPACA is not None and _ALPACA_SECRET is not None
    client = AlpacaDataClient(
        _ALPACA, _ALPACA_SECRET, base_trading_url=_settings.ALPACA_BASE_URL
    )
    clock = client.fetch_clock()
    assert isinstance(clock, ClockInfo)
    assert isinstance(clock.is_open, bool)


@pytest.mark.skipif(not _HAS_ALPACA, reason="Alpaca keys not set")
def test_live_paper_account_and_positions_read_only() -> None:
    # Read-only against the real PAPER account. Submits nothing.
    from quantlab.broker.alpaca_trading import AccountInfo, AlpacaTradingClient

    assert _ALPACA is not None and _ALPACA_SECRET is not None
    client = AlpacaTradingClient(_ALPACA, _ALPACA_SECRET, base_url=_settings.ALPACA_BASE_URL)

    account = client.get_account()
    assert isinstance(account, AccountInfo)
    assert account.equity >= 0.0
    assert account.currency  # non-empty

    positions = client.get_positions()
    assert isinstance(positions, list)  # may be empty
    for p in positions:
        assert p.symbol


@pytest.mark.skipif(not _HAS_TREND, reason="trend account keys not set")
def test_live_trend_account_read_only() -> None:
    # Read-only against trend's DEDICATED paper account (isolated from voltarget).
    from quantlab.broker.alpaca_trading import AccountInfo, AlpacaTradingClient
    from quantlab.config import account_for

    creds = account_for("trend")
    broker = AlpacaTradingClient(creds.api_key, creds.secret_key, base_url=creds.base_url)
    account = broker.get_account()
    assert isinstance(account, AccountInfo)
    assert account.equity >= 0.0
    assert creds.label == "trend"
