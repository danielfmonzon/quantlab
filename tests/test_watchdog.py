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
    ACKNOWLEDGED_DEATHS_PATH,
    BATTERY_HARDENING_APPLIED_AT,
    DEFAULT_LOOKBACK_DAYS,
    SCHED_S_STATUS_CODES,
    AcknowledgedDeath,
    TaskResult,
    audit_task_deaths,
    check_schedule,
    load_acknowledged_deaths,
    parse_schtasks_list,
    previous_digest_date,
    unexplained_task_deaths,
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

    def digest(self, day: date, at: str = "20:45:04.370800+00:00") -> None:
        """A digest for ``day``, stamped with WHEN it ran.

        The default is the real 16:45 ET instant. The stamp matters since PROP-6: a
        digest that ran before one of its own day's firings was due cannot have reported
        on it, and the next window reaches back over that day instead of skipping it.
        """
        (self.digests / f"digest_{day:%Y%m%d}.json").write_text(
            json.dumps({"generated_at": f"{day}T{at}"}), encoding="utf-8"
        )

    def healthy_digest(self, day: date, at: str = "20:45:04.370800+00:00") -> None:
        """A digest for ``day``, PLUS the artifacts for firings due after it ran.

        Since PROP-6 the next window defers-checks exactly those firings, so an anchor
        day that is *meant* to be healthy has to actually be healthy. On a Friday that
        is the weekly review and the refresh alert, both due after 20:45Z.
        """
        self.digest(day, at)
        if day.weekday() == 4:
            self.weekly_review(day)
            self.refresh_alert(day)

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
    t.healthy_digest(date(2026, 7, 31))            # window anchor, a clean Friday
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
    # 07-31, not 08-01: the anchor Friday's weekly and refresh were not yet due when its
    # own digest ran, so they are deferred into this window and the line says so (PROP-6).
    assert report.window_start == date(2026, 7, 31)


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
    t.healthy_digest(date(2026, 8, 7))
    for label in CRYPTO:
        t.run_report(label, saturday, "003006")
    report = t.check(datetime(2026, 8, 8, 22, 0, tzinfo=UTC))
    assert report.missed == []
    # Two crypto accounts on the Saturday, plus Friday's weekly and refresh, which were
    # not yet due when Friday's digest ran and are deferred to this one (PROP-6).
    assert report.firings_checked == 4


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
    t.healthy_digest(date(2026, 7, 31))
    # 08-01 and 08-02 entirely absent for both crypto accounts: four missed firings.
    alerts: list[object] = []
    digest = build_digest(
        {"voltarget": None, "trend": None}, FakeStore(), TradingCalendar(),  # type: ignore[arg-type]
        datetime(2026, 8, 2, 20, 45, tzinfo=UTC),
        data_dir=tmp_path / "data", paper_reports_dir=t.paper,
        weekly_dir=t.weekly, alerts_path=t.alerts, digests_dir=t.digests,
        alert_fn=alerts.append,
        # No scheduler in the test world (PROP-8). Without this the digest reads the
        # REAL Task Scheduler on a Windows dev box and these become host-dependent --
        # they assert about missed FIRINGS, not about task deaths.
        task_results_available=False, task_reader=lambda: [],
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
        # No scheduler in the test world (PROP-8). Without this the digest reads the
        # REAL Task Scheduler on a Windows dev box and these become host-dependent --
        # they assert about missed FIRINGS, not about task deaths.
        task_results_available=False, task_reader=lambda: [],
    )
    assert digest.watchdog is not None and digest.watchdog.ok
    assert alerts == []
    assert "MISSED RUNS: none" in render_markdown(digest)


# --------------------------------------------------------------------------- #
# Deferred not-yet-due firings (PROP-6)                                       #
# --------------------------------------------------------------------------- #

_FRIDAY = date(2026, 8, 28)      # the non-publish
_MONDAY = date(2026, 8, 31)


def test_a_friday_refresh_that_never_ran_is_named_by_the_next_digest(
    tmp_path: Path,
) -> None:
    """The 2026-08-28 case: the refresh left no alert, and this must not stay silent.

    Friday's own digest fires 20:45Z and the refresh is not due until 21:30Z, so that
    digest correctly said nothing. Before PROP-6 the next window opened on the Saturday
    and no digest ever looked at the Friday again; the site went stale for eight days
    with the watchdog reporting clean throughout.
    """
    t = Tree(tmp_path)
    t.digest(_FRIDAY)                      # ran at 20:45Z; refresh due 21:30Z
    t.weekly_review(_FRIDAY)               # the weekly DID run
    _seed_complete(t, [date(2026, 8, 29), date(2026, 8, 30), _MONDAY])

    report = t.check(datetime(2026, 8, 31, 20, 45, tzinfo=UTC))

    assert report.ok is False
    assert [(m.day, m.task) for m in report.missed] == [
        (_FRIDAY, "quantlab-glassbox-refresh")
    ]
    assert "no glassbox.refresh alert" in "\n".join(report.render())


def test_the_same_window_is_clean_when_the_refresh_did_alert(tmp_path: Path) -> None:
    """A wider window must not invent a miss: the healthy Friday still reports clean."""
    t = Tree(tmp_path)
    t.digest(_FRIDAY)
    t.weekly_review(_FRIDAY)
    t.refresh_alert(_FRIDAY)               # the chain alerted, deployed or aborted
    _seed_complete(t, [date(2026, 8, 29), date(2026, 8, 30), _MONDAY])

    report = t.check(datetime(2026, 8, 31, 20, 45, tzinfo=UTC))
    assert report.missed == []
    assert report.ok is True


def test_a_firing_not_yet_due_is_still_skipped_on_the_day_it_fires(
    tmp_path: Path,
) -> None:
    """The not-yet-due rule is untouched: today's 21:30Z refresh is not missing at 20:45Z.

    This is the guarantee PROP-6 must not break. Deferring a check is the point; turning
    it into a daily false alarm is the failure mode the rule exists to prevent.
    """
    t = Tree(tmp_path)
    t.healthy_digest(date(2026, 8, 21))
    _seed_complete(t, [date(2026, 8, 22), date(2026, 8, 23), date(2026, 8, 24),
                       date(2026, 8, 25), date(2026, 8, 26), date(2026, 8, 27)])
    for label in CRYPTO:
        t.run_report(label, _FRIDAY, "003006")
    for label in EQUITY:
        t.run_report(label, _FRIDAY)
    # Friday 20:45Z: the weekly (21:00Z) and refresh (21:30Z) have not fired yet, and
    # neither has left an artifact. Neither may be reported.
    report = t.check(datetime(2026, 8, 28, 20, 45, tzinfo=UTC))
    assert report.missed == []


def test_an_ordinary_weekday_anchor_defers_nothing(tmp_path: Path) -> None:
    """A Thursday digest sees every one of its own day's firings, so nothing carries over.

    The deferral is scoped to firings the previous digest could not have seen. On a day
    with no such firing the window is exactly what it was before PROP-6.
    """
    t = Tree(tmp_path)
    thursday, friday = date(2026, 8, 27), _FRIDAY
    t.digest(thursday)
    _seed_complete(t, [friday])
    report = t.check(datetime(2026, 8, 28, 20, 45, tzinfo=UTC))
    assert report.window_start == friday          # not thursday: nothing was deferred
    assert report.missed == []


# --------------------------------------------------------------------------- #
# Task-death tripwire (PROP-8)                                                #
# --------------------------------------------------------------------------- #

ABORTED = -2147023829          # 0x8007042B ERROR_PROCESS_ABORTED, the 08-28 result


def _results(*rows: tuple[str, int, datetime | None]) -> list[TaskResult]:
    return [TaskResult(task=n, last_result=c, recorded_at=w) for n, c, w in rows]


def _failure_record(t: Tree, day: date, source: str) -> None:
    """An in-code failure record: the task alerting in its OWN voice."""
    with t.alerts.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "timestamp": f"{day}T21:05:00+00:00", "level": "CRITICAL",
            "title": "aborted", "body": "...", "source": source,
        }) + "\n")


def test_a_killed_task_with_no_in_code_record_is_named(tmp_path: Path) -> None:
    """The 2026-08-28 case: the scheduler recorded a death and nothing else did.

    ERROR_PROCESS_ABORTED with no alert and no error log is the signature of a process
    killed outside its own error handling -- the abort path logs AND alerts, so the
    absence of both is what identifies it.
    """
    t = Tree(tmp_path)
    deaths = unexplained_task_deaths(
        _results(("quantlab-glassbox-refresh", ABORTED,
                  datetime(2026, 8, 28, 17, 30))),
        t.alerts, None,
    )
    assert len(deaths) == 1
    assert deaths[0].task == "quantlab-glassbox-refresh"
    assert deaths[0].result_code == ABORTED
    assert deaths[0].hex_code == "0x8007042B"
    assert "0x8007042B" in deaths[0].render()


def test_a_nonzero_result_with_a_matching_record_raises_nothing_extra(
    tmp_path: Path,
) -> None:
    """The task already alerted for itself. A second alert for one failure is noise.

    This is the distinction the whole check turns on: a non-zero result is not by itself
    interesting -- an abort produces one too, and has already been reported.
    """
    t = Tree(tmp_path)
    _failure_record(t, date(2026, 8, 28), "paper.runner")
    deaths = unexplained_task_deaths(
        _results(("quantlab-paper-run", 3, datetime(2026, 8, 28, 10, 0))),
        t.alerts, None,
    )
    assert deaths == []


def test_a_zero_result_is_silent(tmp_path: Path) -> None:
    t = Tree(tmp_path)
    deaths = unexplained_task_deaths(
        _results(
            ("quantlab-paper-run", 0, datetime(2026, 8, 28, 10, 0)),
            ("quantlab-weekly", 0, datetime(2026, 8, 28, 17, 0)),
            ("quantlab-glassbox-refresh", 0, datetime(2026, 8, 28, 17, 30)),
        ),
        t.alerts, None,
    )
    assert deaths == []


def test_an_error_level_log_record_also_counts_as_the_task_speaking(
    tmp_path: Path,
) -> None:
    """Either witness suffices: an alert OR an error-level log line from its logger."""
    t = Tree(tmp_path)
    log_path = tmp_path / "quantlab.jsonl"
    log_path.write_text(json.dumps({
        "timestamp": "2026-08-28T21:30:05.470Z", "level": "error",
        "logger": "quantlab.glassbox.refresh", "event": "glassbox_refresh_aborted",
    }) + "\n", encoding="utf-8")

    deaths = unexplained_task_deaths(
        _results(("quantlab-glassbox-refresh", 1, datetime(2026, 8, 28, 17, 30))),
        t.alerts, log_path,
    )
    assert deaths == []


def test_a_record_from_a_different_task_does_not_excuse_this_one(
    tmp_path: Path,
) -> None:
    """Attribution has teeth: the paper runner's abort says nothing about the refresh."""
    t = Tree(tmp_path)
    _failure_record(t, date(2026, 8, 28), "paper.runner")
    deaths = unexplained_task_deaths(
        _results(("quantlab-glassbox-refresh", ABORTED,
                  datetime(2026, 8, 28, 17, 30))),
        t.alerts, None,
    )
    assert len(deaths) == 1
    assert deaths[0].task == "quantlab-glassbox-refresh"


def test_a_record_on_a_different_day_does_not_excuse_this_one(tmp_path: Path) -> None:
    """Last week's abort is not this week's explanation."""
    t = Tree(tmp_path)
    _failure_record(t, date(2026, 8, 21), "glassbox.refresh")
    deaths = unexplained_task_deaths(
        _results(("quantlab-glassbox-refresh", ABORTED,
                  datetime(2026, 8, 28, 17, 30))),
        t.alerts, None,
    )
    assert len(deaths) == 1


def test_the_check_reports_unavailable_rather_than_clean_without_a_scheduler(
    tmp_path: Path,
) -> None:
    """On the Linux CI runner there is no scheduler, and that is not a clean bill.

    An empty result list and "there is nothing here to read" are different facts.
    Reporting the second as the first is how a check that has stopped working starts
    looking like one that is passing.
    """
    t = Tree(tmp_path)
    report = t.check(
        datetime(2026, 8, 28, 20, 45, tzinfo=UTC),
        task_results_available=False,
        task_reader=lambda: [],
    )
    assert report.task_results_available is False
    assert report.deaths == []
    rendered = "\n".join(report.render())
    assert "unavailable on this host" in rendered
    assert "TASK DEATHS: none" not in rendered


def test_a_clean_scheduler_renders_the_section_as_clean(tmp_path: Path) -> None:
    """The section always renders, so a check that stops running is visible."""
    t = Tree(tmp_path)
    report = t.check(
        datetime(2026, 8, 28, 20, 45, tzinfo=UTC),
        task_results_available=True,
        task_reader=lambda: [
            TaskResult(task="quantlab-paper-run", last_result=0,
                       recorded_at=datetime(2026, 8, 28, 10, 0)),
        ],
    )
    assert report.deaths == []
    assert "TASK DEATHS: none" in "\n".join(report.render())


def test_parse_schtasks_list_reads_only_quantlab_tasks() -> None:
    """Parsing is unit-tested against captured output, so CI exercises it too."""
    captured = "\r\n".join([
        "TaskName:      \\quantlab-glassbox-refresh",
        "Last Run Time: 8/28/2026 5:30:00 PM",
        "Last Result:   -2147023829",
        "",
        "TaskName:      \\quantlab-paper-run",
        "Last Run Time: 8/28/2026 10:00:00 AM",
        "Last Result:   0",
        "",
        "TaskName:      \\SomeVendorUpdater",
        "Last Run Time: 8/28/2026 3:00:00 AM",
        "Last Result:   1",
        "",
    ])
    parsed = parse_schtasks_list(captured)
    assert [p.task for p in parsed] == [
        "quantlab-glassbox-refresh", "quantlab-paper-run",
    ]
    assert parsed[0].last_result == ABORTED
    assert parsed[0].recorded_at == datetime(2026, 8, 28, 17, 30)
    assert parsed[1].last_result == 0


def test_an_unparseable_block_is_skipped_not_guessed_at() -> None:
    """A wrong code would fire a CRITICAL naming a failure that never happened."""
    parsed = parse_schtasks_list("\r\n".join([
        "TaskName:      \\quantlab-weekly",
        "Last Run Time: N/A",
        "Last Result:   not-a-number",
        "",
    ]))
    assert parsed == []


def test_the_missed_firing_check_is_unchanged_by_the_tripwire(tmp_path: Path) -> None:
    """PROP-8 is additive: the PROP-6 window and its single WARNING are untouched."""
    t = Tree(tmp_path)
    t.digest(_FRIDAY)
    t.weekly_review(_FRIDAY)
    _seed_complete(t, [date(2026, 8, 29), date(2026, 8, 30), _MONDAY])

    report = t.check(
        datetime(2026, 8, 31, 20, 45, tzinfo=UTC),
        task_results_available=True,
        task_reader=lambda: [],
    )
    assert [(m.day, m.task) for m in report.missed] == [
        (_FRIDAY, "quantlab-glassbox-refresh")
    ]
    assert report.deaths == []


# --------------------------------------------------------------------------- #
# Tripwire precision (PROP-11)                                                #
# --------------------------------------------------------------------------- #
#
# The tripwire's first two live firings, in `digest_20260831`, were both false. The
# records below are that digest's, verbatim, and they are the fixture: one CRITICAL was
# dispatched over a status code the digest read about itself mid-run, and over the known
# 2026-08-28 death that the alert's own body explained was not a recurrence.

RUNNING = 267009                 # 0x00041301 SCHED_S_TASK_RUNNING
_NOW_MONDAY = datetime(2026, 8, 31, 20, 45, 4, tzinfo=UTC)


def _todays_records() -> list[TaskResult]:
    """The two rows Windows Task Scheduler carried when digest_20260831 ran."""
    return _results(
        ("quantlab-digest", RUNNING, datetime(2026, 8, 31, 16, 45)),
        ("quantlab-glassbox-refresh", ABORTED, datetime(2026, 8, 28, 17, 30)),
    )


def _clean_window(t: Tree) -> None:
    """A window with no missed firing, so the only alerts possible are death alerts.

    Anchored on the SUNDAY digest rather than the Friday one, deliberately. Anchoring on
    the Friday would require seeding that Friday's `glassbox.refresh` alert to keep the
    window clean -- and under PROP-8 that same alert is an in-code record accounting for
    the 08-28 death, which would explain the death away and leave this fixture asserting
    silence for the wrong reason.
    """
    t.digest(date(2026, 8, 30))
    _seed_complete(t, [date(2026, 8, 30), _MONDAY])


def _digest_alerts(
    t: Tree, records: list[TaskResult], **kw: object
) -> tuple[list, object]:
    """Run the real `build_digest` over ``records`` and collect what it dispatched."""
    import numpy as np
    import pandas as pd

    from quantlab.reporting.digest import build_digest

    class FakeStore:
        def load(self, symbol: str, start: object = None, end: object = None):
            dates = pd.bdate_range("2026-06-01", periods=40)
            return pd.DataFrame({"date": dates, "adj_close": np.full(40, 100.0)})

        def load_metadata(self, symbol: str) -> None:
            return None

    alerts: list = []
    digest = build_digest(
        {"voltarget": None, "trend": None}, FakeStore(), TradingCalendar(),  # type: ignore[arg-type]
        _NOW_MONDAY,
        data_dir=t.paper.parent / "data", paper_reports_dir=t.paper,
        weekly_dir=t.weekly, alerts_path=t.alerts, digests_dir=t.digests,
        alert_fn=alerts.append,
        task_results_available=True, task_reader=lambda: records,
        **kw,  # type: ignore[arg-type]
    )
    return alerts, digest


def test_todays_two_records_fire_no_critical_and_one_known_warning(
    tmp_path: Path,
) -> None:
    """The live fixture: exactly what the 2026-08-31 digest saw, and what it should say.

    Zero CRITICAL. One WARNING, and only for the 2026-08-28 refresh, named as the known
    pre-hardening death rather than as a recurrence. The digest's own SCHED_S_TASK_RUNNING
    row is not a death at all and must not appear anywhere.

    The ledger is deliberately absent here: this fixture pins the status-code and dating
    rules on their own, so a later change to the ledger cannot make it pass vacuously.
    """
    t = Tree(tmp_path)
    _clean_window(t)

    alerts, digest = _digest_alerts(
        t, _todays_records(), acknowledged_deaths_path=tmp_path / "no-ledger.json",
    )

    assert [a.level for a in alerts] == ["WARNING"]          # zero CRITICAL
    alert = alerts[0]
    assert alert.source == "reporting.watchdog"
    assert "not a recurrence" in alert.title
    assert "quantlab-glassbox-refresh" in alert.body
    assert "0x8007042B" in alert.body
    # The digest's own in-flight row is nowhere: not in the alert, not in the report.
    assert "quantlab-digest" not in alert.body
    assert "267009" not in alert.body

    assert digest.watchdog is not None
    assert digest.watchdog.recurrences == []
    assert [d.task for d in digest.watchdog.known_deaths] == ["quantlab-glassbox-refresh"]
    rendered = "\n".join(digest.watchdog.render())
    assert "KNOWN TASK DEATHS (1)" in rendered
    assert "pre-hardening" in rendered
    assert "MISSED RUNS: none" in rendered                   # PROP-6 half untouched


def test_the_same_two_records_are_silent_against_the_shipped_ledger(
    tmp_path: Path,
) -> None:
    """With the 08-28 death acknowledged, the digest dispatches nothing and still shows it.

    This reads the ledger the repository actually ships, so it also asserts the seed: a
    ruling that was recorded but never entered would fail here.
    """
    t = Tree(tmp_path)
    _clean_window(t)

    alerts, digest = _digest_alerts(
        t, _todays_records(), acknowledged_deaths_path=ACKNOWLEDGED_DEATHS_PATH,
    )

    assert alerts == []
    assert digest.watchdog is not None
    assert digest.watchdog.deaths == []
    assert [d.task for d in digest.watchdog.acknowledged_deaths] == [
        "quantlab-glassbox-refresh"
    ]
    rendered = "\n".join(digest.watchdog.render())
    assert "acknowledged and ruled (1)" in rendered
    assert "0x8007042B" in rendered            # silenced, never hidden
    assert "TASK DEATHS: none" not in rendered


def test_a_post_hardening_death_still_fires_exactly_one_critical(
    tmp_path: Path,
) -> None:
    """The case the tripwire exists for is untouched: a new death still escalates."""
    t = Tree(tmp_path)
    _clean_window(t)
    records = _todays_records() + _results(
        ("quantlab-paper-run", ABORTED, datetime(2026, 8, 31, 10, 0)),
    )

    alerts, digest = _digest_alerts(
        t, records, acknowledged_deaths_path=ACKNOWLEDGED_DEATHS_PATH,
    )

    assert [a.level for a in alerts] == ["CRITICAL"]
    alert = alerts[0]
    assert "recurrence" in alert.title and "Quant Lead" in alert.title
    assert "quantlab-paper-run" in alert.body
    assert "0x8007042B" in alert.body
    assert digest.watchdog is not None
    assert [d.task for d in digest.watchdog.recurrences] == ["quantlab-paper-run"]
    assert "AFTER the battery hardening" in "\n".join(digest.watchdog.render())


def test_no_scheduler_status_code_is_ever_a_death(tmp_path: Path) -> None:
    """All seven SCHED_S_* codes describe a task's state, not the end of a run."""
    t = Tree(tmp_path)
    for code, name in SCHED_S_STATUS_CODES.items():
        deaths = unexplained_task_deaths(
            _results(("quantlab-weekly", code, datetime(2026, 8, 28, 17, 0))),
            t.alerts, None,
        )
        assert deaths == [], f"{name} ({code:#010x}) was read as a death"


def test_the_status_family_is_not_a_blanket_mute(tmp_path: Path) -> None:
    """A real death in the same read is still named; only the status rows are dropped."""
    t = Tree(tmp_path)
    deaths = unexplained_task_deaths(
        _results(
            ("quantlab-weekly", 0x00041303, datetime(2026, 8, 28, 17, 0)),
            ("quantlab-glassbox-refresh", ABORTED, datetime(2026, 9, 4, 17, 30)),
        ),
        t.alerts, None,
    )
    assert [d.task for d in deaths] == ["quantlab-glassbox-refresh"]


def test_the_digest_does_not_audit_its_own_in_flight_run(tmp_path: Path) -> None:
    """Its own row describes the run doing the looking, whatever the code happens to be.

    Asserted with ERROR_PROCESS_ABORTED rather than the status code, so this proves the
    self rule on its own rather than borrowing the SCHED_S_* one.
    """
    t = Tree(tmp_path)
    deaths = unexplained_task_deaths(
        _results(("quantlab-digest", ABORTED, datetime(2026, 8, 31, 16, 45))),
        t.alerts, None, now=_NOW_MONDAY,
    )
    assert deaths == []


def test_a_digest_death_on_a_previous_day_is_still_named(tmp_path: Path) -> None:
    """The rule is scoped to the audit's own day. Yesterday's death is not in flight."""
    t = Tree(tmp_path)
    deaths = unexplained_task_deaths(
        _results(("quantlab-digest", ABORTED, datetime(2026, 8, 30, 16, 45))),
        t.alerts, None, now=_NOW_MONDAY,
    )
    assert [d.task for d in deaths] == ["quantlab-digest"]


def test_a_death_before_the_hardening_is_known_and_after_it_is_a_recurrence(
    tmp_path: Path,
) -> None:
    """The whole distinction, on one task, one code, two instants."""
    t = Tree(tmp_path)
    before = BATTERY_HARDENING_APPLIED_AT - timedelta(days=2)
    after = BATTERY_HARDENING_APPLIED_AT + timedelta(days=5)
    audit = audit_task_deaths(
        _results(
            ("quantlab-glassbox-refresh", ABORTED, before),
            ("quantlab-weekly", ABORTED, after),
        ),
        t.alerts, None,
    )
    by_task = {d.task: d.post_hardening for d in audit.deaths}
    assert by_task == {"quantlab-glassbox-refresh": False, "quantlab-weekly": True}


def test_a_death_with_no_readable_instant_is_treated_as_a_recurrence(
    tmp_path: Path,
) -> None:
    """Unknown instant takes the louder reading; the quiet one would lose a real death."""
    t = Tree(tmp_path)
    deaths = unexplained_task_deaths(
        _results(("quantlab-weekly", ABORTED, None)), t.alerts, None,
    )
    assert [d.post_hardening for d in deaths] == [True]


def test_an_acknowledgement_must_match_task_result_and_instant_together(
    tmp_path: Path,
) -> None:
    """A ledger keyed loosely would mute the NEXT death too, which is the point of it.

    Same task, same result, one week later: not the death that was ruled on, and it
    alerts.
    """
    t = Tree(tmp_path)
    ruled = AcknowledgedDeath(
        task="quantlab-glassbox-refresh", result_code=ABORTED,
        recorded_at=datetime(2026, 8, 28, 17, 30), ruling="the 08-28 non-publish",
    )
    audit = audit_task_deaths(
        _results(("quantlab-glassbox-refresh", ABORTED, datetime(2026, 9, 4, 17, 30))),
        t.alerts, None, acknowledged=[ruled],
    )
    assert audit.acknowledged == []
    assert [d.task for d in audit.deaths] == ["quantlab-glassbox-refresh"]


def test_a_malformed_ledger_acknowledges_nothing(tmp_path: Path) -> None:
    """Every failure to read the ledger costs an alert that was already ruled on.

    The opposite bias -- a typo silencing a real death -- is the one that cannot be
    allowed, so the loader fails toward alerting.
    """
    bad = tmp_path / "ledger.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert load_acknowledged_deaths(bad) == []
    assert load_acknowledged_deaths(tmp_path / "absent.json") == []

    half = tmp_path / "half.json"
    half.write_text(
        json.dumps({"acknowledged": [
            {"task": "quantlab-weekly"},                       # no result, no instant
            {"task": "quantlab-weekly", "result_code": 1,
             "recorded_at": "2026-09-04T17:00:00"},
        ]}), encoding="utf-8",
    )
    # The unreadable row is dropped; its neighbour survives.
    assert [a.task for a in load_acknowledged_deaths(half)] == ["quantlab-weekly"]


def test_the_shipped_ledger_carries_the_08_28_refresh_death() -> None:
    """The seed, asserted against the file the repository actually ships."""
    entries = load_acknowledged_deaths(ACKNOWLEDGED_DEATHS_PATH)
    assert any(
        e.task == "quantlab-glassbox-refresh"
        and e.result_code == ABORTED
        and e.recorded_at == datetime(2026, 8, 28, 17, 30)
        and e.ruling
        for e in entries
    )


def test_the_missed_firing_half_is_unchanged_by_the_precision_work(
    tmp_path: Path,
) -> None:
    """PROP-11 is subtractive on deaths only: PROP-6's window and WARNING are untouched."""
    t = Tree(tmp_path)
    t.digest(_FRIDAY)
    t.weekly_review(_FRIDAY)
    _seed_complete(t, [date(2026, 8, 29), date(2026, 8, 30), _MONDAY])

    report = t.check(
        _NOW_MONDAY, task_results_available=True, task_reader=_todays_records,
    )
    assert [(m.day, m.task) for m in report.missed] == [
        (_FRIDAY, "quantlab-glassbox-refresh")
    ]
    assert report.recurrences == []
    assert len(report.known_deaths) == 1
