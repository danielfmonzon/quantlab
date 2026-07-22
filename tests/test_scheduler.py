"""Scheduler tests: exact schtasks argv, confirm gate, idempotent uninstall.

Nothing here executes schtasks — a fake runner captures every command instead.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

from quantlab.scheduling import tasks

EXE = r"C:\venv\Scripts\quantlab.exe"


class FakeRunner:
    def __init__(self, returncode: int = 0):
        self.commands: list[list[str]] = []
        self._rc = returncode

    def __call__(self, cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), self._rc, stdout="ok", stderr="")


def test_build_install_commands_are_exact() -> None:
    # Pin moved 2026-07-22: the equity paper-run /TR gained
    # `--asset-class us_equity`. Before this, the task ran `paper run-all
    # --submit`, which defaults to `--asset-class all` and iterated the whole
    # APPROVED_STRATEGIES roster; once crypto accounts were approved, the 10:00
    # equity task began double-running the crypto strategies (already covered by
    # quantlab-crypto-paper-run). The filter scopes this task to equity only.
    cmds = tasks.build_install_commands(EXE)
    assert cmds == [
        [
            "schtasks", "/Create", "/TN", "quantlab-paper-run", "/SC", "WEEKLY",
            "/D", "MON,TUE,WED,THU,FRI", "/ST", "10:00",
            "/TR", f'"{EXE}" paper run-all --asset-class us_equity --submit', "/F",
        ],
        [
            "schtasks", "/Create", "/TN", "quantlab-digest", "/SC", "WEEKLY",
            "/D", "MON,TUE,WED,THU,FRI", "/ST", "16:45",
            "/TR", f'"{EXE}" digest', "/F",
        ],
        [
            "schtasks", "/Create", "/TN", "quantlab-weekly", "/SC", "WEEKLY",
            "/D", "FRI", "/ST", "17:00",
            "/TR", f'"{EXE}" weekly', "/F",
        ],
    ]


def test_install_requires_confirm_yes() -> None:
    runner = FakeRunner()
    rc = tasks.install(confirm=None, exe=EXE, runner=runner, printer=lambda _m: None)
    assert rc == 2
    assert runner.commands == []  # nothing executed without confirmation


def test_install_wrong_confirm_refuses() -> None:
    runner = FakeRunner()
    assert tasks.install("yes", exe=EXE, runner=runner, printer=lambda _m: None) == 2
    assert runner.commands == []


def _interleave_with_post_steps(creates: list[list[str]]) -> list[list[str]]:
    """Each /Create is immediately followed by its StartWhenAvailable post-step."""
    out: list[list[str]] = []
    for c in creates:
        out.append(c)
        out.append(tasks.build_start_when_available_command(c[3]))
    return out


def test_install_with_confirm_runs_all_creates() -> None:
    runner = FakeRunner()
    rc = tasks.install("YES", exe=EXE, runner=runner, printer=lambda _m: None)
    assert rc == 0
    # Execution shape changed 2026-07-22: each create is now paired with a
    # PowerShell StartWhenAvailable post-step (catch-up persistence), so the
    # executed sequence interleaves create -> post-step per task.
    assert runner.commands == _interleave_with_post_steps(tasks.build_install_commands(EXE))
    # the three /Create commands themselves, in order
    assert [c[3] for c in runner.commands if c[0] == "schtasks"] == [
        "quantlab-paper-run", "quantlab-digest", "quantlab-weekly"
    ]
    assert len(runner.commands) == 6  # three creates + three post-steps


def test_start_when_available_command_is_exact() -> None:
    for name in ("quantlab-paper-run", "quantlab-digest", "quantlab-weekly",
                 "quantlab-crypto-paper-run"):
        cmd = tasks.build_start_when_available_command(name)
        assert cmd == [
            "powershell", "-NoProfile", "-Command",
            f"$t = Get-ScheduledTask -TaskName '{name}'; "
            f"$s = $t.Settings; $s.StartWhenAvailable = $true; "
            f"Set-ScheduledTask -TaskName '{name}' -Settings $s",
        ]


def test_install_preview_includes_post_steps() -> None:
    messages: list[str] = []
    rc = tasks.install(confirm=None, exe=EXE, runner=FakeRunner(), printer=messages.append)
    assert rc == 2  # preview only, nothing executed
    # one powershell post-step preview line per task, so what prints is what runs
    assert sum("powershell" in m and "StartWhenAvailable" in m for m in messages) == 3


def test_failing_post_step_warns_but_install_succeeds() -> None:
    messages: list[str] = []

    class PartialRunner:
        """schtasks creates succeed; every powershell post-step fails."""

        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def __call__(self, cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
            self.commands.append(list(cmd))
            rc = 0 if cmd[0] == "schtasks" else 1
            return subprocess.CompletedProcess(list(cmd), rc, stdout="", stderr="access denied")

    runner = PartialRunner()
    rc = tasks.install("YES", exe=EXE, runner=runner, printer=messages.append)
    assert rc == 0  # a post-step failure must NOT fail the install
    assert any("WARNING" in m and "StartWhenAvailable" in m for m in messages)
    # every task was still created despite the warnings
    assert [c[3] for c in runner.commands if c[0] == "schtasks"] == [
        "quantlab-paper-run", "quantlab-digest", "quantlab-weekly"
    ]


def test_uninstall_is_idempotent_even_when_absent() -> None:
    # schtasks returns nonzero when a task is missing; uninstall must still be a
    # clean success (idempotent).
    runner = FakeRunner(returncode=1)
    rc = tasks.uninstall(runner=runner, printer=lambda _m: None)
    assert rc == 0
    assert runner.commands == tasks.build_uninstall_commands()
    assert [c[3] for c in runner.commands] == [
        "quantlab-paper-run", "quantlab-digest", "quantlab-weekly"
    ]


def test_show_queries_all_tasks() -> None:
    runner = FakeRunner()
    tasks.show(runner=runner, printer=lambda _m: None)
    assert [c[3] for c in runner.commands] == [
        "quantlab-paper-run", "quantlab-digest", "quantlab-weekly"
    ]
    assert all(c[1] == "/Query" for c in runner.commands)
