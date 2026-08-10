"""Repo-provenance tests: warn on a dirty or unpushed tree, never block.

``check_repo_state`` shells out to git, so these tests build real throwaway repositories in
``tmp_path`` rather than mocking subprocess — the thing worth testing is that the porcelain
parsing and the upstream arithmetic are right, and a mock would assert my own assumptions
back at me.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from quantlab.glassbox.refresh import refresh
from quantlab.repo_state import RepoState, check_repo_state, warn_if_unclean
from quantlab.scheduling import tasks

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True,
        capture_output=True, text=True,
    )


def _repo(tmp_path: Path, name: str = "work") -> Path:
    """A committed git repo with an 'origin' it is in sync with."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "first")
    _git(repo, "branch", "-M", "main")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo


# --------------------------------------------------------------------------- #
# Detection                                                                   #
# --------------------------------------------------------------------------- #


def test_a_clean_synced_tree_reports_clean(tmp_path: Path) -> None:
    state = check_repo_state(_repo(tmp_path))
    assert state.checked is True
    assert state.clean is True
    assert state.dirty is False
    assert state.unpushed_commits == 0
    assert state.branch == "main"
    assert state.upstream == "origin/main"
    assert state.warnings == []
    assert "clean" in "\n".join(state.render())


def test_an_unstaged_edit_is_dirty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    state = check_repo_state(repo)
    assert state.dirty is True
    assert state.dirty_paths == ["a.txt"]
    assert state.clean is False
    assert any("DIRTY" in w for w in state.warnings)
    # The warning says WHY it matters, not just that it happened.
    assert any("does not contain them" in w for w in state.warnings)


def test_an_untracked_file_is_dirty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    state = check_repo_state(repo)
    assert state.dirty is True
    assert "new.txt" in state.dirty_paths


def test_a_staged_file_is_dirty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "b.txt").write_text("y\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    state = check_repo_state(repo)
    assert state.dirty is True
    assert "b.txt" in state.dirty_paths


def test_unpushed_commits_are_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for i in range(2):
        (repo / f"c{i}.txt").write_text("z\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", f"local {i}")
    state = check_repo_state(repo)
    assert state.dirty is False            # tree matches HEAD...
    assert state.unpushed_commits == 2     # ...but HEAD is ahead of origin
    assert state.clean is False
    assert any("not pushed" in w for w in state.warnings)


def test_no_upstream_is_a_note_not_a_crash(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "first")
    state = check_repo_state(repo)
    assert state.checked is True
    assert state.note is not None and "upstream" in state.note
    assert state.unpushed_commits == 0     # unavailable, not invented


def test_a_non_git_directory_is_reported_as_not_checked(tmp_path: Path) -> None:
    state = check_repo_state(tmp_path / "nowhere")
    assert state.checked is False
    assert state.clean is False             # unknown is not clean
    assert state.warnings == []             # ...but it raises no false alarm either
    assert "NOT CHECKED" in "\n".join(state.render())


def test_many_dirty_paths_are_summarised_not_dumped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for i in range(9):
        (repo / f"f{i}.txt").write_text("x\n", encoding="utf-8")
    state = check_repo_state(repo)
    warning = next(w for w in state.warnings if "DIRTY" in w)
    assert "9 path(s)" in warning
    assert "+4 more" in warning             # 5 shown, the rest counted


def test_warn_if_unclean_reports_without_raising() -> None:
    state = RepoState(checked=True, dirty=True, dirty_paths=["x.py"], unpushed_commits=1,
                      branch="main", upstream="origin/main")
    printed: list[str] = []
    warnings = warn_if_unclean(state, printer=printed.append)
    assert len(warnings) == 2
    assert all(p.startswith("WARNING:") for p in printed)


# --------------------------------------------------------------------------- #
# Report-only: neither caller is blocked                                      #
# --------------------------------------------------------------------------- #


def test_the_refresh_chain_records_the_warning_and_proceeds() -> None:
    """A dirty tree must not stop a publish: staleness is the bigger risk (see repo_state)."""
    dirty = RepoState(checked=True, dirty=True, dirty_paths=["src/x.py"],
                      branch="main", upstream="origin/main")

    class _Report:
        def render(self) -> str:
            return "REPORT"

    class _Snap:
        def __init__(self) -> None:
            self.report = _FakeSanitization()
            self.manifest = type("M", (), {"endpoint_count": 1})()
            self.files_written = ["a.json"]

    class _FakeSanitization:
        passed = True
        redactions: list[object] = []
        failures: list[object] = []
        redaction_count = 0

        def render(self) -> str:
            return "SANITIZATION"

    class _Verified:
        report = _FakeSanitization()
        content = type("C", (), {"passed": True, "failures": []})()
        passed = True
        redactable_findings: list[str] = []
        files_text = 3

        def render(self) -> str:
            return "VERIFY"

    calls: list[list[str]] = []

    def runner(cmd, cwd):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), 0, stdout="Website URL: https://x", stderr="")

    result = refresh(
        runner=runner, alert_fn=lambda _a: [], repo_state=dirty,
        snapshot_fn=lambda out, **kw: _Snap(),
        verify_fn=lambda d, **kw: _Verified(),
    )
    assert result.deployed is True                     # NOT blocked
    assert result.repo is not None and result.repo.dirty is True
    # The warning travels with the report, so the provenance claim is never silent.
    rendered = result.render()
    assert "PROVENANCE" in rendered
    assert "WARNING" in rendered
    assert "src/x.py" in rendered


def test_schedule_install_warns_but_still_installs() -> None:
    dirty = RepoState(checked=True, dirty=False, unpushed_commits=3,
                      branch="main", upstream="origin/main")
    messages: list[str] = []
    ran: list[list[str]] = []

    def runner(cmd):  # type: ignore[no-untyped-def]
        ran.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

    rc = tasks.install("YES", exe=r"C:\v\quantlab.exe", runner=runner,
                       printer=messages.append, repo_state=dirty)
    assert rc == 0                                     # installed anyway
    assert any("WARNING" in m and "not pushed" in m for m in messages)
    assert [c[3] for c in ran if c[0] == "schtasks"] == [
        "quantlab-paper-run", "quantlab-digest", "quantlab-weekly",
        "quantlab-glassbox-refresh",
    ]


def test_schedule_install_preview_also_warns() -> None:
    """The warning must appear on the refusal path too, before anything is created."""
    dirty = RepoState(checked=True, dirty=True, dirty_paths=["a.py"],
                      branch="main", upstream="origin/main")
    messages: list[str] = []
    rc = tasks.install(None, exe=r"C:\v\quantlab.exe",
                       runner=lambda _c: subprocess.CompletedProcess([], 0, "", ""),
                       printer=messages.append, repo_state=dirty)
    assert rc == 2
    assert any("WARNING" in m for m in messages)
