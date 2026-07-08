"""Single-source validation of an EOD frame against the canonical schema.

ERROR-level checks fail validation (``passed=False``); WARNING-level checks pass
but are flagged. Cross-source reconciliation is deferred to Batch 3.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
from pandas.api import types as ptypes
from pydantic import BaseModel

from quantlab.data import CANONICAL_COLUMNS, NUMERIC_COLUMNS, PRICE_COLUMNS
from quantlab.data.calendar import TradingCalendar

# A daily adjusted-close return with magnitude above this is flagged (warning).
_RETURN_WARN_THRESHOLD = 0.20


class ValidationReport(BaseModel):
    """Outcome of validating one symbol's frame."""

    symbol: str
    passed: bool
    errors: list[str] = []
    warnings: list[str] = []
    row_count: int = 0
    first_date: date | None = None
    last_date: date | None = None
    staleness_sessions: int = 0


def _fmt_dates(dates: list[date], limit: int = 10) -> str:
    shown = [d.isoformat() for d in dates[:limit]]
    if len(dates) > limit:
        shown.append(f"... (+{len(dates) - limit} more)")
    return ", ".join(shown)


def staleness_sessions(calendar: TradingCalendar, last_date: date, now: datetime) -> int:
    """Number of completed NYSE sessions between ``last_date`` and now.

    0 means ``last_date`` is the last completed session (fresh). Shared by
    :func:`validate` and the health preflight so both agree on "how stale".
    """
    lcs = calendar.last_completed_session(now)
    if lcs <= last_date:
        return 0
    return sum(1 for d in calendar.sessions_between(last_date, lcs) if d > last_date)


def validate(
    df: pd.DataFrame,
    symbol: str,
    inception_date: date | None,
    requested_start: date | None = None,
    now: datetime | None = None,
    calendar: TradingCalendar | None = None,
) -> ValidationReport:
    """Validate ``df`` for ``symbol``. See module docstring for the check list."""
    cal = calendar if calendar is not None else TradingCalendar()
    now = now if now is not None else datetime.now(UTC)

    errors: list[str] = []
    warnings: list[str] = []

    # -- Schema / dtype (fatal for further checks) ---------------------------
    actual = list(df.columns)
    if actual != list(CANONICAL_COLUMNS):
        errors.append(
            f"schema mismatch: expected columns {list(CANONICAL_COLUMNS)}, got {actual}"
        )
        return ValidationReport(
            symbol=symbol, passed=False, errors=errors, warnings=warnings,
            row_count=len(df),
        )

    if not ptypes.is_datetime64_any_dtype(df["date"]):
        errors.append(f"dtype mismatch: 'date' must be datetime, got {df['date'].dtype}")
    for col in NUMERIC_COLUMNS:
        if not ptypes.is_numeric_dtype(df[col]):
            errors.append(f"dtype mismatch: '{col}' must be numeric, got {df[col].dtype}")

    if errors:  # cannot trust the frame's contents past this point
        return ValidationReport(
            symbol=symbol, passed=False, errors=errors, warnings=warnings,
            row_count=len(df),
        )

    row_count = len(df)
    dates = [ts.date() for ts in pd.to_datetime(df["date"])]
    first_date = dates[0] if dates else None
    last_date = dates[-1] if dates else None

    if row_count == 0:
        errors.append("empty frame: no rows to validate")
        return ValidationReport(
            symbol=symbol, passed=False, errors=errors, warnings=warnings, row_count=0
        )

    # -- Date integrity ------------------------------------------------------
    date_series = pd.to_datetime(df["date"])
    if date_series.duplicated().any():
        dupes = sorted({d for d in dates if dates.count(d) > 1})
        errors.append(f"non-unique dates: {_fmt_dates(list(dupes))}")
    if not date_series.is_monotonic_increasing:
        errors.append("dates are not monotonically increasing")

    # -- Price / volume sanity ----------------------------------------------
    for col in PRICE_COLUMNS:
        bad = df[df[col] <= 0]
        if not bad.empty:
            bad_dates = [ts.date() for ts in pd.to_datetime(bad["date"])]
            errors.append(f"nonpositive '{col}' on: {_fmt_dates(bad_dates)}")

    hl = df[df["high"] < df["low"]]
    if not hl.empty:
        hl_dates = [ts.date() for ts in pd.to_datetime(hl["date"])]
        errors.append(f"high < low on: {_fmt_dates(hl_dates)}")

    max_oc = df[["open", "close"]].max(axis=1)
    h_bad = df[df["high"] < max_oc]
    if not h_bad.empty:
        errors.append(
            f"high < max(open, close) on: "
            f"{_fmt_dates([ts.date() for ts in pd.to_datetime(h_bad['date'])])}"
        )

    min_oc = df[["open", "close"]].min(axis=1)
    l_bad = df[df["low"] > min_oc]
    if not l_bad.empty:
        errors.append(
            f"low > min(open, close) on: "
            f"{_fmt_dates([ts.date() for ts in pd.to_datetime(l_bad['date'])])}"
        )

    for vol_col in ("volume", "adj_volume"):
        neg = df[df[vol_col] < 0]
        if not neg.empty:
            errors.append(
                f"negative '{vol_col}' on: "
                f"{_fmt_dates([ts.date() for ts in pd.to_datetime(neg['date'])])}"
            )

    # -- Missing NYSE sessions (coverage) -----------------------------------
    # (row_count > 0 here, so first_date and last_date are concrete dates.)
    coverage_start: date = inception_date if inception_date is not None else first_date  # type: ignore[assignment]
    if requested_start is not None and requested_start > coverage_start:
        coverage_start = requested_start
    assert last_date is not None
    expected = set(cal.sessions_between(coverage_start, last_date))
    present = set(dates)
    missing = sorted(expected - present)
    if missing:
        errors.append(
            f"missing {len(missing)} NYSE session(s) between "
            f"{coverage_start.isoformat()} and {last_date.isoformat()}: {_fmt_dates(missing)}"
        )

    # -- Staleness (warning) -------------------------------------------------
    staleness = staleness_sessions(cal, last_date, now)
    if staleness > 1:
        warnings.append(
            f"stale: {staleness} completed session(s) behind the last NYSE close"
        )

    # -- Large daily returns (warning) --------------------------------------
    adj_close = pd.to_numeric(df["adj_close"], errors="coerce")
    returns = adj_close.pct_change()
    big = df[returns.abs() > _RETURN_WARN_THRESHOLD]
    if not big.empty:
        big_dates = [ts.date() for ts in pd.to_datetime(big["date"])]
        warnings.append(f"abs daily adj_close return > 20% on: {_fmt_dates(big_dates)}")

    # -- Zero-volume days (warning) -----------------------------------------
    zero_vol = df[df["volume"] == 0]
    if not zero_vol.empty:
        zv_dates = [ts.date() for ts in pd.to_datetime(zero_vol["date"])]
        warnings.append(f"zero-volume day(s) on: {_fmt_dates(zv_dates)}")

    return ValidationReport(
        symbol=symbol,
        passed=not errors,
        errors=errors,
        warnings=warnings,
        row_count=row_count,
        first_date=first_date,
        last_date=last_date,
        staleness_sessions=staleness,
    )


__all__ = ["ValidationReport", "staleness_sessions", "validate"]
