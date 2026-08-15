"""Every default artifact path must be anchored to the repo root, never to the CWD.

WHY THIS FILE EXISTS. On 2026-08-14 the first UNATTENDED `glassbox refresh` aborted with
`PermissionError: [WinError 5] Access is denied: 'reports'`. Nothing had a handle on the
project's `reports/` tree; the message named a directory that had never existed. The
scheduled task supplies no working directory, so the process ran in `C:\\Windows\\System32`,
and `snapshot.DEFAULT_REPORT_DIR` was a bare relative `Path("reports") / "glassbox"`.
`mkdir(parents=True)` recursed into the missing parent and tried to create
`C:\\Windows\\System32\\reports`, which is denied.

The defect was invisible for weeks because every READ goes through `GlassboxPaths`, which
derives from `PROJECT_ROOT`, and because every manual run happened to start in the repo
root. Only the unattended path had a different CWD, and there was exactly one of those.

These tests therefore assert the INVARIANT rather than the incident: a default path that
resolves differently depending on where the process was started is a bug, whether or not
it currently crashes. The `verify_dist` case is the sharper one — a missing `.env` there
is not an error, so a CWD-relative default degrades the gate to a silent no-op that still
reports PASS.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from quantlab.constants import PROJECT_ROOT
from quantlab.glassbox.serve import DEFAULT_SNAPSHOT_DIR
from quantlab.glassbox.snapshot import DEFAULT_REPORT_DIR
from quantlab.glassbox.verify_dist import DEFAULT_ENV_PATH

# Every module-level default that names a location on disk.
ANCHORED_DEFAULTS = {
    "snapshot.DEFAULT_REPORT_DIR": DEFAULT_REPORT_DIR,
    "serve.DEFAULT_SNAPSHOT_DIR": DEFAULT_SNAPSHOT_DIR,
    "verify_dist.DEFAULT_ENV_PATH": DEFAULT_ENV_PATH,
}


@pytest.mark.parametrize("name", sorted(ANCHORED_DEFAULTS))
def test_default_path_is_absolute(name: str) -> None:
    """A relative default is resolved against the CWD, which no caller controls."""
    assert ANCHORED_DEFAULTS[name].is_absolute(), (
        f"{name} is relative; under the scheduler it resolves against "
        f"C:\\Windows\\System32, not the repo"
    )


@pytest.mark.parametrize("name", sorted(ANCHORED_DEFAULTS))
def test_default_path_lives_under_project_root(name: str) -> None:
    assert ANCHORED_DEFAULTS[name].is_relative_to(PROJECT_ROOT), (
        f"{name} resolves outside the repo root {PROJECT_ROOT}"
    )


@pytest.mark.parametrize("name", sorted(ANCHORED_DEFAULTS))
def test_default_path_does_not_move_with_the_cwd(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reproduction, made cheap: run from a foreign CWD and re-resolve.

    `monkeypatch.chdir` stands in for the scheduler's `C:\\Windows\\System32`. Before the
    fix, `Path("reports") / "glassbox"` resolved under `tmp_path` here and under the repo
    when pytest was started from the repo root — the same expression naming two different
    directories is exactly the defect.
    """
    before = ANCHORED_DEFAULTS[name].resolve()
    monkeypatch.chdir(tmp_path)
    assert Path(ANCHORED_DEFAULTS[name]).resolve() == before
    assert Path.cwd() != PROJECT_ROOT, "the test did not actually leave the repo root"


def test_no_bare_relative_path_defaults_in_glassbox() -> None:
    """A structural guard: catch the NEXT one, not just the three we found.

    Parses every module in the package and fails on any module-level assignment whose
    value is a `Path("literal")` — with or without `/` operands chained onto it — that
    does not start from an anchored name. Assertions on the three known constants above
    only prove today's fix; this proves the class stays closed.
    """
    package = Path(PROJECT_ROOT) / "src" / "quantlab" / "glassbox"
    anchors = {"PROJECT_ROOT", "CONFIG_DIR"}
    offenders: list[str] = []

    def base_of(node: ast.expr) -> ast.expr:
        """Walk down the left spine of a `a / b / c` chain to its leftmost operand."""
        while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
        return node

    for module in sorted(package.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in tree.body:  # module level only; function-local paths are the
            if not isinstance(node, ast.Assign):  # caller's business, not a default
                continue
            base = base_of(node.value)
            if not (isinstance(base, ast.Call) and getattr(base.func, "id", "") == "Path"):
                continue
            if not base.args or not isinstance(base.args[0], ast.Constant):
                continue
            literal = base.args[0].value
            if not isinstance(literal, str) or Path(literal).is_absolute():
                continue
            targets = ", ".join(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
            offenders.append(f"{module.name}:{node.lineno} {targets} = Path({literal!r})")

    assert not offenders, (
        "module-level path default(s) resolved against the CWD instead of an anchor "
        f"({' or '.join(sorted(anchors))}):\n  " + "\n  ".join(offenders)
    )


def test_scheduled_entry_points_do_not_depend_on_cwd(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:
    """Importing the scheduled chain from a foreign CWD must still find the repo.

    `PROJECT_ROOT` derives from `__file__`, so this holds by construction — the test
    pins it, because the whole fix rests on that one property.
    """
    monkeypatch.chdir(tmp_path)
    assert PROJECT_ROOT.is_absolute()
    assert (PROJECT_ROOT / "src" / "quantlab" / "constants.py").is_file()
    assert Path(os.getcwd()) != PROJECT_ROOT
