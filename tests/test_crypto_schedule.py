"""Crypto scheduling task + `paper run-all --asset-class` filter.

Nothing here executes schtasks or a broker: a fake runner captures schtasks
argv, and the run-all filter is exercised with `_run_one_paper` monkeypatched.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence

from quantlab import cli
from quantlab.config import APPROVED_STRATEGIES
from quantlab.scheduling import tasks

EXE = r"C:\venv\Scripts\quantlab.exe"


class FakeRunner:
    def __init__(self, returncode: int = 0):
        self.commands: list[list[str]] = []
        self._rc = returncode

    def __call__(self, cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), self._rc, stdout="ok", stderr="")


# --------------------------------------------------------------------------- #
# Scheduling: the crypto task                                                 #
# --------------------------------------------------------------------------- #

def test_crypto_install_command_is_exact() -> None:
    assert tasks.build_crypto_install_commands(EXE) == [
        [
            "schtasks", "/Create", "/TN", "quantlab-crypto-paper-run", "/SC", "DAILY",
            "/ST", "20:30",
            "/TR", f'"{EXE}" paper run-all --asset-class crypto --submit', "/F",
        ],
    ]


def test_crypto_uninstall_and_show_commands() -> None:
    assert tasks.build_crypto_uninstall_commands() == [
        ["schtasks", "/Delete", "/TN", "quantlab-crypto-paper-run", "/F"]
    ]
    assert tasks.build_crypto_show_commands() == [
        ["schtasks", "/Query", "/TN", "quantlab-crypto-paper-run", "/V", "/FO", "LIST"]
    ]


def test_equity_task_definitions_are_byte_identical() -> None:
    # Pin moved 2026-07-22: the equity paper-run /TR now carries
    # `--asset-class us_equity`. This test still guards that the *crypto* task
    # builders never mutate the equity task set; the frozen equity /TR itself was
    # deliberately rescoped so the 10:00 weekday task no longer leaks the crypto
    # strategies (run-all's default `all` iterated every APPROVED_STRATEGIES
    # entry). Digest and weekly definitions are unchanged.
    assert tasks.build_install_commands(EXE) == [
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
    # The crypto task is NOT among the equity task set.
    names = [c[3] for c in tasks.build_install_commands(EXE)]
    assert names == ["quantlab-paper-run", "quantlab-digest", "quantlab-weekly"]
    assert "quantlab-crypto-paper-run" not in names


def test_install_crypto_via_builder_runs_only_the_crypto_task() -> None:
    runner = FakeRunner()
    rc = tasks.install(
        "YES", exe=EXE, runner=runner, printer=lambda _m: None,
        builder=tasks.build_crypto_install_commands,
    )
    assert rc == 0
    # Execution shape changed 2026-07-22: the create is now followed by a
    # StartWhenAvailable post-step (catch-up persistence), applied on the crypto
    # builder path exactly as on the equity path.
    creates = tasks.build_crypto_install_commands(EXE)
    expected = [creates[0], tasks.build_start_when_available_command("quantlab-crypto-paper-run")]
    assert runner.commands == expected
    # only the crypto /Create among the schtasks commands, never the equity ones
    assert [c[3] for c in runner.commands if c[0] == "schtasks"] == ["quantlab-crypto-paper-run"]
    assert len(runner.commands) == 2  # one create + its post-step


def test_crypto_install_post_step_enables_catch_up() -> None:
    # The crypto path must also persist StartWhenAvailable, byte-for-byte.
    assert tasks.build_start_when_available_command("quantlab-crypto-paper-run") == [
        "powershell", "-NoProfile", "-Command",
        "$t = Get-ScheduledTask -TaskName 'quantlab-crypto-paper-run'; "
        "$s = $t.Settings; $s.StartWhenAvailable = $true; "
        "Set-ScheduledTask -TaskName 'quantlab-crypto-paper-run' -Settings $s",
    ]


def test_install_crypto_requires_confirm_yes() -> None:
    runner = FakeRunner()
    rc = tasks.install(
        None, exe=EXE, runner=runner, printer=lambda _m: None,
        builder=tasks.build_crypto_install_commands,
    )
    assert rc == 2
    assert runner.commands == []  # gated exactly like the equity install


# --------------------------------------------------------------------------- #
# CLI: paper run-all --asset-class filter                                     #
# --------------------------------------------------------------------------- #

def test_approved_by_asset_class_selects_subsets() -> None:
    assert cli._approved_by_asset_class("all") == list(APPROVED_STRATEGIES)
    assert cli._approved_by_asset_class("crypto") == ["crypto_trend", "crypto_voltarget"]
    assert cli._approved_by_asset_class("us_equity") == ["voltarget", "trend"]


def _capture_run_all(monkeypatch, asset_class: str, submit: bool) -> list[str]:
    ran: list[str] = []
    monkeypatch.setattr(
        cli, "_run_one_paper",
        lambda strategy, submit: (ran.append(strategy) or 0),
    )
    args = argparse.Namespace(asset_class=asset_class, submit=submit)
    assert cli.cmd_paper_run_all(args) == 0
    return ran


def test_run_all_default_all_is_current_behavior(monkeypatch) -> None:
    ran = _capture_run_all(monkeypatch, "all", submit=False)
    assert ran == list(APPROVED_STRATEGIES)  # byte-for-byte: full roster, in order


def test_run_all_crypto_runs_only_crypto_accounts(monkeypatch) -> None:
    ran = _capture_run_all(monkeypatch, "crypto", submit=True)
    assert ran == ["crypto_trend", "crypto_voltarget"]


def test_run_all_us_equity_runs_only_equity_accounts(monkeypatch) -> None:
    ran = _capture_run_all(monkeypatch, "us_equity", submit=True)
    assert ran == ["voltarget", "trend"]
