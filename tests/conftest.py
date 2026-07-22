"""Shared pytest fixtures for quantlab tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quantlab.data import CANONICAL_COLUMNS
from quantlab.reporting import alerts as alerts_module

FrameFactory = Callable[..., pd.DataFrame]

# Env vars that, when all present, activate the real SMTP EmailChannel.
_EMAIL_ENV_VARS = (
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "ALERT_EMAIL_TO",
)


@pytest.fixture(autouse=True)
def isolate_alert_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Redirect ALL alert output to ``tmp_path`` for every test in the suite.

    Autouse and unconditional. Two things are neutralised:

    * ``alerts.ALERTS_JSONL`` — ``FileChannel`` resolves this at send time, so
      any test that reaches real ``dispatch`` writes here instead of the
      production ``reports/alerts/alerts.jsonl``.
    * the SMTP env vars — a developer with a configured ``.env`` exported into
      their shell would otherwise have the test suite send REAL alert emails.

    This exists because the suite silently appended ~50 fixture alerts to the
    production log on 2026-07-22, corrupting the weekly review's ops stats.
    """
    redirected = tmp_path / "alerts" / "alerts.jsonl"
    monkeypatch.setattr(alerts_module, "ALERTS_JSONL", redirected)
    for name in _EMAIL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield redirected


@pytest.fixture
def make_frame() -> FrameFactory:
    """Return a builder producing a valid canonical EOD frame.

    Pass ``dates`` (a sequence of ``date``) plus any canonical column as a keyword
    to override its default column values, e.g. ``make_frame(dates, close=[...])``.
    """

    def _make(dates: Sequence[date], **overrides: object) -> pd.DataFrame:
        n = len(dates)
        data: dict[str, object] = {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000] * n,
            "adj_open": [100.0] * n,
            "adj_high": [101.0] * n,
            "adj_low": [99.0] * n,
            "adj_close": [100.5] * n,
            "adj_volume": [1000] * n,
            "dividend": [0.0] * n,
            "split_factor": [1.0] * n,
        }
        data.update(overrides)
        frame = pd.DataFrame({"date": pd.to_datetime(list(dates)), **data})
        return frame[list(CANONICAL_COLUMNS)]

    return _make
