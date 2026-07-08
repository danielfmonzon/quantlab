"""Cross-source reconciliation: Tiingo (consolidated tape) vs Alpaca (IEX feed).

What we compare and why:

* We compare **close prices only**, never volume. IEX volume is a small fraction
  of consolidated volume, so a volume comparison would always "mismatch" and is
  meaningless across these two sources.
* We compare **raw** closes on both sides. Alpaca's ``adjustment="all"`` bars are
  split/dividend-adjusted, so comparing them against Tiingo's *raw* close would
  spuriously diverge exactly on and after every corporate action. Callers must
  therefore fetch Alpaca bars with ``adjustment="raw"`` and this function
  compares them against Tiingo's raw ``close`` column.
* IEX closes can still differ slightly from the consolidated tape, so a mismatch
  is defined by a configurable **relative** tolerance (default 0.75%). The
  relative difference is measured against the Tiingo close (the consolidated
  reference).
* The free feed only carries ~7 years of history, so reconciliation runs strictly
  over the **overlapping** date window of the two frames.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel

# Reconciliation thresholds.
MIN_OVERLAP_SESSIONS = 20
MAX_MISMATCH_FRACTION = 0.02
MAX_ALIGNMENT_ASYMMETRY = 5


class Mismatch(BaseModel):
    """A single date where the two sources' closes differ beyond tolerance."""

    date: date
    tiingo_close: float
    alpaca_close: float
    rel_diff: float


class ReconcileReport(BaseModel):
    """Outcome of reconciling one symbol across the two sources."""

    symbol: str
    passed: bool
    overlap_start: date | None = None
    overlap_end: date | None = None
    n_overlap: int = 0
    n_mismatches: int = 0
    mismatches: list[Mismatch] = []
    dates_only_in_tiingo: list[date] = []
    dates_only_in_alpaca: list[date] = []
    errors: list[str] = []
    warnings: list[str] = []


def _close_map(df: pd.DataFrame, lo: date, hi: date) -> dict[date, float]:
    """Map of ``date -> close`` for rows within [lo, hi], dropping NaN closes."""
    sub = df[["date", "close"]].dropna(subset=["close"])
    out: dict[date, float] = {}
    for ts, close in zip(pd.to_datetime(sub["date"]), sub["close"], strict=True):
        d = ts.date()
        if lo <= d <= hi:
            out[d] = float(close)
    return out


def reconcile(
    tiingo_df: pd.DataFrame,
    alpaca_df: pd.DataFrame,
    symbol: str,
    tolerance: float = 0.0075,
) -> ReconcileReport:
    """Reconcile Tiingo raw closes against Alpaca raw closes over their overlap.

    ``alpaca_df`` must have been fetched with ``adjustment="raw"`` (see module
    docstring). See :data:`MIN_OVERLAP_SESSIONS`, :data:`MAX_MISMATCH_FRACTION`,
    and :data:`MAX_ALIGNMENT_ASYMMETRY` for the pass/fail rules.
    """
    errors: list[str] = []
    warnings: list[str] = []

    t = tiingo_df[["date", "close"]].dropna(subset=["close"])
    a = alpaca_df[["date", "close"]].dropna(subset=["close"])

    if t.empty or a.empty:
        errors.append("no overlapping data: one or both sources are empty")
        return ReconcileReport(symbol=symbol, passed=False, errors=errors, warnings=warnings)

    overlap_start = max(pd.to_datetime(t["date"]).min(), pd.to_datetime(a["date"]).min()).date()
    overlap_end = min(pd.to_datetime(t["date"]).max(), pd.to_datetime(a["date"]).max()).date()

    if overlap_start > overlap_end:
        errors.append("no overlapping window between the two sources")
        return ReconcileReport(
            symbol=symbol,
            passed=False,
            overlap_start=None,
            overlap_end=None,
            errors=errors,
            warnings=warnings,
        )

    t_map = _close_map(tiingo_df, overlap_start, overlap_end)
    a_map = _close_map(alpaca_df, overlap_start, overlap_end)

    common = sorted(set(t_map) & set(a_map))
    only_tiingo = sorted(set(t_map) - set(a_map))
    only_alpaca = sorted(set(a_map) - set(t_map))
    n_overlap = len(common)

    mismatches: list[Mismatch] = []
    for d in common:
        tc = t_map[d]
        ac = a_map[d]
        rel = abs(tc - ac) / abs(tc) if tc != 0 else float("inf")
        if rel > tolerance:
            mismatches.append(
                Mismatch(date=d, tiingo_close=tc, alpaca_close=ac, rel_diff=rel)
            )

    n_mismatches = len(mismatches)

    # -- Pass/fail rules -----------------------------------------------------
    if n_overlap < MIN_OVERLAP_SESSIONS:
        errors.append(
            f"overlap window has {n_overlap} common session(s) "
            f"(< {MIN_OVERLAP_SESSIONS} required)"
        )

    mismatch_fraction = (n_mismatches / n_overlap) if n_overlap else 1.0
    if n_overlap and mismatch_fraction > MAX_MISMATCH_FRACTION:
        errors.append(
            f"{n_mismatches}/{n_overlap} sessions "
            f"({mismatch_fraction:.2%}) mismatch beyond tolerance "
            f"{tolerance:.4%} (> {MAX_MISMATCH_FRACTION:.0%} allowed)"
        )

    if len(only_tiingo) > MAX_ALIGNMENT_ASYMMETRY:
        errors.append(
            f"{len(only_tiingo)} overlap dates only in Tiingo "
            f"(> {MAX_ALIGNMENT_ASYMMETRY} allowed)"
        )
    if len(only_alpaca) > MAX_ALIGNMENT_ASYMMETRY:
        errors.append(
            f"{len(only_alpaca)} overlap dates only in Alpaca "
            f"(> {MAX_ALIGNMENT_ASYMMETRY} allowed)"
        )

    # Mismatch details always surface as warnings (informational when passing).
    for m in mismatches:
        warnings.append(
            f"close mismatch {m.date.isoformat()}: "
            f"tiingo={m.tiingo_close:.4f} alpaca={m.alpaca_close:.4f} "
            f"rel_diff={m.rel_diff:.4%}"
        )

    return ReconcileReport(
        symbol=symbol,
        passed=not errors,
        overlap_start=overlap_start,
        overlap_end=overlap_end,
        n_overlap=n_overlap,
        n_mismatches=n_mismatches,
        mismatches=mismatches,
        dates_only_in_tiingo=only_tiingo,
        dates_only_in_alpaca=only_alpaca,
        errors=errors,
        warnings=warnings,
    )


__all__ = ["Mismatch", "ReconcileReport", "reconcile"]
