"""Windows Task Scheduler wiring for the daily paper run, digest, and weekly review.

Four tasks are installed:

* ``quantlab-paper-run`` at 10:00 (Mon-Fri) - runs ``quantlab paper run-all
  --asset-class us_equity --submit`` (each approved *equity* strategy in its own
  isolated paper account, in order). The ``--asset-class us_equity`` filter is
  load-bearing: without it ``run-all`` defaults to ``all`` and iterates every
  entry in APPROVED_STRATEGIES, which now includes crypto accounts - so the
  equity task would double-run the crypto strategies already covered by
  ``quantlab-crypto-paper-run``.
* ``quantlab-digest`` at 16:45 (Mon-Fri) - runs ``quantlab digest``.
* ``quantlab-weekly`` at 17:00 (Fri only) - runs ``quantlab weekly`` (the Phase-9
  paper-vs-shadow review; report-only).
* ``quantlab-glassbox-refresh`` at 17:30 (Fri only) - runs ``quantlab glassbox
  refresh``, republishing the public site from a fresh snapshot. 30 minutes after
  the weekly so the week's review is on disk and gets captured by the same
  refresh; the chain is fail-closed and will not deploy anything the gate has not
  passed (see ``glassbox.refresh``).

Why 10:00 (local, intended as ET): starting 30 minutes after the 09:30 open
sidesteps the opening-auction noise and the first-print gaps; a monthly-signal
strategy is insensitive to intraday timing, so any post-open minute is fine; and
a DAY order placed at 10:00 still has the entire session to fill. 16:45 for the
digest runs it shortly after the 16:00 close so end-of-day marks are settled.
17:00 Friday for the weekly review runs it after that day's digest so the week's
final equity snapshot is already recorded. 17:30 Friday for the Glass Box refresh
puts it after the weekly, so the public site publishes the review generated
half an hour earlier rather than the previous week's.

schtasks uses the host's LOCAL clock; the times above assume the machine runs on
Eastern time. Adjust ``_RUN_TIME`` / ``_DIGEST_TIME`` if the host is elsewhere.

``install`` prints the exact commands and refuses without ``--confirm YES`` (same
convention as ``risk reset``). The command builders are pure functions so tests
can assert the exact argv without executing anything.

Each task is created with ``schtasks /Create /F``; because that command has no
switch for missed-start catch-up (and ``/F`` resets it), ``install`` follows every
create with a PowerShell post-step that sets ``StartWhenAvailable = $true`` so
catch-up survives reinstalls.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from quantlab.config import ConfigError
from quantlab.logging_setup import get_logger
from quantlab.repo_state import RepoState, check_repo_state

log = get_logger("quantlab.scheduling")

TASK_PAPER_RUN = "quantlab-paper-run"
TASK_DIGEST = "quantlab-digest"
TASK_WEEKLY = "quantlab-weekly"
# The public-site refresh. Friday-only, after the weekly, so the review it publishes
# is the one just generated.
TASK_GLASSBOX_REFRESH = "quantlab-glassbox-refresh"
# Crypto is 24/7; its paper run is a separate DAILY (all 7 days) task at 20:30
# local, kept wholly distinct from the four task definitions above.
TASK_CRYPTO_PAPER_RUN = "quantlab-crypto-paper-run"

_WEEKDAYS = "MON,TUE,WED,THU,FRI"
_FRIDAY = "FRI"
_RUN_TIME = "10:00"
_DIGEST_TIME = "16:45"
_WEEKLY_TIME = "17:00"
_GLASSBOX_REFRESH_TIME = "17:30"
_CRYPTO_RUN_TIME = "20:30"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


# --------------------------------------------------------------------------- #
# Public schedule description (consumed by the digest's watchdog)             #
# --------------------------------------------------------------------------- #
# The watchdog has to know when each task was SUPPOSED to fire, and that knowledge
# must not be duplicated: a schedule change here has to move the expectation too, or
# the watchdog starts either crying wolf or going quiet. So the times above are
# re-expressed once, in UTC, alongside which days each task runs.
#
# DOCUMENTED LIMITATION, identical in kind to the one in ``glassbox.constants``: these
# are the EDT-era offsets (schtasks fires on the host's LOCAL clock, and the host is
# Eastern). Under EST every task lands an hour later in UTC. That shifts only *when the
# watchdog starts expecting* a run on the current day, never whether a past day's run is
# found, so a standard-time month makes the watchdog slightly early rather than wrong.
# A real tz-aware schedule model is a later decision, not a silent guess here.

DAYS_WEEKDAYS = "weekdays"   # Mon-Fri, and for equities further narrowed to NYSE sessions
DAYS_FRIDAY = "friday"
DAYS_DAILY = "daily"


@dataclass(frozen=True)
class ScheduledTask:
    """One installed task, and the artifact that proves it ran."""

    name: str
    utc_minute_of_day: int
    days: str
    # Which artifact a completed firing leaves behind. Read by the watchdog.
    produces: str
    # For paper-run tasks: the asset class whose accounts should each have a report.
    asset_class: str | None = None


PRODUCES_RUN_REPORT = "run_report"
PRODUCES_WEEKLY_REVIEW = "weekly_review"
PRODUCES_REFRESH_ALERT = "refresh_alert"

SCHEDULE: tuple[ScheduledTask, ...] = (
    ScheduledTask(TASK_PAPER_RUN, 14 * 60, DAYS_WEEKDAYS,
                  PRODUCES_RUN_REPORT, asset_class="us_equity"),
    # 20:30 ET is 00:30 UTC on the FOLLOWING calendar day, which is the day its mark and
    # its report are stamped with -- so the expectation is keyed to that day at 00:30.
    ScheduledTask(TASK_CRYPTO_PAPER_RUN, 30, DAYS_DAILY,
                  PRODUCES_RUN_REPORT, asset_class="crypto"),
    ScheduledTask(TASK_WEEKLY, 21 * 60, DAYS_FRIDAY, PRODUCES_WEEKLY_REVIEW),
    ScheduledTask(TASK_GLASSBOX_REFRESH, 21 * 60 + 30, DAYS_FRIDAY,
                  PRODUCES_REFRESH_ALERT),
)


def resolve_quantlab_exe() -> str:
    """Absolute path to the venv's ``quantlab`` launcher, resolved at call time."""
    candidate = Path(sys.executable).parent / "quantlab.exe"
    if candidate.exists():
        return str(candidate)
    which = shutil.which("quantlab")
    if which:
        return which
    raise ConfigError(
        "could not resolve the quantlab executable; is the package installed in this venv?"
    )


def _tr(exe: str, cli_args: str) -> str:
    # /TR is a single argument: the fully-quoted command line for the task.
    return f'"{exe}" {cli_args}'


def build_install_commands(exe: str) -> list[list[str]]:
    """The four ``schtasks /Create`` argv lists (pure; nothing is executed)."""
    return [
        [
            "schtasks", "/Create", "/TN", TASK_PAPER_RUN, "/SC", "WEEKLY",
            "/D", _WEEKDAYS, "/ST", _RUN_TIME,
            "/TR", _tr(exe, "paper run-all --asset-class us_equity --submit"), "/F",
        ],
        [
            "schtasks", "/Create", "/TN", TASK_DIGEST, "/SC", "WEEKLY",
            "/D", _WEEKDAYS, "/ST", _DIGEST_TIME,
            "/TR", _tr(exe, "digest"), "/F",
        ],
        [
            "schtasks", "/Create", "/TN", TASK_WEEKLY, "/SC", "WEEKLY",
            "/D", _FRIDAY, "/ST", _WEEKLY_TIME,
            "/TR", _tr(exe, "weekly"), "/F",
        ],
        [
            "schtasks", "/Create", "/TN", TASK_GLASSBOX_REFRESH, "/SC", "WEEKLY",
            "/D", _FRIDAY, "/ST", _GLASSBOX_REFRESH_TIME,
            # Not --dry-run: the scheduled run is expected to publish. It still cannot
            # deploy anything the fail-closed chain has not gated.
            "/TR", _tr(exe, "glassbox refresh"), "/F",
        ],
    ]


def build_uninstall_commands() -> list[list[str]]:
    return [
        ["schtasks", "/Delete", "/TN", TASK_PAPER_RUN, "/F"],
        ["schtasks", "/Delete", "/TN", TASK_DIGEST, "/F"],
        ["schtasks", "/Delete", "/TN", TASK_WEEKLY, "/F"],
        ["schtasks", "/Delete", "/TN", TASK_GLASSBOX_REFRESH, "/F"],
    ]


def build_show_commands() -> list[list[str]]:
    return [
        ["schtasks", "/Query", "/TN", TASK_PAPER_RUN, "/V", "/FO", "LIST"],
        ["schtasks", "/Query", "/TN", TASK_DIGEST, "/V", "/FO", "LIST"],
        ["schtasks", "/Query", "/TN", TASK_WEEKLY, "/V", "/FO", "LIST"],
        ["schtasks", "/Query", "/TN", TASK_GLASSBOX_REFRESH, "/V", "/FO", "LIST"],
    ]


# -- Crypto task (separate; the four builders above are never touched) --

def build_crypto_install_commands(exe: str) -> list[list[str]]:
    """The crypto ``schtasks /Create`` argv (pure; nothing is executed).

    A single DAILY task (all 7 days, ``/SC DAILY``) at 20:30 local running the
    crypto-only run-all. Same ``/F`` and quoting conventions as the equity tasks.
    """
    return [
        [
            "schtasks", "/Create", "/TN", TASK_CRYPTO_PAPER_RUN, "/SC", "DAILY",
            "/ST", _CRYPTO_RUN_TIME,
            "/TR", _tr(exe, "paper run-all --asset-class crypto --submit"), "/F",
        ],
    ]


def build_crypto_uninstall_commands() -> list[list[str]]:
    return [["schtasks", "/Delete", "/TN", TASK_CRYPTO_PAPER_RUN, "/F"]]


def build_crypto_show_commands() -> list[list[str]]:
    return [["schtasks", "/Query", "/TN", TASK_CRYPTO_PAPER_RUN, "/V", "/FO", "LIST"]]


# -- StartWhenAvailable post-step (applies to every installed task) ------------

def build_start_when_available_command(name: str) -> list[str]:
    """PowerShell argv that turns on missed-start catch-up for task ``name``.

    ``schtasks /Create`` has no switch for "run task as soon as possible after a
    scheduled start is missed" (``StartWhenAvailable``), and a bare ``/Create /F``
    overwrite silently resets it. So after each create we run this one-liner to
    set it explicitly, keeping catch-up durable across reinstalls. Pure: nothing
    is executed here (same convention as the schtasks builders).
    """
    script = (
        f"$t = Get-ScheduledTask -TaskName '{name}'; "
        f"$s = $t.Settings; $s.StartWhenAvailable = $true; "
        f"Set-ScheduledTask -TaskName '{name}' -Settings $s"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def _default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def install(
    confirm: str | None,
    exe: str | None = None,
    runner: Runner = _default_runner,
    printer: Callable[[str], None] = print,
    builder: Callable[[str], list[list[str]]] = build_install_commands,
    repo_state: RepoState | None = None,
) -> int:
    """Print the exact commands, then (only with ``confirm == 'YES'``) run them.

    ``builder`` defaults to the three equity tasks; pass
    :func:`build_crypto_install_commands` to install the crypto task instead.

    After each successful ``schtasks /Create`` a PowerShell post-step enables
    ``StartWhenAvailable`` (missed-start catch-up) for that task; a post-step
    failure is reported as a warning but does not fail the install.
    """
    resolved = exe if exe is not None else resolve_quantlab_exe()
    commands = builder(resolved)

    # Provenance warning, report-only. These tasks will run THIS checkout unattended for
    # months, so installing from a dirty or unpushed tree means the code that trades is not
    # the code the repository can show anyone. Not a hard block: see repo_state.
    for warning in (repo_state if repo_state is not None else check_repo_state()).warnings:
        printer(f"WARNING: {warning}")
        log.warning("schedule_install_repo_unclean", detail=warning)

    # Each task is created, then a post-step enables StartWhenAvailable (catch-up).
    # The preview lists both so what is printed is exactly what runs.
    printer("The following scheduled tasks will be created:")
    for cmd in commands:
        printer("  " + _display(cmd))
        printer("  " + _display(build_start_when_available_command(cmd[3])))

    if confirm != "YES":
        printer("Refusing to install: pass --confirm YES to create these tasks.")
        return 2

    for cmd in commands:
        name = cmd[3]
        result = runner(cmd)
        log.info("schedule_install", task=name, returncode=result.returncode)
        if result.returncode != 0:
            printer(f"FAILED ({result.returncode}): {_display(cmd)}\n{result.stderr}")
            return 1
        printer(f"created: {name}")
        # Post-step: enable catch-up. A failure here is a warning, not a fatal
        # error - the task exists and runs, just without missed-start recovery.
        post = build_start_when_available_command(name)
        post_result = runner(post)
        log.info(
            "schedule_start_when_available", task=name, returncode=post_result.returncode
        )
        if post_result.returncode != 0:
            printer(
                f"WARNING: could not enable StartWhenAvailable (catch-up) for {name}; "
                f"the task was created but will not recover a missed start.\n"
                f"{post_result.stderr}"
            )
        else:
            printer(f"catch-up enabled: {name}")
    return 0


def uninstall(
    runner: Runner = _default_runner,
    printer: Callable[[str], None] = print,
    builder: Callable[[], list[list[str]]] = build_uninstall_commands,
) -> int:
    """Delete the tasks; idempotent (a missing task is not an error)."""
    for cmd in builder():
        result = runner(cmd)
        log.info("schedule_uninstall", task=cmd[3], returncode=result.returncode)
        if result.returncode == 0:
            printer(f"removed: {cmd[3]}")
        else:
            printer(f"not present (ok): {cmd[3]}")
    return 0


def show(
    runner: Runner = _default_runner,
    printer: Callable[[str], None] = print,
    builder: Callable[[], list[list[str]]] = build_show_commands,
) -> int:
    """Print ``schtasks /Query`` output for the tasks."""
    for cmd in builder():
        result = runner(cmd)
        printer(f"=== {cmd[3]} ===")
        printer(result.stdout.strip() if result.stdout else result.stderr.strip() or "(not found)")
    return 0


def _display(cmd: Sequence[str]) -> str:
    """Render an argv as a copy-pasteable command line for the console."""
    parts: list[str] = []
    for arg in cmd:
        parts.append(f'"{arg}"' if " " in arg and not arg.startswith('"') else arg)
    return " ".join(parts)


__all__ = [
    "resolve_quantlab_exe",
    "build_install_commands",
    "build_uninstall_commands",
    "build_show_commands",
    "build_crypto_install_commands",
    "build_crypto_uninstall_commands",
    "build_crypto_show_commands",
    "build_start_when_available_command",
    "install",
    "uninstall",
    "show",
    "TASK_PAPER_RUN",
    "TASK_DIGEST",
    "TASK_WEEKLY",
    "TASK_CRYPTO_PAPER_RUN",
]
