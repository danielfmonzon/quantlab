"""Windows Task Scheduler wiring for the daily paper run, digest, and weekly review.

Three tasks are installed:

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

Why 10:00 (local, intended as ET): starting 30 minutes after the 09:30 open
sidesteps the opening-auction noise and the first-print gaps; a monthly-signal
strategy is insensitive to intraday timing, so any post-open minute is fine; and
a DAY order placed at 10:00 still has the entire session to fill. 16:45 for the
digest runs it shortly after the 16:00 close so end-of-day marks are settled.
17:00 Friday for the weekly review runs it after that day's digest so the week's
final equity snapshot is already recorded.

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
from pathlib import Path

from quantlab.config import ConfigError
from quantlab.logging_setup import get_logger

log = get_logger("quantlab.scheduling")

TASK_PAPER_RUN = "quantlab-paper-run"
TASK_DIGEST = "quantlab-digest"
TASK_WEEKLY = "quantlab-weekly"
# Crypto is 24/7; its paper run is a separate DAILY (all 7 days) task at 20:30
# local, kept wholly distinct from the three equity task definitions above.
TASK_CRYPTO_PAPER_RUN = "quantlab-crypto-paper-run"

_WEEKDAYS = "MON,TUE,WED,THU,FRI"
_FRIDAY = "FRI"
_RUN_TIME = "10:00"
_DIGEST_TIME = "16:45"
_WEEKLY_TIME = "17:00"
_CRYPTO_RUN_TIME = "20:30"

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
    """The three ``schtasks /Create`` argv lists (pure; nothing is executed)."""
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
    ]


def build_uninstall_commands() -> list[list[str]]:
    return [
        ["schtasks", "/Delete", "/TN", TASK_PAPER_RUN, "/F"],
        ["schtasks", "/Delete", "/TN", TASK_DIGEST, "/F"],
        ["schtasks", "/Delete", "/TN", TASK_WEEKLY, "/F"],
    ]


def build_show_commands() -> list[list[str]]:
    return [
        ["schtasks", "/Query", "/TN", TASK_PAPER_RUN, "/V", "/FO", "LIST"],
        ["schtasks", "/Query", "/TN", TASK_DIGEST, "/V", "/FO", "LIST"],
        ["schtasks", "/Query", "/TN", TASK_WEEKLY, "/V", "/FO", "LIST"],
    ]


# -- Crypto task (separate; the three equity builders above are never touched) --

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
