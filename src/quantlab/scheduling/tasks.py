"""Windows Task Scheduler wiring for the daily paper run and digest.

Two weekday tasks are installed:

* ``quantlab-paper-run`` at 10:00 - runs ``quantlab paper run --strategy
  voltarget --submit``.
* ``quantlab-digest`` at 16:45 - runs ``quantlab digest``.

Why 10:00 (local, intended as ET): starting 30 minutes after the 09:30 open
sidesteps the opening-auction noise and the first-print gaps; a monthly-signal
strategy is insensitive to intraday timing, so any post-open minute is fine; and
a DAY order placed at 10:00 still has the entire session to fill. 16:45 for the
digest runs it shortly after the 16:00 close so end-of-day marks are settled.

schtasks uses the host's LOCAL clock; the times above assume the machine runs on
Eastern time. Adjust ``_RUN_TIME`` / ``_DIGEST_TIME`` if the host is elsewhere.

``install`` prints the exact commands and refuses without ``--confirm YES`` (same
convention as ``risk reset``). The command builders are pure functions so tests
can assert the exact argv without executing anything.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from quantlab.config import ConfigError
from quantlab.logging_setup import get_logger

log = get_logger("quantlab.scheduling")

TASK_PAPER_RUN = "quantlab-paper-run"
TASK_DIGEST = "quantlab-digest"

_WEEKDAYS = "MON,TUE,WED,THU,FRI"
_RUN_TIME = "10:00"
_DIGEST_TIME = "16:45"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


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
    """The two ``schtasks /Create`` argv lists (pure; nothing is executed)."""
    return [
        [
            "schtasks", "/Create", "/TN", TASK_PAPER_RUN, "/SC", "WEEKLY",
            "/D", _WEEKDAYS, "/ST", _RUN_TIME,
            "/TR", _tr(exe, "paper run --strategy voltarget --submit"), "/F",
        ],
        [
            "schtasks", "/Create", "/TN", TASK_DIGEST, "/SC", "WEEKLY",
            "/D", _WEEKDAYS, "/ST", _DIGEST_TIME,
            "/TR", _tr(exe, "digest"), "/F",
        ],
    ]


def build_uninstall_commands() -> list[list[str]]:
    return [
        ["schtasks", "/Delete", "/TN", TASK_PAPER_RUN, "/F"],
        ["schtasks", "/Delete", "/TN", TASK_DIGEST, "/F"],
    ]


def build_show_commands() -> list[list[str]]:
    return [
        ["schtasks", "/Query", "/TN", TASK_PAPER_RUN, "/V", "/FO", "LIST"],
        ["schtasks", "/Query", "/TN", TASK_DIGEST, "/V", "/FO", "LIST"],
    ]


def _default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True)


def install(
    confirm: str | None,
    exe: str | None = None,
    runner: Runner = _default_runner,
    printer: Callable[[str], None] = print,
) -> int:
    """Print the exact commands, then (only with ``confirm == 'YES'``) run them."""
    resolved = exe if exe is not None else resolve_quantlab_exe()
    commands = build_install_commands(resolved)

    printer("The following scheduled tasks will be created:")
    for cmd in commands:
        printer("  " + _display(cmd))

    if confirm != "YES":
        printer("Refusing to install: pass --confirm YES to create these tasks.")
        return 2

    for cmd in commands:
        result = runner(cmd)
        log.info("schedule_install", task=cmd[3], returncode=result.returncode)
        if result.returncode != 0:
            printer(f"FAILED ({result.returncode}): {_display(cmd)}\n{result.stderr}")
            return 1
        printer(f"created: {cmd[3]}")
    return 0


def uninstall(runner: Runner = _default_runner, printer: Callable[[str], None] = print) -> int:
    """Delete both tasks; idempotent (a missing task is not an error)."""
    for cmd in build_uninstall_commands():
        result = runner(cmd)
        log.info("schedule_uninstall", task=cmd[3], returncode=result.returncode)
        if result.returncode == 0:
            printer(f"removed: {cmd[3]}")
        else:
            printer(f"not present (ok): {cmd[3]}")
    return 0


def show(runner: Runner = _default_runner, printer: Callable[[str], None] = print) -> int:
    """Print ``schtasks /Query`` output for both tasks."""
    for cmd in build_show_commands():
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
    "install",
    "uninstall",
    "show",
    "TASK_PAPER_RUN",
    "TASK_DIGEST",
]
