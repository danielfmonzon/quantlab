"""Scheduled-task watchdog: did every task that should have fired leave a trace?

WHY THIS EXISTS. Every task runs from Windows Task Scheduler on one workstation, and
``StartWhenAvailable`` cannot run anything while that machine is OFF. On 2026-08-01 no
crypto run fired at all. Nothing alerted, because nothing failed — the pipeline was simply
never invoked, and a system that only reports on the runs it performs is blind to the runs
it did not. The cost was concrete: a 70.40h mark interval, a 6.92h one, and a shadow session
with no paper counterpart, which divergence diagnosis #2 traced to `crypto_voltarget`'s only
remaining above-threshold residual.

So the daily digest now asks the opposite question. Instead of "how did today's runs go",
it asks "which firings should have happened since the last digest, and is there an artifact
for each". A missing one becomes a MISSED RUNS section and exactly one WARNING.

WHAT COUNTS AS EVIDENCE, per task (``scheduling.tasks.SCHEDULE`` is the single source of
truth for when each fires):

* ``quantlab-paper-run`` / ``quantlab-crypto-paper-run`` -- one ``run_{label}_*.json`` per
  approved account of that asset class, dated that day. An ABORTED report still counts: the
  task fired, and its abort already alerted on its own. This watchdog is about silence.
* ``quantlab-weekly``          -- ``reports/weekly/week_{YYYYMMDD}.json`` for that Friday.
* ``quantlab-glassbox-refresh``-- a ``glassbox.refresh`` alert record for that day. The
  chain alerts on success AND on abort, so the alert is present either way; its absence
  means the chain never ran.

NOT-YET-DUE IS NOT MISSING. The digest fires at 16:45 ET, before the crypto run (20:30 ET),
the weekly (17:00) and the refresh (17:30). A check that ignored the clock would report
those three as missed every single weekday, and a watchdog that cries wolf daily is worse
than none. Every expectation is therefore gated on its scheduled instant having passed.

...AND NOT-YET-DUE MUST NOT BECOME NEVER-CHECKED (PROP-6). Skipping a firing today is only
honest if something checks it later. The window used to open the day AFTER the previous
digest, on the premise that that digest had already covered its own day — false for exactly
the firings it skipped as not yet due, which then fell between two windows and were checked
by nothing, ever. Both Friday jobs lived there. On 2026-08-28 the Glass Box refresh died
after writing its snapshot, alerted nothing, and `digest_20260828` reported MISSED RUNS none
over four checked firings while the published site went stale for eight days. The window now
reaches back over the previous digest's own day when that digest ran before one of its
firings was due (``previous_digest_instant``), so the skip defers the check instead of
cancelling it.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from pydantic import BaseModel

from quantlab.config import APPROVED_STRATEGIES, account_asset_class
from quantlab.data.calendar import MarketCalendar
from quantlab.logging_setup import get_logger
from quantlab.scheduling.tasks import (
    DAYS_DAILY,
    DAYS_FRIDAY,
    DAYS_WEEKDAYS,
    PRODUCES_REFRESH_ALERT,
    PRODUCES_RUN_REPORT,
    PRODUCES_WEEKLY_REVIEW,
    SCHEDULE,
    ScheduledTask,
)

log = get_logger("quantlab.watchdog")

# How far back to look when there is no previous digest to anchor to. Bounded so a first
# run, or a long gap, does not indict the entire history in one alert.
DEFAULT_LOOKBACK_DAYS = 7

_FRIDAY_WEEKDAY = 4
_REFRESH_ALERT_SOURCE = "glassbox.refresh"

# Which alert sources and logger names each task speaks through when it fails on its OWN
# terms (PROP-8). A non-zero scheduler result whose day carries one of these is already
# accounted for -- the task alerted for itself -- and must not alert a second time. Keyed
# by task name so the mapping is reviewable in one place; `scheduling.tasks` is a
# firewall-forbidden path and is not touched.
_FAILURE_SOURCES_BY_TASK: dict[str, tuple[str, ...]] = {
    "quantlab-paper-run": ("paper.runner", "quantlab.paper"),
    "quantlab-crypto-paper-run": ("paper.runner", "quantlab.paper"),
    "quantlab-weekly": ("reporting.weekly", "quantlab.weekly"),
    "quantlab-digest": ("reporting.digest", "quantlab.digest", "reporting.watchdog"),
    "quantlab-glassbox-refresh": ("glassbox.refresh", "quantlab.glassbox.refresh"),
}

# Log levels that count as the system saying "I failed" in its own voice.
_FAILURE_LEVELS = frozenset({"error", "critical"})

_TASK_NAME_PREFIX = "quantlab-"

# schtasks renders its own local timestamps; none of these carry a zone.
_SCHTASKS_STAMP_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


class TaskResult(BaseModel):
    """One task's last recorded outcome, as the SCHEDULER saw it.

    This is the only witness to a run that died outside its own error handling: the
    process left no artifact and no log line, but the scheduler still wrote down what
    became of it.
    """

    task: str
    last_result: int
    recorded_at: datetime | None = None


class TaskDeath(BaseModel):
    """A non-zero scheduler result that the system itself never accounted for."""

    task: str
    result_code: int
    recorded_at: datetime | None = None

    @property
    def hex_code(self) -> str:
        """The result as Windows reports it, which is the form that is searchable."""
        return f"0x{self.result_code & 0xFFFFFFFF:08X}"

    def render(self) -> str:
        when = self.recorded_at.isoformat() if self.recorded_at else "unknown instant"
        return f"{self.task} - result {self.result_code} ({self.hex_code}) at {when}"


# Injected so the parsing is testable with no scheduler present, and so the Linux CI
# runner exercises the same code path the workstation does.
TaskResultReader = Callable[[], list[TaskResult]]


def schtasks_available() -> bool:
    """Whether this host has the scheduler this check reads.

    Kept as its own predicate rather than folded into the reader: a host without a
    scheduler must report the check as UNAVAILABLE, not as clean. An empty result list
    and "there is nothing to read here" are different facts, and conflating them is how
    a silent check starts looking like a passing one.
    """
    return platform.system() == "Windows"


def _field(block: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)}:\s*(.*)$", block, re.MULTILINE)
    return match.group(1) if match else None


def _parse_local_stamp(raw: str | None) -> datetime | None:
    """A schtasks local timestamp, or None when absent or unparseable.

    Never raises: this only decorates an alert, and a timestamp that cannot be read must
    not prevent the alert that carries it.
    """
    if not raw or raw.strip() in {"", "N/A", "Never"}:
        return None
    for fmt in _SCHTASKS_STAMP_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    return None


def parse_schtasks_list(text: str) -> list[TaskResult]:
    """Parse ``schtasks /query /fo LIST /v`` output into one entry per quantlab task.

    Separate from the subprocess call so the parsing is unit-testable against captured
    output on any platform. A block whose fields cannot be read is skipped rather than
    guessed at -- a wrong result code would fire a CRITICAL naming a failure that never
    happened.
    """
    results: list[TaskResult] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        name = _field(block, "TaskName")
        if not name:
            continue
        short = name.strip().lstrip("\\").strip()
        if not short.startswith(_TASK_NAME_PREFIX):
            continue
        raw_result = _field(block, "Last Result")
        if raw_result is None:
            continue
        try:
            code = int(raw_result.strip())
        except ValueError:
            continue
        results.append(TaskResult(
            task=short, last_result=code,
            recorded_at=_parse_local_stamp(_field(block, "Last Run Time")),
        ))
    return results


def _default_task_reader() -> list[TaskResult]:
    """Every ``quantlab-*`` task's Last Result, read from Windows Task Scheduler."""
    if not schtasks_available():
        return []
    try:
        proc = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST", "/v"],
            capture_output=True, text=True, shell=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return parse_schtasks_list(proc.stdout or "")


class MissedRun(BaseModel):
    """One firing that should have left an artifact behind and did not."""

    task: str
    day: date
    # The account this expectation belongs to, for per-account tasks.
    label: str | None = None
    expected: str

    def render(self) -> str:
        who = f" [{self.label}]" if self.label else ""
        return f"{self.day.isoformat()}  {self.task}{who} — {self.expected}"


class WatchdogReport(BaseModel):
    """What the watchdog checked, and what it could not find."""

    window_start: date
    window_end: date
    # Anchored to the previous digest when one exists; otherwise a bounded lookback.
    anchored_to_previous_digest: bool = False
    firings_checked: int = 0
    missed: list[MissedRun] = []
    # Non-zero scheduler results the system never accounted for (PROP-8). Separate from
    # ``missed`` because they are the opposite failure: the task DID fire, and died
    # somewhere its own error handling could not reach.
    deaths: list[TaskDeath] = []
    # False when this host has no scheduler to read. The check then says so rather than
    # reporting an empty list as a clean bill of health.
    task_results_available: bool = True

    @property
    def ok(self) -> bool:
        return not self.missed

    def render(self) -> list[str]:
        """Markdown lines. Always renders, so a clean window is visibly clean."""
        lines = ["## Scheduled-task watchdog"]
        # Derived from the window actually used, not from the default: a caller may pass
        # its own lookback, and a report that names a length it did not use is a lie.
        span_days = (self.window_end - self.window_start).days
        anchor = (
            "since the previous digest" if self.anchored_to_previous_digest
            else f"{span_days}-day lookback (no previous digest found)"
        )
        lines.append(
            f"- window: {self.window_start.isoformat()} -> {self.window_end.isoformat()} "
            f"({anchor})"
        )
        lines.append(f"- expected firings checked: {self.firings_checked}")
        if not self.missed:
            lines.append("- **MISSED RUNS: none** — every expected firing left an artifact.")
        else:
            lines.append(f"- **MISSED RUNS ({len(self.missed)})**")
            for m in self.missed:
                lines.append(f"  - {m.render()}")
        lines.extend(self._death_lines())
        lines.append("")
        return lines

    def _death_lines(self) -> list[str]:
        """The task-death section. Always rendered, including when it cannot run.

        A check whose output only appears on failure is one nobody notices has stopped
        working — the same reasoning that makes the missed-runs section render on a
        clean window.
        """
        if not self.task_results_available:
            return ["- task-death tripwire: **unavailable on this host** "
                    "(no Windows Task Scheduler to read)"]
        if not self.deaths:
            return ["- **TASK DEATHS: none** — every non-zero result was one the "
                    "system reported itself."]
        lines = [f"- **TASK DEATHS ({len(self.deaths)}) — died outside their own "
                 f"error handling**"]
        lines.extend(f"  - {d.render()}" for d in self.deaths)
        return lines


def _runs_on(task: ScheduledTask, day: date, calendar: MarketCalendar) -> bool:
    """Whether ``task`` was scheduled to fire on ``day``."""
    if task.days == DAYS_DAILY:
        return True
    if task.days == DAYS_FRIDAY:
        return day.weekday() == _FRIDAY_WEEKDAY
    if task.days == DAYS_WEEKDAYS:
        if day.weekday() > _FRIDAY_WEEKDAY:
            return False
        # A weekday task on the equity path only fires usefully on a SESSION; a holiday
        # Monday is not a missed run. The calendar decides, never a weekday count.
        if task.asset_class == "us_equity":
            return bool(calendar.sessions_between(day, day))
        return True
    return False


def _due_at(task: ScheduledTask, day: date) -> datetime:
    """The UTC instant ``task`` was scheduled to fire on ``day``."""
    return datetime.combine(day, time(0, 0), tzinfo=UTC) + timedelta(
        minutes=task.utc_minute_of_day
    )


def _labels_for(task: ScheduledTask) -> list[str]:
    if task.asset_class is None:
        return []
    return [s for s in APPROVED_STRATEGIES if account_asset_class(s) == task.asset_class]


def _run_report_days(paper_reports_dir: Path, label: str) -> set[date]:
    """Days on which ``label`` has at least one run report, aborted or not."""
    days: set[date] = set()
    if not paper_reports_dir.exists():
        return days
    for path in paper_reports_dir.glob(f"run_{label}_*.json"):
        # The filename stamp is authoritative and cheap; the payload is not read, so a
        # truncated or unreadable report still counts as evidence the task fired.
        stem = path.stem[len(f"run_{label}_"):]
        try:
            days.add(datetime.strptime(stem[:8], "%Y%m%d").date())
        except ValueError:
            continue
    return days


def _weekly_review_days(weekly_dir: Path) -> set[date]:
    days: set[date] = set()
    if not weekly_dir.exists():
        return days
    for path in weekly_dir.glob("week_*.json"):
        try:
            days.add(datetime.strptime(path.stem[len("week_"):], "%Y%m%d").date())
        except ValueError:
            continue
    return days


def _refresh_alert_days(alerts_path: Path) -> set[date]:
    """Days carrying a ``glassbox.refresh`` alert — the chain's deploy-log entry.

    The chain alerts on success and on abort alike, so presence proves it ran and says
    nothing about whether it deployed. That is the right test here: this watchdog is
    looking for silence, and an aborted refresh has already raised its own WARNING.
    """
    days: set[date] = set()
    if not alerts_path.exists():
        return days
    for line in alerts_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("source") != _REFRESH_ALERT_SOURCE:
            continue
        ts = record.get("timestamp")
        if isinstance(ts, str):
            try:
                days.add(datetime.fromisoformat(ts).date())
            except ValueError:
                continue
    return days


def _failure_record_days(
    task: str, alerts_path: Path, log_path: Path | None
) -> set[date]:
    """Days on which ``task`` reported a failure IN ITS OWN VOICE.

    Two witnesses, either sufficient: an alert whose ``source`` belongs to this task, or
    a log record at error/critical level from one of its loggers. Both are things only
    running code can write, which is exactly the point — their absence beside a non-zero
    scheduler result is what distinguishes "it failed and said so" from "it was killed".

    A malformed line is skipped, not fatal. This decides whether to RAISE an alert, so
    an unreadable record biases toward raising one, which is the safe direction.
    """
    sources = _FAILURE_SOURCES_BY_TASK.get(task, ())
    if not sources:
        return set()
    days: set[date] = set()

    def _harvest(path: Path, is_log: bool) -> None:
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if is_log:
                if str(record.get("level", "")).lower() not in _FAILURE_LEVELS:
                    continue
                origin = str(record.get("logger", ""))
            else:
                origin = str(record.get("source", ""))
            if not any(origin == s or origin.startswith(f"{s}.") for s in sources):
                continue
            stamp = record.get("timestamp")
            if not isinstance(stamp, str):
                continue
            try:
                days.add(datetime.fromisoformat(stamp.replace("Z", "+00:00")).date())
            except ValueError:
                continue

    _harvest(alerts_path, is_log=False)
    if log_path is not None:
        _harvest(log_path, is_log=True)
    return days


def unexplained_task_deaths(
    results: list[TaskResult],
    alerts_path: Path,
    log_path: Path | None,
) -> list[TaskDeath]:
    """Non-zero scheduler results with no in-code failure record to account for them.

    A non-zero result WITH such a record raises nothing here: the task already alerted
    for itself, and a second alert for one failure teaches its reader to discount both.
    A zero result is silent. What is left is the case the 2026-08-28 non-publish fell
    into — the scheduler recorded ``ERROR_PROCESS_ABORTED`` and the system recorded
    nothing at all, because the process that would have written the record was gone.
    """
    deaths: list[TaskDeath] = []
    for result in results:
        if result.last_result == 0:
            continue
        day = result.recorded_at.date() if result.recorded_at else None
        explained_on = _failure_record_days(result.task, alerts_path, log_path)
        if day is not None and day in explained_on:
            continue
        if day is None and explained_on:
            # No instant to match against; any record for this task is taken as
            # accounting for it rather than firing a CRITICAL on a guess.
            continue
        deaths.append(TaskDeath(
            task=result.task, result_code=result.last_result,
            recorded_at=result.recorded_at,
        ))
    return sorted(deaths, key=lambda d: (d.task, d.result_code))


def previous_digest_instant(digests_dir: Path, day: date) -> datetime | None:
    """When the digest dated ``day`` actually ran, read from its own JSON.

    The DATE alone cannot say whether that digest was able to see a given firing; the
    instant can. Returns None when the digest is absent, unreadable, or predates the
    ``generated_at`` field, and the caller treats that as "cannot tell".
    """
    path = digests_dir / f"digest_{day:%Y%m%d}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    stamp = payload.get("generated_at")
    if not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def previous_digest_date(digests_dir: Path, before: date) -> date | None:
    """Date of the most recent digest strictly before ``before``, if any."""
    if not digests_dir.exists():
        return None
    found: list[date] = []
    for path in digests_dir.glob("digest_*.json"):
        try:
            d = datetime.strptime(path.stem[len("digest_"):], "%Y%m%d").date()
        except ValueError:
            continue
        if d < before:
            found.append(d)
    return max(found) if found else None


def check_schedule(
    now: datetime,
    calendar: MarketCalendar,
    *,
    paper_reports_dir: Path,
    weekly_dir: Path,
    alerts_path: Path,
    digests_dir: Path,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    log_path: Path | None = None,
    task_reader: TaskResultReader | None = None,
    task_results_available: bool | None = None,
) -> WatchdogReport:
    """Find every scheduled firing since the last digest that left no artifact.

    The window starts the day AFTER the previous digest (that digest already reported on
    its own day) and ends on ``now``'s date. Without a previous digest it falls back to a
    bounded lookback rather than the whole history.
    """
    today = now.astimezone(UTC).date() if now.tzinfo else now.date()
    previous = previous_digest_date(digests_dir, today)
    if previous is not None:
        start = previous + timedelta(days=1)
        anchored = True
    else:
        start = today - timedelta(days=lookback_days)
        anchored = False
    # A same-day rerun of the digest would otherwise produce an empty window.
    start = min(start, today)

    report_days = {
        label: _run_report_days(paper_reports_dir, label) for label in APPROVED_STRATEGIES
    }
    weekly_days = _weekly_review_days(weekly_dir)
    refresh_days = _refresh_alert_days(alerts_path)

    # Every (day, task) this digest is answerable for, in order.
    #
    # The sweep from ``start`` is the window proper. DEFERRED is the PROP-6 half: the
    # previous digest skipped some of its OWN day's firings as not-yet-due, correctly,
    # and the window then begins the day after -- so nothing ever checked them. Both
    # Friday jobs live there (the digest fires 20:45Z; `quantlab-weekly` is due 21:00Z
    # and `quantlab-glassbox-refresh` 21:30Z), and on 2026-08-28 the refresh died
    # silently inside that gap while `digest_20260828` reported MISSED RUNS none over
    # four checked firings. Skipping now defers the check instead of cancelling it.
    #
    # Only the firings that were actually not-yet-due are picked up, never the whole
    # day: the rest were already reported on, and re-reporting them would fire a second
    # WARNING for one miss. When the previous digest's instant cannot be read the day is
    # treated as fully deferred -- re-reporting a named miss is the cheaper error.
    checks: list[tuple[date, ScheduledTask]] = []
    day = start
    while day <= today:
        checks.extend(
            (day, task) for task in SCHEDULE
            if _runs_on(task, day, calendar) and _due_at(task, day) <= now
        )
        day += timedelta(days=1)

    deferred_from: date | None = None
    if previous is not None and start > previous:
        ran_at = previous_digest_instant(digests_dir, previous)
        for task in SCHEDULE:
            if not _runs_on(task, previous, calendar):
                continue
            due = _due_at(task, previous)
            if due <= now and (ran_at is None or due > ran_at):
                checks.append((previous, task))
                deferred_from = previous

    missed: list[MissedRun] = []
    checked = 0
    for day, task in checks:
        if task.produces == PRODUCES_RUN_REPORT:
            for label in _labels_for(task):
                checked += 1
                if day not in report_days.get(label, set()):
                    missed.append(MissedRun(
                        task=task.name, day=day, label=label,
                        expected=f"no run report reports/paper/run_{label}_{day:%Y%m%d}*.json",
                    ))
        elif task.produces == PRODUCES_WEEKLY_REVIEW:
            checked += 1
            if day not in weekly_days:
                missed.append(MissedRun(
                    task=task.name, day=day,
                    expected=f"no weekly review reports/weekly/week_{day:%Y%m%d}.json",
                ))
        elif task.produces == PRODUCES_REFRESH_ALERT:
            checked += 1
            if day not in refresh_days:
                missed.append(MissedRun(
                    task=task.name, day=day,
                    expected="no glassbox.refresh alert (the chain left no deploy-log entry)",
                ))

    missed.sort(key=lambda m: (m.day, m.task, m.label or ""))

    # -- task-death tripwire (PROP-8) ---------------------------------------
    # Asks the opposite question to everything above: not "did the artifact appear"
    # but "did the scheduler record an ending the system never mentioned". A run that
    # is killed leaves no artifact AND no log line, so the artifact check alone reports
    # it as a missed firing with the wrong cause attached.
    available = (
        task_results_available if task_results_available is not None
        else schtasks_available()
    )
    deaths: list[TaskDeath] = []
    if available:
        reader = task_reader if task_reader is not None else _default_task_reader
        deaths = unexplained_task_deaths(reader(), alerts_path, log_path)

    result = WatchdogReport(
        # The reported window names what was actually examined, deferred firings
        # included -- a window line that hid them would understate the check.
        window_start=min(start, deferred_from) if deferred_from else start,
        window_end=today,
        anchored_to_previous_digest=anchored,
        firings_checked=checked, missed=missed,
        deaths=deaths, task_results_available=available,
    )
    if deaths:
        log.error("watchdog_task_deaths", count=len(deaths),
                  deaths=[d.render() for d in deaths])
    if missed:
        log.warning("watchdog_missed_runs", count=len(missed),
                    missed=[m.render() for m in missed])
    else:
        log.info("watchdog_clean", firings_checked=checked)
    return result


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "MissedRun",
    "TaskDeath",
    "TaskResult",
    "TaskResultReader",
    "WatchdogReport",
    "check_schedule",
    "parse_schtasks_list",
    "previous_digest_date",
    "schtasks_available",
    "unexplained_task_deaths",
]
