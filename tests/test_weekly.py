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

from quantlab.config import account_asset_class
from quantlab.data import CANONICAL_COLUMNS
from quantlab.data.calendar import TradingCalendar
from quantlab.data.store import ParquetStore
from quantlab.reporting.alerts import Alert
from quantlab.reporting.weekly import (
    TARGET_DAYS,
    build_weekly_review,
    render_markdown,
    session_for_mark,
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

    Implemented as a single dated return on the session the account's LAST mark pairs
    with, so both the weekly and cumulative compounding pick up exactly that value.
    The pairing offset is per asset class (``session_for_mark``): a crypto mark dated
    ``end`` closes session ``end - 1``, so a stub return dated ``end`` would fall
    outside the compared window and shadow flat. Labels absent from the mapping
    shadow flat (0.0).
    """
    def _fn(label: str, store: object, start: date, end: date) -> pd.Series:
        paired = session_for_mark(end, account_asset_class(label))
        return pd.Series([values_by_label.get(label, 0.0)],
                         index=pd.DatetimeIndex([pd.Timestamp(paired)]))
    return _fn


def _stub_shadow_series(series_by_label: dict[str, pd.Series]):
    """A shadow fn returning an explicit DATED series per label (empty if absent).

    Unlike ``_stub_shadow`` this controls the shadow's *coverage* -- the last session
    it carries a return for -- which is what the like-for-like alignment reads.
    """
    def _fn(label: str, store: object, start: date, end: date) -> pd.Series:
        return series_by_label.get(
            label, pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
        )
    return _fn


def _seed_bars(store: ParquetStore, symbol: str, closes: dict[str, float]) -> None:
    """Seed ``symbol`` with bars whose every price column is the given close."""
    frame = pd.DataFrame({
        "date": pd.to_datetime(list(closes)),
        **{c: list(closes.values()) for c in CANONICAL_COLUMNS if c != "date"},
    })
    store.upsert(symbol, frame[list(CANONICAL_COLUMNS)])


def _dated(returns: dict[str, float]) -> pd.Series:
    return pd.Series(list(returns.values()),
                     index=pd.DatetimeIndex([pd.Timestamp(d) for d in returns]))


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
    # The note must name the mechanisms the 2026-07-24 diagnosis actually found:
    # variable mark-window LENGTH (catch-up runs -> 10-33h windows vs uniform 24h
    # UTC days) and mark-PHASE offset, with weekend gaps as the secondary case.
    assert "length" in note and "phase" in note
    assert "10h to 33h" in note
    assert "24h utc days" in note
    assert "weekend" in note and "secondary" in note
    # Still not a dividend story.
    assert "does not credit cash dividends" not in note
    assert "dividend" in note  # explicitly says dividend drag does NOT apply


def test_crypto_note_does_not_claim_paper_marks_are_once_daily(tmp_path) -> None:
    """The old note's premise -- 'both once-daily' -- was the wrong mechanism.

    Paper marks are once-daily only after the review collapses them; their SPACING
    is what diverges (10.49h to 32.72h in week 2026-07-24), and the retired note
    attributed the whole gap to weekend/overnight moves instead.
    """
    review, *_ = _build_four(tmp_path)
    ct = next(a for a in review.accounts if a.label == "crypto_trend")
    assert ct.cumulative is not None
    note = ct.cumulative.structural_drift_note.lower()
    assert "once-daily" not in note
    # Weekend gaps must be present but demoted, not the headline mechanism.
    assert note.index("length") < note.index("weekend")

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
# Like-for-like window alignment (paper truncated to shadow coverage)
# --------------------------------------------------------------------------


def test_paper_snapshot_past_shadow_coverage_is_excluded_from_both_figures(
    tmp_path,
) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    # Paper marks all five sessions; the shadow only covers through 07-09.
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    shadow = _dated({"2026-07-07": 0.001, "2026-07-08": 0.001, "2026-07-09": 0.001})
    review = build_weekly_review(
        {"voltarget": object()}, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow_series({"voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")

    assert vt.excluded_tail_days == [date(2026, 7, 10)]
    # The window now ends where the shadow ends, and carries one fewer snapshot.
    assert vt.window is not None
    assert vt.window.start == date(2026, 7, 6)
    assert vt.window.end == date(2026, 7, 9)
    assert vt.window.n_snapshots == 4

    # Week AND cumulative both run 07-06 -> 07-09, excluding the 07-10 mark.
    aligned_paper = 100_750 / 100_000 - 1.0
    aligned_shadow = 1.001 ** 3 - 1.0
    assert vt.paper_week_return == pytest.approx(aligned_paper)
    assert vt.shadow_week_return == pytest.approx(aligned_shadow)
    assert vt.divergence_bps == pytest.approx((aligned_paper - aligned_shadow) * 1e4)
    assert vt.cumulative is not None
    assert vt.cumulative.paper_total_return == pytest.approx(aligned_paper)
    assert vt.cumulative.cumulative_divergence_bps == pytest.approx(vt.divergence_bps)

    # The ragged comparison this replaces would have used the 07-10 equity against
    # the same three shadow returns and crossed the threshold.
    ragged = (101_000 / 100_000 - 1.0 - aligned_shadow) * 1e4
    assert abs(ragged) > review.divergence_threshold_bps
    assert abs(vt.divergence_bps) <= review.divergence_threshold_bps
    assert vt.verdict == "TRACKING"


def test_excluded_tail_day_is_rendered_in_markdown(tmp_path) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    shadow = _dated({"2026-07-07": 0.001, "2026-07-08": 0.001, "2026-07-09": 0.001})
    review = build_weekly_review(
        {"voltarget": object()}, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow_series({"voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    md = render_markdown(review)
    assert "- excluded from comparison (no shadow data yet): 2026-07-10" in md


def test_aligned_windows_carry_no_excluded_tail(tmp_path) -> None:
    """When the shadow reaches the last paper mark, nothing is excluded or dropped."""
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0095})
    for acct in review.accounts:
        if acct.available:
            assert acct.excluded_tail_days == []
            assert acct.window is not None and acct.window.n_snapshots == 5


def test_trend_week_20260724_lands_within_threshold_once_aligned(tmp_path) -> None:
    """The 2026-07-24 trend scenario isolated to the five snapshots of that window.

    Published: -54.33 bps, DIVERGING. The 07-24 14:00Z snapshot was compared
    against a shadow that had no 07-24 session at all (SPY's EOD bar for that
    session did not exist yet), so that day's -32 bps landed whole in the
    divergence. Aligning to 07-23 leaves the ~-22 bps of mark-phase drift over
    07-21..07-23 and puts the account inside the 50 bps threshold.

    This fixture seeds ONLY the window's five snapshots, so the aligned window has
    four. The real account also has earlier snapshots, so its production window
    slides back to keep five --
    ``test_aligned_window_slides_back_to_preserve_a_full_week`` covers that.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(
        data_dir / "equity_history_trend.parquet",
        ["2026-07-20 14:00:14", "2026-07-21 14:00:11", "2026-07-22 14:00:28",
         "2026-07-23 14:00:16", "2026-07-24 14:00:18"],
        [99_209.80, 99_167.23, 99_609.55, 98_467.50, 98_147.57],
    )
    # trend held 100% SPY all week, so its shadow is SPY close-to-close.
    spy = {"2026-07-20": 742.09, "2026-07-21": 748.28,
           "2026-07-22": 747.41, "2026-07-23": 738.18}
    shadow = _dated({
        "2026-07-21": spy["2026-07-21"] / spy["2026-07-20"] - 1.0,
        "2026-07-22": spy["2026-07-22"] / spy["2026-07-21"] - 1.0,
        "2026-07-23": spy["2026-07-23"] / spy["2026-07-22"] - 1.0,
    })
    review = build_weekly_review(
        {"trend": object()}, MagicMock(), TradingCalendar(),
        datetime(2026, 7, 24, 21, 0, 0, tzinfo=UTC), date(2026, 7, 24),
        shadow_fn=_stub_shadow_series({"trend": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    tr = next(a for a in review.accounts if a.label == "trend")

    assert tr.excluded_tail_days == [date(2026, 7, 24)]
    assert tr.window is not None
    assert tr.window.start == date(2026, 7, 20)
    assert tr.window.end == date(2026, 7, 23)
    assert tr.window.n_snapshots == 4

    aligned_paper = 98_467.50 / 99_209.80 - 1.0
    aligned_shadow = float((1.0 + shadow).prod() - 1.0)
    assert tr.paper_week_return == pytest.approx(aligned_paper)
    assert tr.shadow_week_return == pytest.approx(aligned_shadow)
    # ~-22 bps, comfortably inside the 50 bps threshold -> TRACKING, not DIVERGING.
    assert tr.divergence_bps == pytest.approx(-22.1, abs=1.0)
    assert abs(tr.divergence_bps) <= review.divergence_threshold_bps
    assert tr.verdict == "TRACKING"
    assert not any("trend: DIVERGING" in b for b in review.readiness.blockers)

    # And the ragged comparison that produced the published figure was ~-54 bps.
    ragged = (98_147.57 / 99_209.80 - 1.0 - aligned_shadow) * 1e4
    assert ragged == pytest.approx(-54.3, abs=1.0)
    assert abs(ragged) > review.divergence_threshold_bps


def test_aligned_window_slides_back_to_preserve_a_full_week(tmp_path) -> None:
    """Truncating the tail must not shrink the week: the window slides back.

    A week is defined as the last N snapshots, so applying that definition to the
    ALIGNED history keeps a full five-snapshot comparison rather than silently
    reporting a four-snapshot one. Shaped like trend's real history, which carries
    snapshots before the published window (2026-07-09/13/14/16) and therefore
    slides from 07-20..07-24 back to 07-16..07-23.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(
        data_dir / "equity_history_trend.parquet",
        ["2026-07-13 14:00:17", "2026-07-14 14:00:48", "2026-07-16 15:09:32",
         "2026-07-20 14:00:14", "2026-07-21 14:00:11", "2026-07-22 14:00:28",
         "2026-07-23 14:00:16", "2026-07-24 14:00:18"],
        [100_288.65, 99_913.52, 100_203.52,
         99_209.80, 99_167.23, 99_609.55, 98_467.50, 98_147.57],
    )
    shadow = _dated({d: 0.0 for d in
                     ["2026-07-14", "2026-07-16", "2026-07-20", "2026-07-21",
                      "2026-07-22", "2026-07-23"]})
    review = build_weekly_review(
        {"trend": object()}, MagicMock(), TradingCalendar(),
        datetime(2026, 7, 24, 21, 0, 0, tzinfo=UTC), date(2026, 7, 24),
        shadow_fn=_stub_shadow_series({"trend": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    tr = next(a for a in review.accounts if a.label == "trend")
    assert tr.excluded_tail_days == [date(2026, 7, 24)]
    assert tr.window is not None
    # Five snapshots still, ending at coverage -- start slid back from 07-20.
    assert tr.window.n_snapshots == 5
    assert tr.window.insufficient is False
    assert tr.window.start == date(2026, 7, 16)
    assert tr.window.end == date(2026, 7, 23)
    assert tr.paper_week_return == pytest.approx(98_467.50 / 100_203.52 - 1.0)
    # Cumulative also stops at coverage: 07-13 -> 07-23, not -> 07-24.
    assert tr.cumulative is not None
    assert tr.cumulative.paper_total_return == pytest.approx(
        98_467.50 / 100_288.65 - 1.0
    )


def test_no_paper_snapshots_within_coverage_is_insufficient_not_a_divergence(
    tmp_path,
) -> None:
    """Shadow coverage predating every paper mark: report the tail, claim nothing."""
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet",
                 ["2026-07-09", "2026-07-10"], [100_000, 101_000])
    shadow = _dated({"2026-07-01": 0.001})
    review = build_weekly_review(
        {"voltarget": object()}, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow_series({"voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.verdict == "INSUFFICIENT"
    assert vt.divergence_bps is None
    assert vt.cumulative is None
    assert vt.excluded_tail_days == [date(2026, 7, 9), date(2026, 7, 10)]
    assert "- excluded from comparison (no shadow data yet): 2026-07-09, 2026-07-10" \
        in render_markdown(review)


def test_empty_shadow_leaves_the_paper_window_untouched(tmp_path) -> None:
    """No coverage information at all: do not truncate, do not invent exclusions."""
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    review = build_weekly_review(
        {"voltarget": object()}, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow_series({}), alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.excluded_tail_days == []
    assert vt.window is not None and vt.window.n_snapshots == 5
    assert vt.window.end == date(2026, 7, 10)
    assert vt.verdict == "INSUFFICIENT"  # nothing to compare against


def test_crypto_alignment_uses_utc_day_marks(tmp_path) -> None:
    """Crypto collapses to one mark per UTC day BEFORE alignment, then truncates.

    The exclusion boundary is the mark's PAIRED session, not the mark's own date. A
    crypto mark dated 07-10 closes session 07-09, so a shadow covering through 07-09
    can speak to it and it stays in — the pre-DEFECT-A code excluded it, comparing one
    fewer paper interval than the shadow could actually price.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    # Two marks on the final day (the double-run shape); shadow stops a day earlier.
    _seed_equity(
        data_dir / "equity_history_crypto_voltarget.parquet",
        ["2026-07-04 05:00:00", "2026-07-05 05:00:00", "2026-07-06 05:00:00",
         "2026-07-07 05:00:00", "2026-07-08 05:00:00", "2026-07-09 05:00:00",
         "2026-07-10 00:30:00", "2026-07-10 14:00:00"],
        [200_000, 200_200, 200_600, 200_800, 201_200, 201_600, 202_000, 202_100],
    )
    shadow = _dated({d: 0.001 for d in
                     ["2026-07-05", "2026-07-06", "2026-07-07", "2026-07-08",
                      "2026-07-09"]})
    review = build_weekly_review(
        {"crypto_voltarget": object()}, MagicMock(), TradingCalendar(),
        NOW, WEEK_ENDING, shadow_fn=_stub_shadow_series({"crypto_voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    cv = next(a for a in review.accounts if a.label == "crypto_voltarget")
    # 07-10 pairs with covered session 07-09, so nothing is excluded...
    assert cv.excluded_tail_days == []
    assert cv.window is not None
    assert cv.window.start == date(2026, 7, 4)
    assert cv.window.end == date(2026, 7, 10)
    assert cv.window.n_snapshots == 7
    # ...and the day's LAST mark (202_100, not 202_000) closes the week, despite two
    # raw marks landing on 07-10.
    assert cv.paper_week_return == pytest.approx(202_100 / 200_000 - 1.0)


# --------------------------------------------------------------------------
# Measurement batch #3: per-class interval dating, decomposition, unpaired
# --------------------------------------------------------------------------


def _seed_priced_run(reports_dir: Path, label: str, ts: str, *, equity: float,
                     cash: float, symbol: str) -> None:
    """A run report rich enough for the mark-phase decomposition to read it."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy": label, "timestamp": ts, "aborted": False, "equity": equity,
        "plan": {"cash": cash, "current_weights": {symbol: (equity - cash) / equity}},
        "submitted_orders": [],
    }
    stamp = ts.replace(":", "").replace("-", "").replace("T", "")
    (reports_dir / f"run_{label}_{stamp}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_session_for_mark_offsets_by_asset_class() -> None:
    """A 14:00Z equity mark belongs to its own session; a 00:30Z crypto mark to d-1."""
    d = date(2026, 8, 6)
    assert session_for_mark(d, "us_equity") == d
    assert session_for_mark(d, "crypto") == date(2026, 8, 5)
    # An unknown class must not silently shift anything.
    assert session_for_mark(d, "something_else") == d


def test_equity_pairing_is_unchanged_by_the_crypto_fix(tmp_path) -> None:
    """Regression: an equity fixture week pairs mark date d with session d, as before.

    The figures below are what the pre-DEFECT-A code produced for this fixture. Paper
    runs +1.00% across 07-06..07-10; the shadow carries +0.10% on each of the four
    sessions the four paper intervals close on, so shadow_week compounds to 1.001**4
    over exactly (07-06, 07-10] -- no offset, nothing excluded.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_voltarget.parquet", WEEK_DATES,
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    shadow = _dated({d: 0.001 for d in
                     ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
                      "2026-07-10"]})
    review = build_weekly_review(
        {"voltarget": object()}, MagicMock(), TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow_series({"voltarget": shadow}), alert_fn=lambda _a: [],
        data_dir=data_dir, paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.window is not None
    assert (vt.window.start, vt.window.end) == (date(2026, 7, 6), date(2026, 7, 10))
    assert vt.excluded_tail_days == []
    assert vt.unpaired_sessions == []
    # (07-06, 07-10] -> four sessions, NOT the five the series carries.
    assert vt.shadow_week_return == pytest.approx(1.001 ** 4 - 1.0)
    assert vt.divergence_bps == pytest.approx(
        (101_000 / 100_000 - 1.0 - (1.001 ** 4 - 1.0)) * 1e4
    )


def test_crypto_week_pairs_each_mark_with_the_previous_session(tmp_path) -> None:
    """DEFECT A: a crypto week reproduces the diagnosis's LAG-1 pairing.

    Seven marks on 07-04..07-10 close six intervals. Under the fix those pair with
    sessions 07-04..07-09; under the old dating they paired with 07-05..07-10. The
    shadow below is deliberately lopsided -- +5.00% on 07-10 alone, +0.10% elsewhere --
    so the two pairings cannot produce the same number.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_crypto_voltarget.parquet",
                 CRYPTO_WEEK_DATES,
                 [200_000, 200_200, 200_600, 200_800, 201_200, 201_600, 202_000])
    shadow = _dated({"2026-07-03": 0.001, "2026-07-04": 0.001, "2026-07-05": 0.001,
                     "2026-07-06": 0.001, "2026-07-07": 0.001, "2026-07-08": 0.001,
                     "2026-07-09": 0.001, "2026-07-10": 0.05})
    review = build_weekly_review(
        {"crypto_voltarget": object()}, MagicMock(), TradingCalendar(),
        NOW, WEEK_ENDING, shadow_fn=_stub_shadow_series({"crypto_voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    cv = next(a for a in review.accounts if a.label == "crypto_voltarget")
    assert cv.window is not None
    assert (cv.window.start, cv.window.end) == (date(2026, 7, 4), date(2026, 7, 10))
    # LAG-1: sessions (07-03, 07-09] -- six 0.10% days, and NOT the 5% on 07-10.
    assert cv.shadow_week_return == pytest.approx(1.001 ** 6 - 1.0)
    # The old pairing would have swept the 5% session in; prove it did not.
    old_pairing = 1.001 ** 5 * 1.05 - 1.0
    assert cv.shadow_week_return != pytest.approx(old_pairing)
    assert cv.unpaired_sessions == []


def test_crypto_cumulative_is_paired_the_same_way(tmp_path) -> None:
    """The LAG-1 offset applies to the cumulative figure too, not just the week.

    A cumulative divergence paired one way and a weekly paired the other would
    disagree about what the account did over the overlapping sessions.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    _seed_equity(data_dir / "equity_history_crypto_voltarget.parquet",
                 CRYPTO_WEEK_DATES,
                 [200_000, 200_200, 200_600, 200_800, 201_200, 201_600, 202_000])
    shadow = _dated({d: 0.001 for d in
                     ["2026-07-04", "2026-07-05", "2026-07-06", "2026-07-07",
                      "2026-07-08", "2026-07-09", "2026-07-10"]})
    review = build_weekly_review(
        {"crypto_voltarget": object()}, MagicMock(), TradingCalendar(),
        NOW, WEEK_ENDING, shadow_fn=_stub_shadow_series({"crypto_voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    cv = next(a for a in review.accounts if a.label == "crypto_voltarget")
    assert cv.cumulative is not None
    # Inception mark 07-04 pairs with session 07-03; final mark 07-10 with 07-09.
    # (07-03, 07-09] intersected with the seeded series = 07-04..07-09 = six days.
    assert cv.cumulative.shadow_total_return == pytest.approx(1.001 ** 6 - 1.0)


def test_missed_run_is_reported_as_an_unpaired_session(tmp_path) -> None:
    """DEFECT C: the real 2026-08-01 shape -- a missing crypto mark leaves a hole.

    Marks land on 07-30, 07-31 and 08-02..08-06 (no 08-01 run), so the 07-31 00:30Z
    -> 08-02 interval spans two UTC days. Session 07-31 is inside the compared window
    but no mark closes on it, and that must be named rather than folded in silently.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    marks = ["2026-07-30 00:30:00", "2026-07-31 00:30:00", "2026-08-02 22:54:00",
             "2026-08-03 05:49:00", "2026-08-04 00:30:00", "2026-08-05 00:30:00",
             "2026-08-06 00:30:00"]
    _seed_equity(data_dir / "equity_history_crypto_voltarget.parquet", marks,
                 [99_485, 100_242, 98_962, 98_309, 98_950, 99_602, 100_357])
    shadow = _dated({d: 0.001 for d in
                     ["2026-07-29", "2026-07-30", "2026-07-31", "2026-08-01",
                      "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"]})
    review = build_weekly_review(
        {"crypto_voltarget": object()}, MagicMock(), TradingCalendar(),
        datetime(2026, 8, 7, 21, 0, tzinfo=UTC), date(2026, 8, 7),
        shadow_fn=_stub_shadow_series({"crypto_voltarget": shadow}),
        alert_fn=lambda _a: [], data_dir=data_dir,
        paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    cv = next(a for a in review.accounts if a.label == "crypto_voltarget")
    assert cv.window is not None
    assert (cv.window.start, cv.window.end) == (date(2026, 7, 30), date(2026, 8, 6))
    # Six intervals claim 07-30 and 08-01..08-05; 07-31 is left over.
    assert cv.unpaired_sessions == [date(2026, 7, 31)]
    md = render_markdown(review)
    assert "unpaired sessions" in md
    assert "2026-07-31" in md


def test_an_intact_cadence_reports_no_unpaired_sessions(tmp_path) -> None:
    review, *_ = _build_four(tmp_path)
    for acct in review.accounts:
        assert acct.unpaired_sessions == []
    assert "unpaired sessions" not in render_markdown(review)


def test_verdict_is_taken_on_the_residual_not_the_raw_divergence(tmp_path) -> None:
    """DEFECT B: a week whose raw divergence is all mark-phase is TRACKING.

    `trend`'s real shape: 100% SPY, never traded, marked at 14:00Z. The mark prices
    below are the implied 10:00 marks from diagnosis #2's week 2026-08-07 and the
    seeded closes are SPY's own, so the raw divergence is ~+101 bps -- twice the
    threshold -- and the decomposition accounts for ~+100 of it.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    store = ParquetStore(tmp_path / "eod")
    closes = {"2026-07-30": 741.69, "2026-07-31": 747.03, "2026-08-03": 757.67,
              "2026-08-04": 771.33, "2026-08-05": 769.79, "2026-08-06": 768.56}
    _seed_bars(store, "SPY", closes)
    implied = {"2026-07-31": 741.97, "2026-08-03": 753.2344, "2026-08-04": 763.225,
               "2026-08-05": 771.61, "2026-08-06": 770.99}
    qty = 133.028241898
    _seed_equity(data_dir / "equity_history_trend.parquet",
                 [f"{d} 14:00:10" for d in implied],
                 [qty * p for p in implied.values()])
    for day, price in implied.items():
        _seed_priced_run(reports_dir, "trend", f"{day}T14:00:10",
                         equity=qty * price, cash=0.0, symbol="SPY")
    # Shadow = SPY close-to-close on each paired session (w=1, no turnover cost).
    sessions = list(closes)
    shadow = _dated({
        sessions[i]: closes[sessions[i]] / closes[sessions[i - 1]] - 1.0
        for i in range(1, len(sessions))
    })
    review = build_weekly_review(
        {"trend": object()}, store, TradingCalendar(),
        datetime(2026, 8, 7, 21, 0, tzinfo=UTC), date(2026, 8, 7),
        shadow_fn=_stub_shadow_series({"trend": shadow}), alert_fn=lambda _a: [],
        data_dir=data_dir, paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    tr = next(a for a in review.accounts if a.label == "trend")
    assert tr.raw_divergence_bps is not None
    # +102.9 bps here rather than the published +101.39: this fixture's shadow is pure
    # SPY close-to-close, without the real shadow's turnover cost and weight path.
    assert tr.raw_divergence_bps == pytest.approx(102.91, abs=1.0)
    assert tr.predicted_mark_phase_bps == pytest.approx(99.71, abs=1.0)
    assert tr.residual_bps == pytest.approx(3.2, abs=1.0)
    # Raw is beyond the 50 bps threshold; the residual is nowhere near it.
    assert abs(tr.raw_divergence_bps) > review.divergence_threshold_bps
    assert abs(tr.residual_bps) < review.divergence_threshold_bps
    assert tr.verdict == "TRACKING"
    assert tr.decomposition_note is None
    assert review.readiness.blockers == []


def test_a_residual_beyond_threshold_still_diverges(tmp_path) -> None:
    """The instrument was fixed, not loosened: unexplained movement still trips.

    Same static fixture, but the shadow is shifted so ~200 bps of the week cannot be
    accounted for by mark phase.
    """
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    store = ParquetStore(tmp_path / "eod")
    closes = {"2026-07-30": 741.69, "2026-07-31": 747.03, "2026-08-03": 757.67,
              "2026-08-04": 771.33, "2026-08-05": 769.79, "2026-08-06": 768.56}
    _seed_bars(store, "SPY", closes)
    implied = {"2026-07-31": 741.97, "2026-08-03": 753.2344, "2026-08-04": 763.225,
               "2026-08-05": 771.61, "2026-08-06": 770.99}
    qty = 133.028241898
    _seed_equity(data_dir / "equity_history_trend.parquet",
                 [f"{d} 14:00:10" for d in implied],
                 [qty * p for p in implied.values()])
    for day, price in implied.items():
        _seed_priced_run(reports_dir, "trend", f"{day}T14:00:10",
                         equity=qty * price, cash=0.0, symbol="SPY")
    sessions = list(closes)
    shadow = _dated({
        sessions[i]: closes[sessions[i]] / closes[sessions[i - 1]] - 1.0 - 0.005
        for i in range(1, len(sessions))
    })
    fired: list[Alert] = []
    review = build_weekly_review(
        {"trend": object()}, store, TradingCalendar(),
        datetime(2026, 8, 7, 21, 0, tzinfo=UTC), date(2026, 8, 7),
        shadow_fn=_stub_shadow_series({"trend": shadow}), alert_fn=fired.append,
        data_dir=data_dir, paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    tr = next(a for a in review.accounts if a.label == "trend")
    assert tr.residual_bps is not None
    assert abs(tr.residual_bps) > review.divergence_threshold_bps
    assert tr.verdict == "DIVERGING"
    # The alert and the blocker both quote the figure that decided it.
    assert len(fired) == 1
    assert "residual" in fired[0].body
    assert any("residual" in b for b in review.readiness.blockers)


def test_missing_run_reports_fall_back_to_the_raw_verdict(tmp_path) -> None:
    """DEFECT B fallback: no decomposition inputs -> threshold the raw figure, and say so."""
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095, "trend": 0.0})
    vt = next(a for a in review.accounts if a.label == "voltarget")
    # No run reports were seeded, so the decomposition has nothing to read.
    assert vt.predicted_mark_phase_bps is None
    assert vt.residual_bps is None
    assert vt.decomposition_note is not None
    assert "decomposition unavailable" in vt.decomposition_note
    assert vt.raw_divergence_bps == pytest.approx(5.0)
    assert vt.verdict == "TRACKING"  # decided on the raw +5 bps

    tr = next(a for a in review.accounts if a.label == "trend")
    assert tr.residual_bps is None
    assert tr.raw_divergence_bps == pytest.approx(200.0)
    assert tr.verdict == "DIVERGING"  # raw +200 bps, still beyond threshold
    assert any("raw" in b for b in review.readiness.blockers)


def test_markdown_renders_raw_predicted_and_residual_with_one_explanation(tmp_path) -> None:
    review, *_ = _build(tmp_path, shadow_values={"voltarget": 0.0095})
    md = render_markdown(review)
    assert "- raw divergence:" in md
    assert "- predicted mark-phase:" in md
    assert "- residual (verdict is taken on this): " in md
    # Exactly one explanatory line per account section, and it says what decides.
    assert "The threshold applies to the residual." in md or \
           "decomposition unavailable" in md


def test_markdown_explains_the_decomposition_when_it_is_available(tmp_path) -> None:
    data_dir, reports_dir, alerts_path = _base_dirs(tmp_path)
    store = ParquetStore(tmp_path / "eod")
    _seed_bars(store, "SPY", {"2026-07-06": 100.0, "2026-07-07": 101.0,
                              "2026-07-08": 102.0, "2026-07-09": 103.0,
                              "2026-07-10": 104.0})
    _seed_equity(data_dir / "equity_history_voltarget.parquet",
                 [f"{d} 14:00:10" for d in WEEK_DATES],
                 [100_000, 100_250, 100_500, 100_750, 101_000])
    for d, eq in zip(WEEK_DATES, [100_000, 100_250, 100_500, 100_750, 101_000],
                     strict=True):
        _seed_priced_run(reports_dir, "voltarget", f"{d}T14:00:10",
                         equity=float(eq), cash=0.0, symbol="SPY")
    review = build_weekly_review(
        {"voltarget": object()}, store, TradingCalendar(), NOW, WEEK_ENDING,
        shadow_fn=_stub_shadow({"voltarget": 0.0095}), alert_fn=lambda _a: [],
        data_dir=data_dir, paper_reports_dir=reports_dir, alerts_path=alerts_path,
    )
    vt = next(a for a in review.accounts if a.label == "voltarget")
    assert vt.predicted_mark_phase_bps is not None
    assert vt.decomposition_note is None
    md = render_markdown(review)
    assert "The threshold applies to the residual." in md
    assert "decomposition unavailable" not in md


def test_raw_divergence_bps_mirrors_the_published_divergence_field(tmp_path) -> None:
    """``divergence_bps`` is kept for the Glass Box reader and the published files."""
    review, *_ = _build_four(tmp_path, shadow_values={"voltarget": 0.005})
    for acct in review.accounts:
        assert acct.raw_divergence_bps == acct.divergence_bps


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
