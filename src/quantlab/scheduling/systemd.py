"""systemd timer units for the always-on host (PROP-13).

WHY THIS EXISTS. Windows Task Scheduler on one workstation cannot run anything while that
machine is off or asleep, and on 2026-09-04 the Glass Box refresh was killed mid-chain under
Modern Standby with `STATUS_CONTROL_C_EXIT`, alerting nothing, leaving the published site
eight days stale. That was the second silent outage of the class the 2026-08-30 early-move
trigger names, so the deferral ended and the schedule moves to a VPS.

WHY TIMERS AND NOT A CRON TABLE. Three reasons, and the first is close to decisive.

* ``Persistent=true`` is the only faithful replacement for ``StartWhenAvailable``. The
  existing schedule depends on catch-up -- ``install`` bolts a PowerShell post-step onto
  every ``schtasks /Create`` to set it, and the record is full of catch-up runs that exist
  because of it. A timer with ``Persistent=true`` stores its last trigger and fires on boot
  if the window was missed. cron has no equivalent; anacron is daily-granularity and cannot
  express a 20:30 firing. Choosing cron would silently DELETE a behaviour the record
  depends on, which is a schedule change wearing a migration's clothes.
* systemd records a structured, queryable ending, and the death tripwire (PROP-8) reads
  exactly that. ``Result=``, ``ExecMainStatus=``, ``ActiveState=``/``SubState=`` are what
  ``reporting.watchdog`` consumes in place of ``schtasks``'s ``Last Result``. cron reports
  an exit status by local mail and keeps no queryable history, so the tripwire would have to
  be deleted rather than ported.
* ``Result=`` NAMES the cause -- ``exit-code``, ``signal``, ``oom-kill``, ``timeout``. The
  whole of PROP-11 exists because Windows' ``Last Result`` is two fields wearing one name,
  an exit code sometimes and a ``SCHED_S_*`` state code other times, and the tripwire read a
  state as a death. systemd separates them structurally.

EVERY FIRING INSTANT IS PRESERVED, AND IS NOT RESTATED HERE. The times come from the
``_RUN_TIME``/``_DIGEST_TIME``/... constants in :mod:`quantlab.scheduling.tasks` -- the same
constants ``schtasks`` installs from -- so this module cannot drift from the Windows
schedule by editing one of them. That is deliberate and it is the same rule ``SCHEDULE``
follows: a firing instant is a DECISION under `improve.firewall`, and re-expressing one is
allowed only where it is READ rather than chosen. Nothing here picks a time.

THE ZONE IS NAMED IN THE UNIT, not inherited. ``OnCalendar`` carries an explicit
``America/New_York``, so a host whose ``timedatectl`` is UTC still fires at the instants the
paper record was accumulated on. Inheriting the host clock would make the schedule depend on
a machine setting nothing in this repository can see, and a mark interval that moves because
someone ran ``timedatectl set-timezone`` is exactly the silent redefinition the firewall
freezes ``tasks.py`` to prevent.

NOTHING HERE IS EXECUTED, and nothing is installed. Every function is pure and returns text;
rendering the units to disk is a separate, explicit step, and putting them on a host is a
human action taken after the migration ruling. Same convention as the ``schtasks`` builders.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quantlab.scheduling.tasks import (
    _CRYPTO_RUN_TIME,
    _DIGEST_TIME,
    _GLASSBOX_REFRESH_TIME,
    _RUN_TIME,
    _WEEKLY_TIME,
    TASK_CRYPTO_PAPER_RUN,
    TASK_DIGEST,
    TASK_GLASSBOX_REFRESH,
    TASK_PAPER_RUN,
    TASK_WEEKLY,
)

# The zone the paper record was accumulated in. Written into every unit rather than
# inherited from the host -- see the module docstring.
SCHEDULE_TIMEZONE = "America/New_York"

# Where the checkout, the venv and the env file live on the target host. Defaults chosen
# for a single-purpose VPS; every one of them is a parameter of `render_units` so the real
# host can differ without this file being edited.
DEFAULT_INSTALL_ROOT = "/opt/quantlab"
DEFAULT_SERVICE_USER = "quantlab"

# systemd day expressions. `DAYS_*` in `tasks` describe the same thing for the watchdog;
# these are the calendar-spec spellings.
_SYSTEMD_WEEKDAYS = "Mon..Fri"
_SYSTEMD_FRIDAY = "Fri"

# Where the units are rendered for review in-repo. Not an install path.
UNIT_OUTPUT_DIR = Path("deploy") / "systemd"


@dataclass(frozen=True)
class TimerUnit:
    """One task, as a systemd service+timer pair."""

    task: str
    # HH:MM on the host's America/New_York clock -- read from `tasks`, never chosen here.
    local_time: str
    # A systemd day expression, or "" for every day.
    days: str
    # The `quantlab` sub-command this fires.
    command: str
    description: str
    # Long jobs get a ceiling so a hang is KILLED AND REPORTED rather than running forever.
    # The 2026-09-04 refresh hung inside connected standby until something killed it; a
    # timeout turns that into `Result=timeout`, which the tripwire reads as a named cause.
    timeout: str
    memory_max: str

    @property
    def service_name(self) -> str:
        return f"{self.task}.service"

    @property
    def timer_name(self) -> str:
        return f"{self.task}.timer"

    @property
    def on_calendar(self) -> str:
        """The ``OnCalendar=`` value, zone included."""
        days = f"{self.days} " if self.days else ""
        return f"{days}*-*-* {self.local_time}:00 {SCHEDULE_TIMEZONE}"


def build_units() -> tuple[TimerUnit, ...]:
    """Every installed task as a timer unit. Pure; the times are READ from ``tasks``.

    Ordered to mirror ``build_install_commands`` followed by the crypto task, so the two
    installers can be read side by side.
    """
    return (
        TimerUnit(
            task=TASK_PAPER_RUN, local_time=_RUN_TIME, days=_SYSTEMD_WEEKDAYS,
            command="paper run-all --asset-class us_equity --submit",
            description="quantlab equity paper run (gated, submits)",
            timeout="30min", memory_max="2G",
        ),
        TimerUnit(
            task=TASK_DIGEST, local_time=_DIGEST_TIME, days=_SYSTEMD_WEEKDAYS,
            command="digest",
            description="quantlab daily paper digest and scheduled-task watchdog",
            timeout="20min", memory_max="2G",
        ),
        TimerUnit(
            task=TASK_WEEKLY, local_time=_WEEKLY_TIME, days=_SYSTEMD_FRIDAY,
            command="weekly",
            description="quantlab weekly paper-vs-shadow review (report-only)",
            timeout="30min", memory_max="2G",
        ),
        TimerUnit(
            task=TASK_GLASSBOX_REFRESH, local_time=_GLASSBOX_REFRESH_TIME,
            days=_SYSTEMD_FRIDAY, command="glassbox refresh",
            description="quantlab Glass Box refresh: snapshot, build, gate, deploy",
            # The longest job by far -- npm build plus a netlify deploy -- and the one that
            # has died twice. 45 minutes is generous against the ~100s a healthy run takes,
            # which is the point: the ceiling exists to convert a HANG into a reported
            # ending, not to police normal duration.
            #
            # 1500M IS BELOW PHYSICAL RAM, and that is the whole value of the number
            # (PROP-16). The provisioned host has 1,919 MiB, so the earlier 3G could never
            # be reached by an allocation -- the machine would swap into a 4 GB swapfile
            # and degrade quietly instead of ending, which is the silent failure this
            # migration exists to remove, on the one job that has already died twice. A
            # ceiling under RAM makes a runaway arrive as `Result=oom-kill`, a NAMED cause
            # the death tripwire reads. Phase 0 measured the public build at 705 MiB
            # committed, peak, so this leaves better than two times headroom over the
            # real figure.
            timeout="45min", memory_max="1500M",
        ),
        TimerUnit(
            task=TASK_CRYPTO_PAPER_RUN, local_time=_CRYPTO_RUN_TIME, days="",
            command="paper run-all --asset-class crypto --submit",
            description="quantlab crypto paper run (gated, submits; 7 days a week)",
            timeout="30min", memory_max="2G",
        ),
    )


def render_service(
    unit: TimerUnit,
    *,
    install_root: str = DEFAULT_INSTALL_ROOT,
    user: str = DEFAULT_SERVICE_USER,
) -> str:
    """The ``.service`` text for ``unit``.

    ``WorkingDirectory`` is set explicitly. Under ``schtasks`` there was no working
    directory at all, so an unattended run started in ``C:\\Windows\\System32`` and a
    relative path resolved somewhere no one intended -- the incident recorded on
    `glassbox.snapshot.DEFAULT_REPORT_DIR`. Setting it removes that whole class; the
    repo-root anchoring stays regardless, because two guarantees are better than one.

    ``QUANTLAB_ENV_FILE`` is exported as well as loaded. ``EnvironmentFile`` injects the
    values into this process, but the env-secret gate has to be able to OPEN the file to
    reduce its values to prefixes, and it needs a path to do that.
    """
    env_file = f"{install_root}/.env"
    return "\n".join([
        "[Unit]",
        f"Description={unit.description}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=oneshot",
        f"User={user}",
        f"Group={user}",
        f"WorkingDirectory={install_root}",
        f"EnvironmentFile={env_file}",
        f"Environment=QUANTLAB_ENV_FILE={env_file}",
        f"ExecStart={install_root}/.venv/bin/quantlab {unit.command}",
        f"TimeoutStartSec={unit.timeout}",
        f"MemoryMax={unit.memory_max}",
        # A killed or timed-out run must not be retried silently: the watchdog's evidence
        # is the artifact, and a retry that succeeds after a death hides the death.
        "Restart=no",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
    ])


def render_timer(unit: TimerUnit) -> str:
    """The ``.timer`` text for ``unit``.

    ``Persistent=true`` on every one of them: it is the ``StartWhenAvailable`` equivalent
    and the reason a timer was chosen over a crontab at all.

    ``RandomizedDelaySec`` is deliberately NOT set. Jitter would move the mark instant, and
    the mark instant is what every divergence figure is computed against.
    """
    return "\n".join([
        "[Unit]",
        f"Description={unit.description} (timer)",
        "",
        "[Timer]",
        f"OnCalendar={unit.on_calendar}",
        "Persistent=true",
        f"Unit={unit.service_name}",
        # NO `AccuracySec` (PROP-16). The default is a minute of slack, which is ample:
        # what protects the mark instant is the absence of `RandomizedDelaySec`, not a
        # tight wake-up, and a setting that reads as protective while protecting nothing
        # is worse than no setting, because someone will eventually rely on it.
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ])


def render_units(
    *,
    install_root: str = DEFAULT_INSTALL_ROOT,
    user: str = DEFAULT_SERVICE_USER,
) -> dict[str, str]:
    """Every unit file as ``{filename: content}``. Pure; writes nothing."""
    out: dict[str, str] = {}
    for unit in build_units():
        out[unit.service_name] = render_service(
            unit, install_root=install_root, user=user
        )
        out[unit.timer_name] = render_timer(unit)
    return out


def build_enable_commands() -> list[list[str]]:
    """The ``systemctl`` argv lists that arm the schedule (pure; nothing is executed)."""
    argv: list[list[str]] = [["systemctl", "daemon-reload"]]
    for unit in build_units():
        argv.append(["systemctl", "enable", "--now", unit.timer_name])
    return argv


def build_disable_commands() -> list[list[str]]:
    """The rollback: disarm every timer without deleting anything."""
    return [
        ["systemctl", "disable", "--now", unit.timer_name] for unit in build_units()
    ]


__all__ = [
    "DEFAULT_INSTALL_ROOT",
    "DEFAULT_SERVICE_USER",
    "SCHEDULE_TIMEZONE",
    "UNIT_OUTPUT_DIR",
    "TimerUnit",
    "build_disable_commands",
    "build_enable_commands",
    "build_units",
    "render_service",
    "render_timer",
    "render_units",
]
