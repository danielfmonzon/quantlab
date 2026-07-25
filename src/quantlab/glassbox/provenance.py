"""Classify a paper equity mark against the schedule that should have produced it.

The 2026-07-24 divergence diagnosis turned on this distinction. Paper marks are
not a uniform daily series: in the week studied, `crypto_voltarget`'s seven marks
were spaced 10.49h to 32.72h apart because only one of them fired on schedule —
three were catch-up runs and three were the leaked equity task. A chart of those
marks with no provenance flag looks like clean daily data and is not.

The heuristics are the diagnosis's, lifted into documented constants (see
``constants``). They classify by CLOCK TIME only; a mark is never re-dated or
dropped.
"""

from __future__ import annotations

from datetime import datetime

from quantlab.glassbox.constants import (
    CRYPTO_RUN_UTC_MINUTES,
    EQUITY_RUN_UTC_MINUTES,
    LEAKED_WINDOW_MINUTES,
    ON_SCHEDULE_TOLERANCE_MINUTES,
    PROVENANCE_CATCH_UP,
    PROVENANCE_LEAKED,
    PROVENANCE_ON_SCHEDULE,
)

_MINUTES_PER_DAY = 24 * 60


def _minutes_of_day(ts: datetime) -> int:
    return ts.hour * 60 + ts.minute


def _circular_distance(a: int, b: int) -> int:
    """Minutes between two times of day, wrapping at midnight.

    Wrapping matters: the crypto task fires at 00:30 UTC, so a mark at 23:55 is 35
    minutes early, not 1,405 minutes late.
    """
    raw = abs(a - b) % _MINUTES_PER_DAY
    return min(raw, _MINUTES_PER_DAY - raw)


def classify_mark(timestamp: datetime, asset_class: str) -> str:
    """Provenance of one equity-history mark: on_schedule / catch_up / leaked.

    Crypto marks are tested against the equity window FIRST: the crypto task runs
    at 00:30 UTC, so a crypto mark near 14:00 UTC cannot be a late crypto run — it
    is the equity task iterating crypto accounts (the leak fixed 2026-07-22).
    """
    minute = _minutes_of_day(timestamp)
    if asset_class == "crypto":
        if _circular_distance(minute, EQUITY_RUN_UTC_MINUTES) <= LEAKED_WINDOW_MINUTES:
            return PROVENANCE_LEAKED
        scheduled = CRYPTO_RUN_UTC_MINUTES
    else:
        scheduled = EQUITY_RUN_UTC_MINUTES

    if _circular_distance(minute, scheduled) <= ON_SCHEDULE_TOLERANCE_MINUTES:
        return PROVENANCE_ON_SCHEDULE
    return PROVENANCE_CATCH_UP


__all__ = ["classify_mark"]
