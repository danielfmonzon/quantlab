"""Phase-9 weekly review: paper-vs-shadow tracking, ops stats, readiness ledger.

Report-only. ``build_weekly_review`` produces, per paper account:

* the week's paper return (last 5 equity snapshots) vs the shadow return the
  paper account SHOULD have earned over the same span, and their divergence;
* cumulative paper-vs-shadow return since track start, with an explicit
  dividend-drag annotation (see ``reporting.shadow`` caveat (c));
* operational stats for the week (runs attempted/completed/aborted by stage,
  alerts by level, the account's current RiskState);
* a per-account verdict: TRACKING when |week divergence| <= the configured
  threshold (``weekly_divergence_alert_bps``, default 50), DIVERGING otherwise.
  A DIVERGING account fires exactly one WARNING alert.

Plus a portfolio-wide live-readiness ledger (elapsed vs a 90-day target, with
blockers). ``render_markdown`` formats it; ``write_weekly_review`` writes
``week_{YYYYMMDD}.md`` + ``.json`` under ``reports/weekly/``.

The shadow is close-to-close while paper equity marks are ~10:00 ET and Alpaca
paper does not credit dividends, so some drift is STRUCTURAL, not tracking error
(see ``reporting.shadow``). The threshold and the dividend-drag note exist so the
review annotates that expected drift rather than alarming on it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from quantlab.config import APPROVED_STRATEGIES
from quantlab.constants import PROJECT_ROOT
from quantlab.data.calendar import TradingCalendar
from quantlab.data.store import ParquetStore
from quantlab.paper.runner import (
    DATA_DIR,
    PAPER_REPORTS_DIR,
    equity_history_path_for,
)
from quantlab.reporting.alerts import ALERTS_JSONL, Alert, DeliveryResult, dispatch
from quantlab.reporting.shadow import shadow_returns
from quantlab.risk.limits import load_risk_limits
from quantlab.risk.state import RiskState, load_risk_state, risk_state_path_for
from quantlab.version import version_string

WEEKLY_DIR: Path = PROJECT_ROOT / "reports" / "weekly"

# Live-readiness target: 90 calendar days of clean paper tracking before any
# consideration of going live. A constant by design (a policy gate, not a knob).
TARGET_DAYS = 90

# A trading week is five sessions; the paper runner snapshots equity once per run.
_WEEK_SNAPSHOTS = 5
# Minimum completed runs in a week below which readiness flags the account.
_MIN_COMPLETED_RUNS = 4

# Injected so tests can substitute deterministic stubs.
ShadowFn = Callable[[str, ParquetStore, date, date], pd.Series]
AlertFn = Callable[[Alert], list[DeliveryResult]]

_DIVIDEND_DRAG_NOTE = (
    "Alpaca paper does not credit cash dividends while the shadow uses "
    "dividend-adjusted (adj_close) returns, so paper is EXPECTED to lag the "
    "shadow by roughly the portfolio's dividend yield over time. A negative "
    "cumulative divergence of that order is expected dividend drag, not tracking "
    "error."
)


class WeekWindow(BaseModel):
    start: date | None
    end: date | None
    n_snapshots: int
    insufficient: bool
    note: str | None = None


class CumulativeStats(BaseModel):
    paper_total_return: float | None
    shadow_total_return: float | None
    cumulative_divergence_bps: float | None
    expected_dividend_drag_note: str = _DIVIDEND_DRAG_NOTE


class OpsStats(BaseModel):
    runs_attempted: int
    runs_completed: int
    runs_aborted: int
    aborted_by_stage: dict[str, int] = {}
    alerts_by_level: dict[str, int] = {}
    risk_state: RiskState | None = None


class AccountWeekly(BaseModel):
    label: str
    available: bool
    note: str | None = None
    window: WeekWindow | None = None
    paper_week_return: float | None = None
    shadow_week_return: float | None = None
    divergence_bps: float | None = None
    cumulative: CumulativeStats | None = None
    ops: OpsStats | None = None
    verdict: str = "INSUFFICIENT"  # TRACKING / DIVERGING / INSUFFICIENT


class ReadinessLedger(BaseModel):
    paper_start_date: date | None
    calendar_days_elapsed: int
    target_days: int = TARGET_DAYS
    pct_complete: float
    blockers: list[str] = []


class WeeklyReview(BaseModel):
    generated_at: datetime
    week_ending: date
    divergence_threshold_bps: float
    accounts: list[AccountWeekly]
    readiness: ReadinessLedger


def _equity_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame({"timestamp": pd.Series(dtype="datetime64[ns]"),
                             "equity": pd.Series(dtype="float64")})
    df = pd.read_parquet(path)
    return df.sort_values("timestamp").reset_index(drop=True)


def _compound(series: pd.Series, start_exclusive: date, end_inclusive: date) -> float | None:
    """Compound daily returns over ``(start_exclusive, end_inclusive]``."""
    if series is None or series.empty:
        return None
    idx_dates = series.index.date
    mask = (idx_dates > start_exclusive) & (idx_dates <= end_inclusive)
    sub = series[mask]
    if sub.empty:
        return None
    return float((1.0 + sub).prod() - 1.0)


def _runs_in_window(
    paper_reports_dir: Path, label: str, start: date, end: date
) -> list[dict[str, object]]:
    if not paper_reports_dir.exists():
        return []
    runs: list[dict[str, object]] = []
    for path in sorted(paper_reports_dir.glob(f"run_{label}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ts = payload.get("timestamp")
        if not isinstance(ts, str):
            continue
        run_date = datetime.fromisoformat(ts).date()
        if start <= run_date <= end:
            runs.append(payload)
    return runs


def _alerts_in_window(
    alerts_path: Path, label: str, start: date, end: date
) -> dict[str, int]:
    if not alerts_path.exists():
        return {}
    counts: dict[str, int] = {}
    for line in alerts_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = record.get("timestamp")
        if not isinstance(ts, str):
            continue
        alert_date = datetime.fromisoformat(ts).date()
        if not (start <= alert_date <= end):
            continue
        # alerts.jsonl is global; attribute to this account when the label appears
        # in the alert title (paper-run alerts embed the strategy name there).
        title = str(record.get("title", "")).lower()
        if label.lower() not in title:
            continue
        level = str(record.get("level", "UNKNOWN"))
        counts[level] = counts.get(level, 0) + 1
    return counts


def _ops_stats(
    label: str, paper_reports_dir: Path, alerts_path: Path,
    week_start: date, week_end: date, data_dir: Path,
) -> OpsStats:
    runs = _runs_in_window(paper_reports_dir, label, week_start, week_end)
    aborted_by_stage: dict[str, int] = {}
    completed = 0
    for r in runs:
        if r.get("aborted"):
            stage = str(r.get("abort_stage") or "unknown")
            aborted_by_stage[stage] = aborted_by_stage.get(stage, 0) + 1
        else:
            completed += 1
    return OpsStats(
        runs_attempted=len(runs),
        runs_completed=completed,
        runs_aborted=len(runs) - completed,
        aborted_by_stage=aborted_by_stage,
        alerts_by_level=_alerts_in_window(alerts_path, label, week_start, week_end),
        risk_state=load_risk_state(risk_state_path_for(label, data_dir)),
    )


def _account_weekly(
    label: str,
    available: bool,
    store: ParquetStore,
    week_ending: date,
    threshold_bps: float,
    *,
    shadow_fn: ShadowFn,
    data_dir: Path,
    paper_reports_dir: Path,
    alerts_path: Path,
) -> AccountWeekly:
    if not available:
        return AccountWeekly(label=label, available=False,
                             note="account keys not configured")

    # Ops stats span the seven calendar days ending week_ending (covers Mon-Fri).
    week_start = week_ending - timedelta(days=6)
    ops = _ops_stats(label, paper_reports_dir, alerts_path, week_start, week_ending, data_dir)

    history = _equity_history(equity_history_path_for(label, data_dir))
    history = history[history["timestamp"].dt.date <= week_ending]

    if len(history) < 2:
        note = ("insufficient snapshots for weekly window; showing since-inception"
                if len(history) == 1 else "no equity snapshots recorded yet")
        first_date = (pd.Timestamp(history["timestamp"].iloc[0]).date()
                      if len(history) else None)
        return AccountWeekly(
            label=label, available=True,
            window=WeekWindow(start=first_date, end=first_date,
                              n_snapshots=int(len(history)), insufficient=True, note=note),
            cumulative=None, ops=ops, verdict="INSUFFICIENT",
        )

    week_hist = history.tail(_WEEK_SNAPSHOTS)
    w_start = pd.Timestamp(week_hist["timestamp"].iloc[0]).date()
    w_end = pd.Timestamp(week_hist["timestamp"].iloc[-1]).date()
    paper_week = float(week_hist["equity"].iloc[-1]) / float(week_hist["equity"].iloc[0]) - 1.0

    incept = pd.Timestamp(history["timestamp"].iloc[0]).date()
    paper_total = float(history["equity"].iloc[-1]) / float(history["equity"].iloc[0]) - 1.0

    # The shadow needs enough dated returns to cover inception->week_ending.
    shadow_series = shadow_fn(label, store, incept, w_end)
    shadow_week = _compound(shadow_series, w_start, w_end)
    shadow_total = _compound(shadow_series, incept, w_end)

    divergence_bps = (
        (paper_week - shadow_week) * 1e4 if shadow_week is not None else None
    )
    cum_div_bps = (
        (paper_total - shadow_total) * 1e4 if shadow_total is not None else None
    )

    if divergence_bps is None:
        verdict = "INSUFFICIENT"
    elif abs(divergence_bps) <= threshold_bps:
        verdict = "TRACKING"
    else:
        verdict = "DIVERGING"

    window = WeekWindow(
        start=w_start, end=w_end, n_snapshots=int(len(week_hist)),
        insufficient=len(week_hist) < _WEEK_SNAPSHOTS,
        note=("fewer than 5 snapshots; week return spans what is available"
              if len(week_hist) < _WEEK_SNAPSHOTS else None),
    )
    return AccountWeekly(
        label=label, available=True, window=window,
        paper_week_return=paper_week, shadow_week_return=shadow_week,
        divergence_bps=divergence_bps,
        cumulative=CumulativeStats(
            paper_total_return=paper_total, shadow_total_return=shadow_total,
            cumulative_divergence_bps=cum_div_bps,
        ),
        ops=ops, verdict=verdict,
    )


def _readiness_ledger(
    accounts: list[AccountWeekly], data_dir: Path, week_ending: date,
) -> ReadinessLedger:
    # Track start = earliest first-snapshot date across all available accounts.
    starts: list[date] = []
    for acct in accounts:
        if not acct.available:
            continue
        path = equity_history_path_for(acct.label, data_dir)
        history = _equity_history(path)
        if len(history):
            starts.append(pd.Timestamp(history["timestamp"].iloc[0]).date())
    paper_start = min(starts) if starts else None

    elapsed = (week_ending - paper_start).days if paper_start else 0
    pct = min(100.0, 100.0 * elapsed / TARGET_DAYS) if TARGET_DAYS else 0.0

    blockers: list[str] = []
    for acct in accounts:
        if not acct.available:
            continue
        rs = acct.ops.risk_state if acct.ops else None
        if rs is not None and rs.halted:
            kind = "KILL" if rs.requires_manual_reset else "HALT"
            blockers.append(f"{acct.label}: {kind} active - {rs.reason}")
        if acct.verdict == "DIVERGING" and acct.divergence_bps is not None:
            blockers.append(
                f"{acct.label}: DIVERGING week ({acct.divergence_bps:+.0f} bps)"
            )
        if acct.ops is not None and acct.ops.runs_completed < _MIN_COMPLETED_RUNS:
            blockers.append(
                f"{acct.label}: only {acct.ops.runs_completed} completed run(s) "
                f"this week (< {_MIN_COMPLETED_RUNS})"
            )
    return ReadinessLedger(
        paper_start_date=paper_start, calendar_days_elapsed=elapsed,
        pct_complete=pct, blockers=blockers,
    )


def build_weekly_review(
    brokers: Mapping[str, object | None],
    store: ParquetStore,
    calendar: TradingCalendar,
    now: datetime,
    week_ending: date | None = None,
    *,
    shadow_fn: ShadowFn = shadow_returns,
    alert_fn: AlertFn = dispatch,
    data_dir: Path = DATA_DIR,
    paper_reports_dir: Path = PAPER_REPORTS_DIR,
    alerts_path: Path = ALERTS_JSONL,
) -> WeeklyReview:
    """Assemble the weekly review across every approved account.

    ``brokers`` maps each label to its client (or None when keys are absent — that
    account is reported as unavailable, mirroring the daily digest). Each DIVERGING
    account fires exactly one WARNING alert via ``alert_fn``.
    """
    week_end = week_ending if week_ending is not None else now.date()
    threshold = load_risk_limits().weekly_divergence_alert_bps

    accounts: list[AccountWeekly] = []
    for label in APPROVED_STRATEGIES:
        acct = _account_weekly(
            label, brokers.get(label) is not None, store, week_end, threshold,
            shadow_fn=shadow_fn, data_dir=data_dir,
            paper_reports_dir=paper_reports_dir, alerts_path=alerts_path,
        )
        accounts.append(acct)
        if acct.verdict == "DIVERGING":
            alert_fn(Alert(
                level="WARNING",
                title=f"weekly review: {label} DIVERGING",
                body=(f"{label} paper-vs-shadow divergence "
                      f"{acct.divergence_bps:+.0f} bps this week exceeds the "
                      f"{threshold:.0f} bps threshold."),
                source="reporting.weekly",
            ))

    readiness = _readiness_ledger(accounts, data_dir, week_end)
    return WeeklyReview(
        generated_at=now, week_ending=week_end,
        divergence_threshold_bps=threshold, accounts=accounts, readiness=readiness,
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def _bps(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.0f} bps"


def _render_account(acct: AccountWeekly) -> list[str]:
    lines: list[str] = [f"## Account: {acct.label}"]
    if not acct.available:
        lines.append(f"- _skipped: {acct.note}_")
        lines.append("")
        return lines

    if acct.window is not None and acct.window.insufficient and acct.paper_week_return is None:
        lines.append(f"- _{acct.window.note}_")
        if acct.ops is not None:
            lines.append(f"- runs this week: {acct.ops.runs_attempted} attempted, "
                         f"{acct.ops.runs_completed} completed, {acct.ops.runs_aborted} aborted")
        lines.append(f"- verdict: **{acct.verdict}**")
        lines.append("")
        return lines

    w = acct.window
    if w is not None:
        span = f"{w.start.isoformat()} -> {w.end.isoformat()}" if w.start and w.end else "n/a"
        lines.append(f"- week window: {span} ({w.n_snapshots} snapshot(s))")
    lines.append(f"- paper week return: {_pct(acct.paper_week_return)}")
    lines.append(f"- shadow week return: {_pct(acct.shadow_week_return)}")
    lines.append(f"- week divergence: {_bps(acct.divergence_bps)}")

    c = acct.cumulative
    if c is not None:
        lines.append(f"- cumulative paper: {_pct(c.paper_total_return)}  |  "
                     f"shadow: {_pct(c.shadow_total_return)}  |  "
                     f"divergence: {_bps(c.cumulative_divergence_bps)}")
        lines.append(f"- _dividend note: {c.expected_dividend_drag_note}_")

    o = acct.ops
    if o is not None:
        lines.append(f"- runs this week: {o.runs_attempted} attempted, "
                     f"{o.runs_completed} completed, {o.runs_aborted} aborted")
        if o.aborted_by_stage:
            by_stage = ", ".join(f"{k}={v}" for k, v in sorted(o.aborted_by_stage.items()))
            lines.append(f"  - aborts by stage: {by_stage}")
        if o.alerts_by_level:
            by_level = ", ".join(f"{k}={v}" for k, v in sorted(o.alerts_by_level.items()))
            lines.append(f"- alerts this week: {by_level}")
        else:
            lines.append("- alerts this week: (none)")
        rs = o.risk_state
        halted = rs.halted if rs is not None else False
        lines.append(f"- risk: halted **{halted}**"
                     + (f" - {rs.reason}" if rs is not None and rs.halted else ""))

    lines.append(f"- verdict: **{acct.verdict}**")
    lines.append("")
    return lines


def render_markdown(review: WeeklyReview) -> str:
    """Render the weekly review as Markdown."""
    lines: list[str] = [
        f"# quantlab weekly review - week ending {review.week_ending.isoformat()}",
        "",
        f"_generated {review.generated_at.isoformat()}  |  quantlab {version_string()}_",
        f"_DIVERGING threshold: {review.divergence_threshold_bps:.0f} bps "
        "(report-only; never affects the trading path)_",
        "",
    ]
    for acct in review.accounts:
        lines.extend(_render_account(acct))

    r = review.readiness
    lines.append("## Live-readiness ledger")
    start = r.paper_start_date.isoformat() if r.paper_start_date else "-"
    lines.append(f"- paper track start: {start}")
    lines.append(f"- elapsed: {r.calendar_days_elapsed} / {r.target_days} calendar days "
                 f"({r.pct_complete:.1f}% complete)")
    if r.blockers:
        lines.append("- blockers:")
        for b in r.blockers:
            lines.append(f"  - {b}")
    else:
        lines.append("- blockers: (none)")
    lines.append("")
    return "\n".join(lines)


def write_weekly_review(
    review: WeeklyReview, weekly_dir: Path = WEEKLY_DIR
) -> tuple[Path, Path]:
    """Write ``week_{YYYYMMDD}.md`` and ``.json`` (overwriting same-week reruns)."""
    weekly_dir.mkdir(parents=True, exist_ok=True)
    stamp = review.week_ending.strftime("%Y%m%d")
    md_path = weekly_dir / f"week_{stamp}.md"
    json_path = weekly_dir / f"week_{stamp}.json"
    md_path.write_text(render_markdown(review), encoding="utf-8")
    json_path.write_text(
        json.dumps(review.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    return md_path, json_path


__all__ = [
    "build_weekly_review",
    "render_markdown",
    "write_weekly_review",
    "WeeklyReview",
    "AccountWeekly",
    "WeekWindow",
    "CumulativeStats",
    "OpsStats",
    "ReadinessLedger",
    "WEEKLY_DIR",
    "TARGET_DAYS",
]
