"""Live smoke test — hits the real Tiingo API.

Marked ``live`` and skipped automatically when TIINGO_API_KEY is absent, so the
default suite never performs network I/O.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from quantlab.config import get_settings
from quantlab.data.tiingo_client import TiingoClient
from quantlab.data.validate import validate

_API_KEY = get_settings().TIINGO_API_KEY

pytestmark = pytest.mark.live


@pytest.mark.skipif(not _API_KEY, reason="TIINGO_API_KEY not set")
def test_live_fetch_and_validate_spy() -> None:
    assert _API_KEY is not None
    client = TiingoClient(_API_KEY)
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
