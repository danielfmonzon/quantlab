"""Walk-forward analysis: performance across contiguous, non-overlapping windows.

The panel's date range is tiled into ~``window_years`` segments. Each segment is
backtested on a FRESH strategy instance, run from ``warmup_buffer`` calendar days
before the segment so the signal is warmed up by the segment's first session —
but metrics are computed on the segment sessions ONLY. This is REPORT-ONLY (see
the package docstring): it measures consistency, it does not select anything.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd
from pydantic import BaseModel

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.metrics import compute_metrics
from quantlab.backtest.strategy import Strategy

# 400 calendar days comfortably covers 12 trailing month-ends (the deepest
# warmup any tactical strategy needs) plus slack for holidays.
WARMUP_BUFFER_DAYS = 400
_MIN_SEGMENT_DAYS = 365  # drop a trailing stub shorter than one year

StrategyFactory = Callable[[], Strategy]


class SegmentResult(BaseModel):
    """Metrics for one walk-forward segment (computed on segment sessions only)."""

    start: date
    end: date
    cagr: float
    sharpe: float | None
    max_drawdown: float
    total_return: float


class WalkForwardReport(BaseModel):
    """Per-segment results plus consistency aggregates."""

    window_years: int
    n_segments: int
    segments: list[SegmentResult]
    pct_segments_positive_return: float
    pct_segments_beat_cash: float  # cash earns 0%, so this is cagr > 0
    sharpe_min: float | None
    sharpe_median: float | None
    sharpe_max: float | None


def _segment_bounds(
    index: pd.DatetimeIndex, window_years: int
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Half-open [lo, hi) calendar bounds tiling the index, ``window_years`` wide."""
    start, end = index[0], index[-1]
    edges: list[pd.Timestamp] = [start]
    nxt = start + pd.DateOffset(years=window_years)
    while nxt <= end:
        edges.append(nxt)
        nxt = nxt + pd.DateOffset(years=window_years)
    edges.append(end + pd.Timedelta(days=1))  # inclusive upper bound for the tail
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]


def walk_forward(
    panel: pd.DataFrame,
    strategy_factory: StrategyFactory,
    window_years: int = 3,
    cost_bps: float = 5.0,
) -> WalkForwardReport:
    """Tile ``panel`` into ~``window_years`` segments and backtest each in turn.

    ``strategy_factory`` is called once per segment to obtain a fresh, un-warmed
    strategy. Each segment's run starts ``WARMUP_BUFFER_DAYS`` before the segment
    (clipped to available data), but only segment sessions contribute to metrics.
    """
    index = pd.DatetimeIndex(panel.index)
    bounds = _segment_bounds(index, window_years)

    segments: list[SegmentResult] = []
    for lo, hi in bounds:
        seg_dates = index[(index >= lo) & (index < hi)]
        if len(seg_dates) < 2:
            continue
        seg_start, seg_end = seg_dates[0], seg_dates[-1]

        run_start = seg_start - pd.Timedelta(days=WARMUP_BUFFER_DAYS)
        sub_panel = panel.loc[run_start:seg_end]
        result = run_backtest(sub_panel, strategy_factory(), cost_bps=cost_bps)

        seg_returns = result.daily_returns.loc[seg_start:seg_end]
        seg_equity = result.equity.loc[seg_start:seg_end]
        if len(seg_returns) < 2 or len(seg_equity) < 2:
            continue
        m = compute_metrics(seg_returns, seg_equity)
        total_return = float(seg_equity.iloc[-1] / seg_equity.iloc[0] - 1.0)
        segments.append(
            SegmentResult(
                start=seg_start.date(),
                end=seg_end.date(),
                cagr=m.cagr,
                sharpe=m.sharpe,
                max_drawdown=m.max_drawdown,
                total_return=total_return,
            )
        )

    # Drop a trailing stub shorter than one year (only the last segment can be one).
    if segments:
        last = segments[-1]
        if (last.end - last.start).days < _MIN_SEGMENT_DAYS:
            segments = segments[:-1]

    n = len(segments)
    sharpes = sorted(s.sharpe for s in segments if s.sharpe is not None)
    pct_positive = (
        sum(1 for s in segments if s.total_return > 0.0) / n if n else 0.0
    )
    pct_beat_cash = sum(1 for s in segments if s.cagr > 0.0) / n if n else 0.0

    return WalkForwardReport(
        window_years=window_years,
        n_segments=n,
        segments=segments,
        pct_segments_positive_return=pct_positive,
        pct_segments_beat_cash=pct_beat_cash,
        sharpe_min=sharpes[0] if sharpes else None,
        sharpe_median=_median(sharpes) if sharpes else None,
        sharpe_max=sharpes[-1] if sharpes else None,
    )


def _median(values: list[float]) -> float:
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


__all__ = ["walk_forward", "WalkForwardReport", "SegmentResult", "WARMUP_BUFFER_DAYS"]
