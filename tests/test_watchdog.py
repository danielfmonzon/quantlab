"""Watchdog tests: a missed firing is named, a complete window is silent.

Everything is seeded into ``tmp_path`` — no repository state is read, and no alert leaves
the test. The dates below are real ones from the incident this exists for: the crypto tasks
did not fire on 2026-08-01 (a Saturday, host off), and diagnosis #2 traced
``crypto_voltarget``'s only remaining above-threshold residual to that gap.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from quantlab.data.calendar import TradingCalendar
from quantlab.reporting.watchdog import (
    DEFAULT_LOOKBACK_DAYS,
    check_schedule,
    previous_digest_date,
)

EQUITY = ("voltarget", "trend")
CRYPTO = ("crypto_trend", "crypto_voltarget")
ALL_LABELS = EQUITY + CRYPTO


class Tree:
    """The four directories the watchdog reads, all inside tmp_path."""

    def __init__(self, tmp: Path):
        self.paper = tmp / "paper"
        self.weekly = tmp / "weekly"
        self.alerts = tmp / "alerts.jsonl"
        self.digests = tmp / "digests"
        for d in (self.paper, self.weekly, self.digests):
            d.mkdir(parents=True, exist_ok=True)

    def run_report(self, label: str, day: date, hhmmss: str = "140006") -> None:
        stamp = f"{day:%Y%m%d}T{hhmmss}Z"
        (self.paper / f"run_{label}_{stamp}.json").write_text(
            json.dumps({"strategy": label, "timestamp": f"{day}T14:00:06Z"}),
            encoding="utf-8",
        )

    def weekly_review(self, day: date) -> None:
        (self.weekly / f"week_{day:%Y%m%d}.json").write_text("{}", encoding="utf-8")

    def refresh_alert(self, day: date, level: str = "INFO") -> None:
        with self.alerts.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "timestamp": f"{day}T21:35:00+00:00", "level": level,
                "title": "glass box refreshed and deployed", "body": "…",
                "source": "glassbox.refresh",
            }) + "\n")

    def digest(self, day: date) -> None:
        (self.digests / f"digest_{day:%Y%m%d}.json").write_text("{}", encoding="utf-8")

    def check(self, now: datetime, **kw: object):
        return check_schedule(
            now, TradingCalendar(), paper_reports_dir=self.paper,
            weekly_dir=self.weekly, alerts_path=self.alerts, digests_dir=self.digests,
            **kw,  # type: ignore[arg-type]
        )


def _seed_complete(t: Tree, days: list[date], *, weekly_on: list[date] | None = None) -> None:
    """Every expected artifact for ``days``: equity reports on sessions, crypto every day."""
    cal = TradingCalendar()
    for d in days:
        for label in CRYPTO:
            t.run_report(label, d, "003006")
        if d.weekday() <= 4 and cal.sessions_between(d, d):
            for label in EQUITY:
                t.run_report(label, d)
        if d.weekday() == 4:  # Friday
            t.weekly_review(d)
            t.refresh_alert(d)
    for d in weekly_on or []:
        t.weekly_review(d)


# --------------------------------------------------------------------------- #
# The 2026-08-01 case                                                         #
# --------------------------------------------------------------------------- #


def test_a_missing_crypto_day_is_named_and_renders_the_section(tmp_path: Path) -> None:
    """The real incident: no crypto run fired on 2026-08-01, and nothing alerted."""
    t = Tree(tmp_path)
    t.digest(date(2026, 7, 31))                    # window anchor
    days = [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 3)]
    _seed_complete(t, days)
    # ...then remove 08-01's crypto reports, reproducing the miss.
    for p in t.paper.glob("run_crypto_*_20260801*.json"):
        p.unlink()

    now = datetime(2026, 8, 3, 20, 45, tzinfo=UTC)
    report = t.check(now)

    assert report.ok is False
    assert {(m.day, m.label) for m in report.missed} == {
        (date(2026, 8, 1), "crypto_trend"),
        (date(2026, 8, 1), "crypto_voltarget"),
    }
    assert all(m.task == "quantlab-crypto-paper-run" for m in report.missed)
    rendered = "\n".join(report.render())
    assert "MISSED RUNS (2)" in rendered
    assert "2026-08-01" in rendered
    assert "crypto_voltarget" in rendered
    assert report.anchored_to_previous_digest is True
    assert report.window_start == date(2026, 8, 1)


def test_a_complete_window_renders_the_section_with_no_misses(tmp_path: Path) -> None:
    """The section always renders, so a clean window is visibly clean rather than absent."""
    t = Tree(tmp_path)
    t.digest(date(2026, 8, 2))
    _seed_complete(t, [date(2026, 8, 3), date(2026, 8, 4)])
    report = t.check(datetime(2026, 8, 4, 20, 45, tzinfo=UTC))
    assert report.ok is True
    assert report.missed == []
    rendered = "\n".join(report.render())
    assert "Scheduled-task watchdog" in rendered
    assert "MISSED RUNS: none" in rendered
    assert report.firings_checked > 0     # it really did check something


# --------------------------------------------------------------------------- #
# Not-yet-due is not missing                                                  #
# --------------------------------------------------------------------------- #


def test_tasks_not_yet_due_today_are_not_reported_missing(tmp_path: Path) -> None:
    """The digest fires at 16:45 ET (20:45Z), BEFORE the weekly (21:00Z) and refresh (21:30Z).

    Without this gate those two would be reported missed on every Friday digest, and a
    watchdog that cries wolf on schedule is worse than none.
    """
    t = Tree(tmp_path)
    friday = date(2026, 8, 7)
    t.digest(friday - timedelta(days=1))
    # Everything already due by 20:45Z has fired: the 00:30Z crypto runs and the 14:00Z
    # equity runs. The weekly and the refresh have not, and must not be flagged.
    for label in CRYPTO:
        t.run_report(label, friday, "003006")
    for label in EQUITY:
        t.run_report(label, friday)
    report = t.check(datetime(2026, 8, 7, 20, 45, tzinfo=UTC))
    assert report.missed == [], [m.render() for m in report.missed]
    # Fifteen minutes later the weekly IS due and its absence is real.
    later = t.check(datetime(2026, 8, 7, 21, 5, tzinfo=UTC))
    assert [m.task for m in later.missed] == ["quantlab-weekly"]


def test_the_friday_refresh_becomes_due_after_2130z(tmp_path: Path) -> None:
    t = Tree(tmp_path)
    friday = date(2026, 8, 7)
    t.digest(friday - timedelta(days=1))
    for label in CRYPTO:
        t.run_report(label, friday, "003006")
    for label in EQUITY:
        t.run_report(label, friday)
    t.weekly_review(friday)
    assert t.check(datetime(2026, 8, 7, 21, 25, tzinfo=UTC)).missed == []
    due = t.check(datetime(2026, 8, 7, 21, 35, tzinfo=UTC))
    assert [m.task for m in due.missed] == ["quantlab-glassbox-refresh"]


# --------------------------------------------------------------------------- #
# What counts as evidence                                                     #
# --------------------------------------------------------------------------- #


def test_an_aborted_run_still_counts_as_having_fired(tmp_path: Path) -> None:
    """This watchdog looks for SILENCE. An abort already alerted on its own."""
    t = Tree(tmp_path)
    day = date(2026, 8, 3)
    t.digest(day - timedelta(days=1))
    for label in CRYPTO:
        t.run_report(label, day, "003006")
    for label in EQUITY:
        # An aborted report is still a report: the task ran.
        stamp = f"{day:%Y%m%d}T140006Z"
        (t.paper / f"run_{label}_{stamp}.json").write_text(
            json.dumps({"strategy": label, "aborted": True, "abort_stage": "health"}),
            encoding="utf-8",
        )
    assert t.check(datetime(2026, 8, 3, 20, 45, tzinfo=UTC)).missed == []


def test_an_aborted_refresh_counts_too(tmp_path: Path) -> None:
    """The chain alerts on abort as well as on deploy, so either proves it ran."""
    t = Tree(tmp_path)
    friday = date(2026, 8, 7)
    t.digest(friday - timedelta(days=1))
    for label in EQUITY:
        t.run_report(label, friday)
    for label in CRYPTO:
        t.run_report(label, friday, "003006")
    t.weekly_review(friday)
    t.refresh_alert(friday, level="WARNING")
    assert t.check(datetime(2026, 8, 7, 22, 0, tzinfo=UTC)).missed == []


def test_an_unrelated_alert_is_not_mistaken_for_a_refresh(tmp_path: Path) -> None:
    t = Tree(tmp_path)
    friday = date(2026, 8, 7)
    t.digest(friday - timedelta(days=1))
    with t.alerts.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "timestamp": f"{friday}T21:35:00+00:00", "level": "INFO",
            "title": "paper voltarget: 1 order(s) submitted", "body": "…",
            "source": "paper.runner",
        }) + "\n")
    missed = t.check(datetime(2026, 8, 7, 22, 0, tzinfo=UTC)).missed
    assert "quantlab-glassbox-refresh" in {m.task for m in missed}


# --------------------------------------------------------------------------- #
# Calendar and window handling                                                #
# --------------------------------------------------------------------------- #


def test_a_market_holiday_is_not_a_missed_equity_run(tmp_path: Path) -> None:
    """Independence Day 2026 falls on Saturday; the observed holiday is Friday 07-03."""
    t = Tree(tmp_path)
    holiday = date(2026, 7, 3)
    assert TradingCalendar().sessions_between(holiday, holiday) == []
    t.digest(holiday - timedelta(days=1))
    for label in CRYPTO:
        t.run_report(label, holiday, "003006")
    t.weekly_review(holiday)
    t.refresh_alert(holiday)
    report = t.check(datetime(2026, 7, 3, 22, 0, tzinfo=UTC))
    assert [m.render() for m in report.missed] == []


def test_a_weekend_is_not_a_missed_equity_run(tmp_path: Path) -> None:
    t = Tree(tmp_path)
    saturday = date(2026, 8, 8)
    t.digest(date(2026, 8, 7))
    for label in CRYPTO:
        t.run_report(label, saturday, "003006")
    report = t.check(datetime(2026, 8, 8, 22, 0, tzinfo=UTC))
    assert report.missed == []
    assert report.firings_checked == 2   # only the two crypto accounts were expected


def test_without_a_previous_digest_it_uses_a_bounded_lookback(tmp_path: Path) -> None:
    """A first run must not indict the entire history in one alert."""
    t = Tree(tmp_path)   # no digests seeded
    now = datetime(2026, 8, 10, 20, 45, tzinfo=UTC)
    report = t.check(now)
    assert report.anchored_to_previous_digest is False
    assert report.window_start == now.date() - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    assert f"{DEFAULT_LOOKBACK_DAYS}-day lookback" in "\n".join(report.render())


def test_the_rendered_lookback_matches_the_window_actually_used(tmp_path: Path) -> None:
    """A caller may pass its own lookback; the report must not name the default instead."""
    t = Tree(tmp_path)   # no digests, so the lookback path is taken
    report = t.check(datetime(2026, 8, 10, 23, 59, tzinfo=UTC), lookback_days=12)
    assert report.window_start == date(2026, 7, 29)
    assert "12-day lookback" in "\n".join(report.render())
    assert f"{DEFAULT_LOOKBACK_DAYS}-day" not in "\n".join(report.render())


def test_the_window_starts_the_day_after_the_previous_digest(tmp_path: Path) -> None:
    """The previous digest already reported on its own day; don't re-report it."""
    t = Tree(tmp_path)
    t.digest(date(2026, 8, 5))
    report = t.check(datetime(2026, 8, 7, 20, 45, tzinfo=UTC))
    assert report.window_start == date(2026, 8, 6)
    assert report.window_end == date(2026, 8, 7)
    assert all(m.day >= date(2026, 8, 6) for m in report.missed)


def test_previous_digest_date_picks_the_latest_before_today(tmp_path: Path) -> None:
    t = Tree(tmp_path)
    for d in (date(2026, 8, 3), date(2026, 8, 5), date(2026, 8, 6)):
        t.digest(d)
    assert previous_digest_date(t.digests, date(2026, 8, 6)) == date(2026, 8, 5)
    assert previous_digest_date(t.digests, date(2026, 8, 1)) is None


def test_a_same_day_rerun_does_not_produce_an_inverted_window(tmp_path: Path) -> None:
    """Re-running the digest on a day that already has one must stay well-formed."""
    t = Tree(tmp_path)
    t.digest(date(2026, 8, 7))
    report = t.check(datetime(2026, 8, 7, 20, 45, tzinfo=UTC))
    assert report.window_start <= report.window_end


# --------------------------------------------------------------------------- #
# The digest wiring: exactly one WARNING                                      #
# --------------------------------------------------------------------------- #


def test_digest_fires_exactly_one_warning_naming_every_miss(tmp_path: Path) -> None:
    """One alert, not one per miss: a weekend off is a dozen misses for ONE reason."""

    import numpy as np
    import pandas as pd

    from quantlab.reporting.digest import build_digest, render_markdown

    class FakeStore:
        def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
            dates = pd.bdate_range("2026-06-01", periods=40)
            return pd.DataFrame({"date": dates, "adj_close": np.full(40, 100.0)})

        def load_metadata(self, symbol: str) -> None:
            return None

    t = Tree(tmp_path)
    t.digest(date(2026, 7, 31))
    # 08-01 and 08-02 entirely absent for both crypto accounts: four missed firings.
    alerts: list[object] = []
    digest = build_digest(
        {"voltarget": None, "trend": None}, FakeStore(), TradingCalendar(),  # type: ignore[arg-type]
        datetime(2026, 8, 2, 20, 45, tzinfo=UTC),
        data_dir=tmp_path / "data", paper_reports_dir=t.paper,
        weekly_dir=t.weekly, alerts_path=t.alerts, digests_dir=t.digests,
        alert_fn=alerts.append,
    )
    assert digest.watchdog is not None
    assert len(digest.watchdog.missed) == 4
    assert len(alerts) == 1                      # exactly one WARNING
    alert = alerts[0]
    assert alert.level == "WARNING"              # type: ignore[attr-defined]
    assert alert.source == "reporting.watchdog"  # type: ignore[attr-defined]
    body = alert.body                            # type: ignore[attr-defined]
    for day in ("2026-08-01", "2026-08-02"):
        assert day in body
    assert "crypto_voltarget" in body
    # It says what a miss MEANS, so the reader does not go hunting for a failure.
    assert "never ran" in body
    # PROP-4: and it names both observed causes. The wording used to assert the host
    # was off "most often", which the 2026-08-17 outage disproved -- the host was on
    # and awake for all 20 of those misses and the runtime beneath the tasks was gone.
    # A first diagnostic step that points only at the power state is the wrong step.
    assert "host off, or the runtime itself broken" in body
    assert "most often the host was off" not in body

    md = render_markdown(digest)
    assert "## Scheduled-task watchdog" in md
    assert "MISSED RUNS (4)" in md


def test_digest_fires_no_alert_on_a_complete_window(tmp_path: Path) -> None:

    import numpy as np
    import pandas as pd

    from quantlab.reporting.digest import build_digest, render_markdown

    class FakeStore:
        def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
            dates = pd.bdate_range("2026-06-01", periods=40)
            return pd.DataFrame({"date": dates, "adj_close": np.full(40, 100.0)})

        def load_metadata(self, symbol: str) -> None:
            return None

    t = Tree(tmp_path)
    t.digest(date(2026, 8, 2))
    _seed_complete(t, [date(2026, 8, 3)])
    alerts: list[object] = []
    digest = build_digest(
        {"voltarget": None, "trend": None}, FakeStore(), TradingCalendar(),  # type: ignore[arg-type]
        datetime(2026, 8, 3, 20, 45, tzinfo=UTC),
        data_dir=tmp_path / "data", paper_reports_dir=t.paper,
        weekly_dir=t.weekly, alerts_path=t.alerts, digests_dir=t.digests,
        alert_fn=alerts.append,
    )
    assert digest.watchdog is not None and digest.watchdog.ok
    assert alerts == []
    assert "MISSED RUNS: none" in render_markdown(digest)
