"""Weekly-review tests: divergence verdicts, alerts, ops stats, readiness.

Brokers, store, shadow, and alert dispatch are all stubbed -- no network, no real
alerts, no market data. The shadow function is injected so paper-vs-shadow
divergence is exact and controllable.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from quantlab.data.calendar import TradingCalendar
from quantlab.reporting.alerts import Alert
from quantlab.reporting.weekly import (
    TARGET_DAYS,
    build_weekly_review,
    render_markdown,
    write_weekly_review,
)
from quantlab.risk.state import RiskState, risk_state_path_for, save_risk_state

NOW = datetime(2026, 7, 10, 21, 0, 0, tzinfo=UTC)
WEEK_ENDING = date(2026, 7, 10)
WEEK_DATES = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]


def _seed_equity(path: Path, dates: list[str], values: list[float]) -> None:
    pd.DataFrame(
        {"timestamp": pd.to_datetime(dates), "equity": values}
    ).to_parquet(path, index=False)


def _seed_run(reports_dir: Path, label: str, ts: str, *, aborted: bool = False,
              stage: str | None = None) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {"strategy": label, "timestamp": ts, "aborted": aborted, "abort_stage": stage}
    stamp = ts.replace(":", "").replace("-", "").replace("T", "")
    (reports_dir / f"run_{label}_{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")


def _seed_alert(path: Path, ts: str, level: str, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"timestamp": ts, "level": level, "title": title,
                             "body": "b", "source": "s"}) + "\n")


def _stub_shadow(values_by_label: dict[str, float]):
    """A shadow fn whose compounded return over any window is a fixed per-label value.

    Implemented as a single dated return on the window's end date, so both the
    weekly and cumulative compounding pick up exactly that value.
    """
    def _fn(label: str, store: object, start: date, end: date) -> pd.Series:
        return pd.Series([values_by_label[label]], index=pd.DatetimeIndex([pd.Timestamp(end)]))
    return _fn


def _base_dirs(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    reports_dir = tmp_path / "paper"
    alerts_path = tmp_path / "alerts.jsonl"
    return data_dir, reports_dir, alerts_path


def _build(tmp_path, *, shadow_values, alert_fn=None, brokers=None):
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    # voltarget: +1.00% paper week; trend: +2.00% paper week.
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    _seed_equity(data_dir / "equity_history_trend.parquet", WEEK_DATES,
                 [50_000, 50_250, 50_500, 50_750, 51_000])
    if brokers is None:
        brokers = {"voltarget": object(), "trend": object()}
    review = build_weekly_review(
        brokers, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow(shadow_values),
        alert_fn=alert_fn if alert_fn is not None else (lambda _a: []),
        data_dir=data_dir, paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    return review, data_dir, reports_dir, alerts_path


def test_divergence_bps_from_seeded_equity_and_shadow(tmp_path) -> None:
    # voltarget paper +1.00%, shadow +0.95% -> divergence +5 bps.
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0095})
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.paper_week_return == pytest.approx(0.01)
    assert vt.shadow_week_return == pytest.approx(0.0095)
    assert vt.divergence_bps == pytest.approx(5.0)


def test_tracking_within_threshold(tmp_path) -> None:
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0195})
    # Both within 50 bps of paper -> TRACKING.
    assert all(a.verdict == "TRACKING" for a in review.accounts)


def test_diverging_beyond_threshold(tmp_path) -> None:
    # trend paper +2.00%, shadow +1.00% -> 100 bps -> DIVERGING.
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.01})
    tr = next(a for a in review.accounts if a.label == "trend")
    assert tr.divergence_bps == pytest.approx(100.0)
    assert tr.verdict == "DIVERGING"
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.verdict == "TRACKING"


def test_diverging_fires_exactly_one_warning_alert(tmp_path) -> None:
    alert_fn = MagicMock(return_value=[])
    # Only trend diverges.
    _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.01}, alert_fn=alert_fn)
    assert alert_fn.call_count == 1
    sent = alert_fn.call_args.args[0]
    assert isinstance(sent, Alert)
    assert sent.level == "WARNING"
    assert "trend" in sent.title
    assert sent.source == "reporting.weekly"


def test_cumulative_divergence_and_dividend_note(tmp_path) -> None:
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0195})
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.cumulative is not None
    # inception==week-start here, so cumulative divergence == week divergence.
    assert vt.cumulative.cumulative_divergence_bps == pytest.approx(5.0)
    assert "dividend" in vt.cumulative.expected_dividend_drag_note.lower()


def test_ops_stats_count_runs_and_aborts_by_stage(tmp_path) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    _seed_equity(data_dir / "equity_history_trend.parquet", WEEK_DATES,
                 [50_000, 50_250, 50_500, 50_750, 51_000])
    _seed_run(reports_dir, "voltarget", "2026-07-07T14:00:00")
    _seed_run(reports_dir, "voltarget", "2026-07-08T14:00:00")
    _seed_run(reports_dir, "voltarget", "2026-07-09T14:00:00", aborted=True, stage="validate")
    _seed_alert(alerts_path, "2026-07-08T14:00:00+00:00", "WARNING",
                "paper voltarget aborted at 'validate'")

    review = build_weekly_review(
        {"voltarget": object(), "trend": object()}, MagicMock(), TradingCalendar(),
        NOW, WEEK_ENDING, shadow_fn=_stub_shadow({"voltarget": 0.0095, "trend": 0.0195}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.ops is not None
    assert vt.ops.runs_attempted == 3
    assert vt.ops.runs_completed == 2
    assert vt.ops.runs_aborted == 1
    assert vt.ops.aborted_by_stage == {"validate": 1}
    assert vt.ops.alerts_by_level == {"WARNING": 1}


def test_insufficient_snapshots_is_graceful(tmp_path) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", ["2026-07-10"], [100_000])
    _seed_equity(data_dir / "equity_history_trend.parquet", WEEK_DATES,
                 [50_000, 50_250, 50_500, 50_750, 51_000])
    review = build_weekly_review(
        {"voltarget": object(), "trend": object()}, MagicMock(), TradingCalendar(),
        NOW, WEEK_ENDING, shadow_fn=_stub_shadow({"voltarget": 0.0, "trend": 0.0195}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.verdict == "INSUFFICIENT"
    assert vt.available is True
    assert vt.window is not None and vt.window.insufficient
    assert "since-inception" in (vt.window.note or "")


def test_absent_account_skipped(tmp_path) -> None:
    review, *_ = _build(
        tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0195},
        brokers={"voltarget": object(), "trend": None},
    )
    tr = next(a for a in review.accounts if a.label == "trend")
    assert tr.available is False
    assert tr.note is not None


def test_readiness_blockers_include_halt_and_sub4_runs(tmp_path) -> None:
    review, data_dir, reports_dir, alerts_path = _build(
        tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0195}
    )
    # No run reports were seeded -> 0 completed runs this week for both accounts.
    r = review.readiness
    assert any("< 4" in b for b in r.blockers)  # sub-4-completed-runs blocker
    assert any("voltarget" in b for b in r.blockers)


def test_readiness_flags_halted_account(tmp_path) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    _seed_equity(data_dir / "equity_history_trend.parquet", WEEK_DATES,
                 [50_000, 50_250, 50_500, 50_750, 51_000])
    save_risk_state(
        RiskState(halted=True, reason="daily loss", requires_manual_reset=False),
        risk_state_path_for("voltarget", data_dir),
    )
    review = build_weekly_review(
        {"voltarget": object(), "trend": object()}, MagicMock(), TradingCalendar(),
        NOW, WEEK_ENDING, shadow_fn=_stub_shadow({"voltarget": 0.0095, "trend": 0.0195}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    assert any("HALT" in b and "voltarget" in b for b in review.readiness.blockers)


def test_readiness_pct_complete_math(tmp_path) -> None:
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0195})
    r = review.readiness
    # Track start = 2026-07-06, week ending 2026-07-10 -> 4 calendar days elapsed.
    assert r.paper_start_date == date(2026, 7, 6)
    assert r.calendar_days_elapsed == 4
    assert r.target_days == TARGET_DAYS
    assert r.pct_complete == pytest.approx(100.0 * 4 / TARGET_DAYS)


def test_render_markdown_and_write(tmp_path) -> None:
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.01})
    from quantlab import __version__

    md = render_markdown(review)
    assert "# quantlab weekly review" in md
    assert f"quantlab {__version__}" in md  # traceable to a release + commit
    assert "## Account: voltarget" in md
    assert "## Account: trend" in md
    assert "Live-readiness ledger" in md
    assert "DIVERGING" in md  # trend diverges

    out_dir = tmp_path / "weekly"
    md_path, json_path = write_weekly_review(review, weekly_dir=out_dir)
    assert md_path.exists() and json_path.exists()
    # Same-week rerun overwrites (single file per week).
    write_weekly_review(review, weekly_dir=out_dir)
    assert len(list(out_dir.glob("week_*.md"))) == 1
