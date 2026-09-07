"""PROP-13: the host-independent half of the VPS migration.

Three things are under test here, and none of them needs a host:

* the systemd units reproduce every firing instant the Windows schedule installs;
* the death tripwire reads systemd's ledger as well as ``schtasks``'s, behind ONE
  availability predicate that does not silently go dark on Linux;
* the env file is resolved through one function that both readers of it agree on.

The fixtures are captured ``systemctl show`` output, so this suite is written on Windows
and means the same thing on Linux -- the same reason ``parse_schtasks_list`` is separated
from the subprocess call it feeds.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from quantlab.config import (
    ENV_FILE_VAR,
    env_file_is_group_or_world_readable,
    env_file_path,
    load_env_file,
)
from quantlab.constants import PROJECT_ROOT
from quantlab.reporting.watchdog import (
    audit_task_deaths,
    parse_systemctl_show,
    systemd_available,
    task_scheduler_available,
    tasks_in_flight,
)
from quantlab.scheduling.systemd import (
    SCHEDULE_TIMEZONE,
    build_disable_commands,
    build_enable_commands,
    build_units,
    render_service,
    render_timer,
    render_units,
)
from quantlab.scheduling.tasks import (
    TASK_CRYPTO_PAPER_RUN,
    TASK_DIGEST,
    TASK_GLASSBOX_REFRESH,
    TASK_PAPER_RUN,
    TASK_WEEKLY,
    build_crypto_install_commands,
    build_install_commands,
)

# --------------------------------------------------------------------------- #
# The units reproduce the schedule rather than restating it                    #
# --------------------------------------------------------------------------- #


def _schtasks_time(task: str) -> str:
    """The ``/ST`` value schtasks installs for ``task`` — the other source of truth."""
    argv = build_install_commands("quantlab") + build_crypto_install_commands("quantlab")
    for cmd in argv:
        if task in cmd:
            return cmd[cmd.index("/ST") + 1]
    raise AssertionError(f"{task} is not installed by any builder")


@pytest.mark.parametrize("task", [
    TASK_PAPER_RUN, TASK_DIGEST, TASK_WEEKLY, TASK_GLASSBOX_REFRESH,
    TASK_CRYPTO_PAPER_RUN,
])
def test_every_unit_fires_at_the_instant_schtasks_installs(task: str) -> None:
    """THE ANTI-DRIFT ASSERTION, and the reason this suite exists at all.

    A migration is allowed to change the host; it is not allowed to change when anything
    fires, because the mark instant is what every divergence figure in the paper record is
    computed against. If someone edits `_RUN_TIME` and not the unit — or the reverse —
    this fails rather than the two quietly disagreeing on a live host.
    """
    unit = next(u for u in build_units() if u.task == task)
    assert unit.local_time == _schtasks_time(task)
    assert unit.on_calendar.endswith(f"{unit.local_time}:00 {SCHEDULE_TIMEZONE}")


def test_every_task_installed_on_windows_has_a_unit() -> None:
    """Five tasks in, five tasks out — a migration that drops one is how a run goes dark."""
    installed = {
        cmd[cmd.index("/TN") + 1]
        for cmd in build_install_commands("quantlab") + build_crypto_install_commands("q")
    }
    assert {u.task for u in build_units()} == installed


def test_every_timer_is_persistent() -> None:
    """`Persistent=true` IS the `StartWhenAvailable` equivalent; without it the move is a
    silent removal of catch-up, which the record depends on."""
    for unit in build_units():
        assert "Persistent=true" in render_timer(unit)


def test_no_timer_randomises_its_start() -> None:
    """Jitter would move the mark instant, which is the one thing that must not move."""
    for unit in build_units():
        assert "RandomizedDelaySec" not in render_timer(unit)


def test_the_zone_is_named_in_the_unit_not_inherited() -> None:
    """A schedule that depends on `timedatectl` depends on something the repo cannot see."""
    for unit in build_units():
        assert SCHEDULE_TIMEZONE in render_timer(unit)


def test_the_crypto_timer_runs_every_day_and_the_others_do_not() -> None:
    units = {u.task: u for u in build_units()}
    assert units[TASK_CRYPTO_PAPER_RUN].on_calendar.startswith("*-*-*")
    assert units[TASK_PAPER_RUN].on_calendar.startswith("Mon..Fri ")
    assert units[TASK_DIGEST].on_calendar.startswith("Mon..Fri ")
    assert units[TASK_WEEKLY].on_calendar.startswith("Fri ")
    assert units[TASK_GLASSBOX_REFRESH].on_calendar.startswith("Fri ")


def test_the_service_sets_a_working_directory() -> None:
    """Removes the class of defect that put an unattended run in `C:\\Windows\\System32`."""
    for unit in build_units():
        assert "WorkingDirectory=/opt/quantlab" in render_service(unit)


def test_the_service_points_the_env_override_at_the_file_it_loads() -> None:
    """`EnvironmentFile` injects the values; the gate additionally has to OPEN the file."""
    for unit in build_units():
        text = render_service(unit)
        assert "EnvironmentFile=/opt/quantlab/.env" in text
        assert f"Environment={ENV_FILE_VAR}=/opt/quantlab/.env" in text


def test_every_service_is_bounded_and_never_retried() -> None:
    """A hang becomes `Result=timeout`; a silent retry would hide a death."""
    for unit in build_units():
        text = render_service(unit)
        assert "TimeoutStartSec=" in text
        assert "Restart=no" in text


def test_the_install_root_and_user_are_parameters_not_edits() -> None:
    """Wednesday's host details must not require touching this module."""
    text = render_service(build_units()[0], install_root="/srv/ql", user="ql")
    assert "WorkingDirectory=/srv/ql" in text
    assert "User=ql" in text
    assert "/srv/ql/.venv/bin/quantlab" in text


def test_rendered_units_match_the_files_committed_under_deploy() -> None:
    """The reviewed files and the generator cannot drift apart unnoticed."""
    out = PROJECT_ROOT / "deploy" / "systemd"
    rendered = render_units()
    assert {p.name for p in out.glob("*")} == set(rendered)
    for name, text in rendered.items():
        assert (out / name).read_text(encoding="utf-8") == text


def test_enable_and_disable_commands_are_pure_and_symmetric() -> None:
    """The rollback disarms every timer and deletes nothing."""
    enable = build_enable_commands()
    assert enable[0] == ["systemctl", "daemon-reload"]
    assert len(enable) == len(build_units()) + 1
    disable = build_disable_commands()
    assert all(cmd[:3] == ["systemctl", "disable", "--now"] for cmd in disable)
    assert {c[-1] for c in disable} == {c[-1] for c in enable[1:]}


# --------------------------------------------------------------------------- #
# The death tripwire on Linux                                                  #
# --------------------------------------------------------------------------- #

# Captured `systemctl show` output. The refresh block is the 2026-09-04 death as systemd
# would have recorded it: killed, and SAYING SO, instead of one opaque HRESULT.
_SHOW_OUTPUT = """Id=quantlab-glassbox-refresh.service
Result=signal
ExecMainStatus=9
ExecMainCode=2
ExecMainExitTimestamp=Fri 2026-09-04 17:30:41 EDT
ActiveState=failed
SubState=failed

Id=quantlab-digest.service
Result=success
ExecMainStatus=0
ExecMainCode=1
ExecMainExitTimestamp=Fri 2026-09-04 16:45:12 EDT
ActiveState=inactive
SubState=dead

Id=quantlab-crypto-paper-run.service
Result=success
ExecMainStatus=0
ExecMainCode=1
ExecMainExitTimestamp=n/a
ActiveState=activating
SubState=start
"""


def test_parse_systemctl_show_reads_each_unit() -> None:
    results = {r.task: r for r in parse_systemctl_show(_SHOW_OUTPUT)}
    assert set(results) == {
        "quantlab-glassbox-refresh", "quantlab-digest", "quantlab-crypto-paper-run",
    }
    refresh = results["quantlab-glassbox-refresh"]
    assert refresh.result_kind == "signal"
    assert refresh.last_result == 9
    assert refresh.recorded_at == datetime(2026, 9, 4, 17, 30, 41)
    assert refresh.running is False


def test_a_unit_mid_flight_is_reported_as_running() -> None:
    """A oneshot under way reports the PREVIOUS run's Result; the state must win."""
    results = {r.task: r for r in parse_systemctl_show(_SHOW_OUTPUT)}
    crypto = results["quantlab-crypto-paper-run"]
    assert crypto.running is True
    assert crypto.result_kind == "success"      # stale, and correctly ignored
    assert tasks_in_flight(parse_systemctl_show(_SHOW_OUTPUT)) == {
        "quantlab-crypto-paper-run"
    }


def test_a_signal_death_is_named_with_its_cause(tmp_path: Path) -> None:
    """The 2026-09-04 failure, as the new host would have reported it."""
    audit = audit_task_deaths(
        parse_systemctl_show(_SHOW_OUTPUT), tmp_path / "alerts.jsonl", None,
    )
    assert [d.task for d in audit.deaths] == ["quantlab-glassbox-refresh"]
    rendered = audit.deaths[0].render()
    assert "signal" in rendered
    assert "status 9" in rendered


def test_a_running_unit_is_never_a_death(tmp_path: Path) -> None:
    """Reading Result before SubState would classify the LAST run's outcome as this one's."""
    text = _SHOW_OUTPUT.replace("Result=success\nExecMainStatus=0\nExecMainCode=1\n"
                                "ExecMainExitTimestamp=n/a\nActiveState=activating",
                                "Result=exit-code\nExecMainStatus=3\nExecMainCode=1\n"
                                "ExecMainExitTimestamp=n/a\nActiveState=activating")
    audit = audit_task_deaths(parse_systemctl_show(text), tmp_path / "a.jsonl", None)
    assert "quantlab-crypto-paper-run" not in [d.task for d in audit.deaths]


@pytest.mark.parametrize("kind,status,is_death", [
    ("success", 0, False),
    ("exit-code", 0, False),      # ended cleanly; the kind alone is not a verdict
    ("exit-code", 3, True),
    ("signal", 9, True),
    ("oom-kill", 0, True),        # a kill with no exit status is still a kill
    ("timeout", 0, True),
    ("core-dump", 11, True),
])
def test_result_kind_decides_what_counts_as_a_death(
    kind: str, status: int, is_death: bool, tmp_path: Path,
) -> None:
    text = (
        f"Id=quantlab-weekly.service\nResult={kind}\nExecMainStatus={status}\n"
        f"ExecMainCode=1\nExecMainExitTimestamp=Fri 2026-09-04 17:00:03 EDT\n"
        f"ActiveState=inactive\nSubState=dead\n"
    )
    audit = audit_task_deaths(parse_systemctl_show(text), tmp_path / "a.jsonl", None)
    assert bool(audit.deaths) is is_death


def test_a_block_without_a_readable_result_is_skipped_not_guessed_at() -> None:
    """A fabricated code would fire a CRITICAL naming a failure that never happened."""
    assert parse_systemctl_show("Id=quantlab-weekly.service\nActiveState=inactive\n") == []
    assert parse_systemctl_show("Result=signal\nExecMainStatus=9\n") == []
    assert parse_systemctl_show(
        "Id=quantlab-weekly.service\nResult=signal\nExecMainStatus=notanumber\n"
    ) == []


def test_a_non_quantlab_unit_is_ignored() -> None:
    assert parse_systemctl_show(
        "Id=nginx.service\nResult=exit-code\nExecMainStatus=1\n"
    ) == []


def test_an_unparseable_timestamp_does_not_lose_the_death(tmp_path: Path) -> None:
    """A stamp only decorates the alert; losing it must not suppress the alert."""
    text = (
        "Id=quantlab-weekly.service\nResult=signal\nExecMainStatus=9\nExecMainCode=2\n"
        "ExecMainExitTimestamp=who knows\nActiveState=failed\nSubState=failed\n"
    )
    results = parse_systemctl_show(text)
    assert results[0].recorded_at is None
    audit = audit_task_deaths(results, tmp_path / "a.jsonl", None)
    assert [d.task for d in audit.deaths] == ["quantlab-weekly"]
    # An unknown instant reads as post-hardening: the louder of the two, deliberately.
    assert audit.deaths[0].post_hardening is True


def test_the_availability_predicate_covers_both_schedulers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MIGRATION'S QUIETEST HAZARD.

    `schtasks_available()` alone is False on Linux. Moving the host without widening the
    predicate would have switched the tripwire off and rendered "unavailable on this host"
    once a day forever — a silent-monitoring failure traded for a silent-outage one, and
    the worse of the two because the report still looks like a report.
    """
    import quantlab.reporting.watchdog as wd

    monkeypatch.setattr(wd.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wd.shutil, "which", lambda _: "/usr/bin/systemctl")
    assert systemd_available() is True
    assert task_scheduler_available() is True

    monkeypatch.setattr(wd.platform, "system", lambda: "Windows")
    assert systemd_available() is False
    assert task_scheduler_available() is True


def test_linux_without_systemctl_reports_unavailable_rather_than_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty audit and 'nothing to read here' are different facts."""
    import quantlab.reporting.watchdog as wd

    monkeypatch.setattr(wd.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wd.shutil, "which", lambda _: None)
    assert task_scheduler_available() is False


def test_the_unavailable_line_names_both_schedulers() -> None:
    from quantlab.reporting.watchdog import WatchdogReport

    report = WatchdogReport(
        window_start=datetime(2026, 9, 7).date(), window_end=datetime(2026, 9, 7).date(),
        task_results_available=False,
    )
    rendered = "\n".join(report.render())
    assert "unavailable on this host" in rendered
    assert "systemd" in rendered


def test_windows_rows_still_classify_exactly_as_before(tmp_path: Path) -> None:
    """Regression: the platform-neutral fields default to None and change nothing."""
    from quantlab.reporting.watchdog import TaskResult

    rows = [
        TaskResult(task="quantlab-glassbox-refresh", last_result=-2147023829,
                   recorded_at=datetime(2026, 8, 28, 17, 30)),
        TaskResult(task="quantlab-digest", last_result=0x00041301,
                   recorded_at=datetime(2026, 8, 31, 16, 45)),
        TaskResult(task="quantlab-weekly", last_result=0,
                   recorded_at=datetime(2026, 8, 28, 17, 0)),
    ]
    audit = audit_task_deaths(rows, tmp_path / "a.jsonl", None)
    assert [d.task for d in audit.deaths] == ["quantlab-glassbox-refresh"]
    # The HRESULT rendering is unchanged where no cause was named.
    assert "0x8007042B" in audit.deaths[0].render()
    # And SCHED_S_TASK_RUNNING is still read as in-flight on the Windows path.
    assert tasks_in_flight(rows) == {"quantlab-digest"}


# --------------------------------------------------------------------------- #
# The env file                                                                 #
# --------------------------------------------------------------------------- #


def test_the_env_file_defaults_to_the_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anchored, not CWD-relative: a relative path silently resolves to nothing under a
    scheduler, and the env-secret gate PASSES having searched for no secrets at all."""
    monkeypatch.delenv(ENV_FILE_VAR, raising=False)
    assert env_file_path() == PROJECT_ROOT / ".env"


def test_the_env_file_can_be_relocated_for_the_new_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = tmp_path / "elsewhere" / "quantlab.env"
    monkeypatch.setenv(ENV_FILE_VAR, str(target))
    assert env_file_path() == target


def test_the_override_is_read_at_call_time_not_captured_at_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A value captured at import could not be changed by a unit file or a test."""
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "one.env"))
    first = env_file_path()
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "two.env"))
    assert env_file_path() != first


def test_the_verify_dist_gate_follows_the_same_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two modules pinned the path independently; they must not disagree on the host."""
    import inspect

    from quantlab.glassbox import verify_dist

    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "x.env"))
    source = inspect.getsource(verify_dist)
    assert "env_file_path()" in source
    assert env_file_path() == tmp_path / "x.env"


def test_load_env_file_resolves_through_the_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = tmp_path / "custom.env"
    target.write_text("QUANTLAB_TEST_ONLY_KEY=abc123\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VAR, str(target))
    monkeypatch.delenv("QUANTLAB_TEST_ONLY_KEY", raising=False)

    assert load_env_file() == ["QUANTLAB_TEST_ONLY_KEY"]
    assert os.environ["QUANTLAB_TEST_ONLY_KEY"] == "abc123"


def test_a_real_environment_variable_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Unchanged behaviour: the file never overrides what the unit already exported."""
    target = tmp_path / "custom.env"
    target.write_text("QUANTLAB_TEST_ONLY_KEY=from_file\n", encoding="utf-8")
    monkeypatch.setenv(ENV_FILE_VAR, str(target))
    monkeypatch.setenv("QUANTLAB_TEST_ONLY_KEY", "from_env")

    assert load_env_file() == []
    assert os.environ["QUANTLAB_TEST_ONLY_KEY"] == "from_env"


def test_a_missing_env_file_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setenv(ENV_FILE_VAR, str(tmp_path / "absent.env"))
    assert load_env_file() == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits carry no such meaning here")
def test_a_group_readable_env_file_is_reported(tmp_path: Path) -> None:
    target = tmp_path / "loose.env"
    target.write_text("K=v\n", encoding="utf-8")
    target.chmod(0o640)
    assert env_file_is_group_or_world_readable(target) is True
    target.chmod(0o600)
    assert env_file_is_group_or_world_readable(target) is False


def test_the_permission_check_never_raises_on_a_missing_file(tmp_path: Path) -> None:
    """Reported, never enforced — and never a reason the trading path fails to start."""
    assert env_file_is_group_or_world_readable(tmp_path / "nope.env") is False
