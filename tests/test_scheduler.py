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
    cmds = tasks.build_install_commands(EXE)
    assert cmds == [
        [
            "schtasks", "/Create", "/TN", "quantlab-paper-run", "/SC", "WEEKLY",
            "/D", "MON,TUE,WED,THU,FRI", "/ST", "10:00",
            "/TR", f'"{EXE}" paper run-all --submit', "/F",
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


def test_install_with_confirm_runs_all_creates() -> None:
    runner = FakeRunner()
    rc = tasks.install("YES", exe=EXE, runner=runner, printer=lambda _m: None)
    assert rc == 0
    assert runner.commands == tasks.build_install_commands(EXE)
    assert [c[3] for c in runner.commands] == [
        "quantlab-paper-run", "quantlab-digest", "quantlab-weekly"
    ]
    assert len(runner.commands) == 3  # exactly three tasks installed


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
