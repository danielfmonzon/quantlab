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
from quantlab.reporting.weekly import (
    _alerts_in_window as alerts_in_window,
)
from quantlab.reporting.weekly import (
    _last_snapshot_per_day as last_snapshot_per_day,
)
from quantlab.risk.state import RiskState, risk_state_path_for, save_risk_state

NOW = datetime(2026, 7, 10, 21, 0, 0, tzinfo=UTC)
WEEK_ENDING = date(2026, 7, 10)
WEEK_DATES = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]
# A crypto week is seven UTC days (24/7 market), not five sessions.
CRYPTO_WEEK_DATES = [
    "2026-07-04", "2026-07-05", "2026-07-06", "2026-07-07",
    "2026-07-08", "2026-07-09", "2026-07-10",
]


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
    weekly and cumulative compounding pick up exactly that value. Labels absent
    from the mapping shadow flat (0.0).
    """
    def _fn(label: str, store: object, start: date, end: date) -> pd.Series:
        return pd.Series([values_by_label.get(label, 0.0)],
                         index=pd.DatetimeIndex([pd.Timestamp(end)]))
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


def _build_four(tmp_path, *, shadow_values=None, week_ending=WEEK_ENDING, now=NOW,
                alert_fn=None):
    """All four approved accounts (2 equity + 2 crypto) with brokers configured.

    Equity accounts get a 5-session week; crypto accounts get a 7-UTC-day week,
    each +1.00% paper over its own window.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    _seed_equity(data_dir / "equity_history_trend.parquet", WEEK_DATES,
                 [50_000, 50_250, 50_500, 50_750, 51_000])
    _seed_equity(data_dir / "equity_history_crypto_trend.parquet", CRYPTO_WEEK_DATES,
                 [100_000, 100_100, 100_300, 100_400, 100_600, 100_800, 101_000])
    _seed_equity(data_dir / "equity_history_crypto_voltarget.parquet", CRYPTO_WEEK_DATES,
                 [200_000, 200_200, 200_600, 200_800, 201_200, 201_600, 202_000])
    brokers = {label: object() for label in
               ("voltarget", "trend", "crypto_trend", "crypto_voltarget")}
    review = build_weekly_review(
        brokers, MagicMock(), TradingCalendar(), now, week_ending,
        shadow_fn=_stub_shadow(shadow_values or {}),
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
    # Both configured accounts are within 50 bps of paper -> TRACKING. (The crypto
    # accounts have no broker in this fixture and render as unavailable.)
    available = [a for a in review.accounts if a.available]
    assert len(available) == 2
    assert all(a.verdict == "TRACKING" for a in available)


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
    assert "dividend" in vt.cumulative.structural_drift_note.lower()


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
    equity = next(c for c in review.readiness.clocks if c.asset_class == "us_equity")
    # Equity track start = 2026-07-06, week ending 2026-07-10 -> 4 calendar days.
    assert equity.paper_start_date == date(2026, 7, 6)
    assert equity.calendar_days_elapsed == 4
    assert equity.target_days == TARGET_DAYS
    assert equity.pct_complete == pytest.approx(100.0 * 4 / TARGET_DAYS)
    # The equity clock is derived from data, never floored by policy.
    assert equity.start_note is None


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


# --------------------------------------------------------------------------
# All-asset-class coverage (crypto accounts included)
# --------------------------------------------------------------------------


def test_four_accounts_render_four_sections_with_asset_class_labels(tmp_path) -> None:
    review, *_ = _build_four(tmp_path)
    assert [a.label for a in review.accounts] == [
        "voltarget", "trend", "crypto_trend", "crypto_voltarget",
    ]
    assert all(a.available for a in review.accounts)

    md = render_markdown(review)
    assert "## Account: voltarget (us_equity)" in md
    assert "## Account: trend (us_equity)" in md
    assert "## Account: crypto_trend (crypto)" in md
    assert "## Account: crypto_voltarget (crypto)" in md
    assert md.count("## Account:") == 4


def test_crypto_sections_carry_crypto_note_not_dividend_note(tmp_path) -> None:
    review, *_ = _build_four(tmp_path)
    ct = next(a for a in review.accounts if a.label == "crypto_trend")
    assert ct.asset_class == "crypto"
    assert ct.cumulative is not None
    note = ct.cumulative.structural_drift_note.lower()
    assert "24/7" in note and "once-daily" in note
    assert "does not credit cash dividends" not in note

    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.cumulative is not None
    assert "does not credit cash dividends" in vt.cumulative.structural_drift_note

    md = render_markdown(review)
    assert "- _crypto note:" in md
    assert "- _dividend note:" in md


def test_crypto_week_window_spans_seven_utc_days(tmp_path) -> None:
    review, *_ = _build_four(tmp_path)
    ct = next(a for a in review.accounts if a.label == "crypto_trend")
    assert ct.window is not None
    assert ct.window.n_snapshots == 7  # a crypto week is 7 days, not 5 sessions
    assert ct.window.insufficient is False
    assert ct.window.start == date(2026, 7, 4)
    assert ct.window.end == date(2026, 7, 10)
    # Equity keeps its 5-session week untouched.
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.window is not None and vt.window.n_snapshots == 5


def test_readiness_has_one_clock_per_asset_class_with_floored_crypto_start(tmp_path) -> None:
    # Week ending after the crypto restart date so the crypto clock has run.
    review, *_ = _build_four(
        tmp_path, week_ending=date(2026, 7, 24),
        now=datetime(2026, 7, 24, 21, 0, 0, tzinfo=UTC),
    )
    clocks = {c.asset_class: c for c in review.readiness.clocks}
    assert list(clocks) == ["us_equity", "crypto"]

    equity = clocks["us_equity"]
    assert equity.paper_start_date == date(2026, 7, 6)  # derived from first snapshot
    assert equity.calendar_days_elapsed == 18
    assert equity.start_note is None

    # Crypto history starts 2026-07-04 but the ruling floors the clock at 07-22.
    crypto = clocks["crypto"]
    assert crypto.paper_start_date == date(2026, 7, 22)
    assert crypto.calendar_days_elapsed == 2
    assert crypto.pct_complete == pytest.approx(100.0 * 2 / TARGET_DAYS)
    assert crypto.start_note is not None
    assert "2026-07-22" in crypto.start_note and "2026-07-04" in crypto.start_note

    md = render_markdown(review)
    assert "- **us_equity**: paper track start 2026-07-06" in md
    assert "- **crypto**: paper track start 2026-07-22" in md
    assert "clock restarted 2026-07-22 by ruling" in md


def test_crypto_clock_never_goes_negative_before_the_restart_date(tmp_path) -> None:
    # week_ending (2026-07-10) precedes the 2026-07-22 floor: 0 days, not negative.
    review, *_ = _build_four(tmp_path)
    crypto = next(c for c in review.readiness.clocks if c.asset_class == "crypto")
    assert crypto.paper_start_date == date(2026, 7, 22)
    assert crypto.calendar_days_elapsed == 0
    assert crypto.pct_complete == pytest.approx(0.0)


def test_last_snapshot_per_day_keeps_only_the_final_mark(tmp_path) -> None:
    # Two marks on 2026-07-20 (the pre-fix double-run); one on each other day.
    history = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-07-20 05:17:36", "2026-07-20 14:01:00", "2026-07-21 05:18:13",
        ]),
        "equity": [99_833.94, 99_894.84, 101_175.92],
    })
    collapsed = last_snapshot_per_day(history)
    assert len(collapsed) == 2
    assert list(collapsed["equity"]) == [99_894.84, 101_175.92]  # the LAST of 07-20
    assert list(collapsed["timestamp"].dt.date) == [date(2026, 7, 20), date(2026, 7, 21)]


def test_crypto_double_run_day_does_not_shrink_the_week_window(tmp_path) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    _seed_equity(data_dir / "equity_history_trend.parquet", WEEK_DATES,
                 [50_000, 50_250, 50_500, 50_750, 51_000])
    _seed_equity(data_dir / "equity_history_crypto_trend.parquet", CRYPTO_WEEK_DATES,
                 [100_000, 100_100, 100_300, 100_400, 100_600, 100_800, 101_000])
    # crypto_voltarget carries a SECOND mark on each of the last three days: the
    # 05:00 UTC crypto-task run plus the leaked 14:00 UTC equity-task run.
    _seed_equity(
        data_dir / "equity_history_crypto_voltarget.parquet",
        ["2026-07-04 05:00:00", "2026-07-05 05:00:00", "2026-07-06 05:00:00",
         "2026-07-07 05:00:00",
         "2026-07-08 05:00:00", "2026-07-08 14:00:00",
         "2026-07-09 05:00:00", "2026-07-09 14:00:00",
         "2026-07-10 05:00:00", "2026-07-10 14:00:00"],
        [200_000, 200_200, 200_600, 200_800,
         201_200, 201_300,
         201_600, 201_700,
         202_000, 202_100],
    )
    brokers = {label: object() for label in
               ("voltarget", "trend", "crypto_trend", "crypto_voltarget")}
    review = build_weekly_review(
        brokers, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow({}), alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    cv = next(a for a in review.accounts if a.label == "crypto_voltarget")
    assert cv.window is not None
    # 10 raw snapshots collapse to 7 days; the window is still a full week.
    assert cv.window.n_snapshots == 7
    assert cv.window.start == date(2026, 7, 4)
    assert cv.window.end == date(2026, 7, 10)
    # Week return runs first-day mark -> LAST mark of the final day.
    assert cv.paper_week_return == pytest.approx(202_100 / 200_000 - 1.0)


# --------------------------------------------------------------------------
# Exact-label alert attribution (replaces substring matching)
# --------------------------------------------------------------------------


def _seed_alert_row(path: Path, ts: str, level: str, title: str,
                    strategy: str | None = None) -> None:
    """Append one alert record; omit ``strategy`` to simulate a legacy entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {"timestamp": ts, "level": level, "title": title,
                                 "body": "b", "source": "s"}
    if strategy is not None:
        record["strategy"] = strategy
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _counts_for(path: Path, label: str) -> dict[str, int]:
    return alerts_in_window(path, label, date(2026, 7, 16), date(2026, 7, 22))


def test_trend_does_not_absorb_crypto_trend_alerts(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"
    _seed_alert_row(path, "2026-07-20T14:00:00+00:00", "WARNING",
                    "paper trend aborted at 'health'", strategy="trend")
    _seed_alert_row(path, "2026-07-20T05:00:00+00:00", "WARNING",
                    "paper crypto_trend aborted at 'health'", strategy="crypto_trend")
    assert _counts_for(path, "trend") == {"WARNING": 1}
    assert _counts_for(path, "crypto_trend") == {"WARNING": 1}


def test_voltarget_does_not_absorb_crypto_voltarget_alerts(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"
    _seed_alert_row(path, "2026-07-20T14:00:00+00:00", "INFO",
                    "paper voltarget: 1 order(s) submitted", strategy="voltarget")
    for i in range(3):
        _seed_alert_row(path, f"2026-07-2{i}T05:00:00+00:00", "INFO",
                        "paper crypto_voltarget: 1 order(s) submitted",
                        strategy="crypto_voltarget")
    assert _counts_for(path, "voltarget") == {"INFO": 1}
    assert _counts_for(path, "crypto_voltarget") == {"INFO": 3}


def test_legacy_entries_without_the_field_still_attribute_correctly(tmp_path) -> None:
    # No 'strategy' key: falls back to a word-boundary title match. '_' is a word
    # character, so 'trend' must NOT match 'crypto_trend'.
    path = tmp_path / "alerts.jsonl"
    _seed_alert_row(path, "2026-07-20T14:00:00+00:00", "CRITICAL",
                    "paper trend aborted at 'account'")
    _seed_alert_row(path, "2026-07-20T05:00:00+00:00", "WARNING",
                    "paper crypto_trend aborted at 'health'")
    _seed_alert_row(path, "2026-07-21T14:00:00+00:00", "INFO",
                    "paper voltarget: 1 order(s) submitted")
    _seed_alert_row(path, "2026-07-21T05:00:00+00:00", "INFO",
                    "paper crypto_voltarget: 1 order(s) submitted")
    assert _counts_for(path, "trend") == {"CRITICAL": 1}
    assert _counts_for(path, "crypto_trend") == {"WARNING": 1}
    assert _counts_for(path, "voltarget") == {"INFO": 1}
    assert _counts_for(path, "crypto_voltarget") == {"INFO": 1}


def test_structured_field_wins_over_a_misleading_title(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"
    _seed_alert_row(path, "2026-07-20T14:00:00+00:00", "WARNING",
                    "weekly review: crypto_voltarget DIVERGING",
                    strategy="crypto_voltarget")
    assert _counts_for(path, "crypto_voltarget") == {"WARNING": 1}
    assert _counts_for(path, "voltarget") == {}


def test_mixed_legacy_and_structured_entries_coexist(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"
    _seed_alert_row(path, "2026-07-20T14:00:00+00:00", "INFO",
                    "paper trend: 2 order(s) submitted")            # legacy
    _seed_alert_row(path, "2026-07-21T14:00:00+00:00", "INFO",
                    "paper trend: 2 order(s) submitted", strategy="trend")
    _seed_alert_row(path, "2026-07-21T05:00:00+00:00", "INFO",
                    "paper crypto_trend: 1 order(s) submitted", strategy="crypto_trend")
    assert _counts_for(path, "trend") == {"INFO": 2}
    assert _counts_for(path, "crypto_trend") == {"INFO": 1}
