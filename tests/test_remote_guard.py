"""The remote-call guard: no test may push, or act on GitHub.

This file is the regression for a real incident. On 2026-08-30 a test run created
``snapshot/deploy-20260830``, pushed it, and opened pull request #20 against this
repository, carrying a fixture URL in the commit body. The cause was a default:
``glassbox.refresh.refresh`` shipped with its recording step enabled, and
``tests/test_repo_state.py`` calls ``refresh()`` directly and reaches a successful
deploy. That test predates the step by months and had no reason to know about it.

Making that one default opt-in fixed that one path. The guard fixes the class, and
these tests are what keep it fixed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quantlab.constants import PROJECT_ROOT
from tests.conftest import RemoteCallBlocked, _blocked_reason

# --------------------------------------------------------------------------- #
# The matcher                                                                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            [r"C:\Program Files\Git\cmd\git.exe", "push", "--set-upstream",
             "origin", "snapshot/deploy-20260830"],
            id="the-exact-argv-that-opened-pr-20",
        ),
        pytest.param(["git", "push", "origin", "main"], id="plain-push"),
        pytest.param(["git", "-C", "/tmp/r", "push", "origin", "x"],
                     id="push-behind-a-global-flag-and-its-value"),
        pytest.param(["gh", "pr", "create", "--base", "main"], id="gh-pr-create"),
        pytest.param([r"C:\bin\gh.exe", "api", "-X", "PATCH", "repos/o/r/pulls/1"],
                     id="gh-api-resolved-to-an-absolute-path"),
        pytest.param(["gh", "issue", "create", "--title", "x"], id="gh-issue"),
        pytest.param("git push origin main", id="given-as-a-string"),
    ],
)
def test_these_are_blocked(argv: list[str] | str) -> None:
    """Blocked when run inside the real checkout, which is where the harm is."""
    assert _blocked_reason(argv, PROJECT_ROOT) is not None
    assert _blocked_reason(argv, None) is not None      # inherited cwd == checkout


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["git", "log", "--oneline"], id="git-log"),
        pytest.param(["git", "init", "-b", "main"], id="git-init"),
        pytest.param(["git", "commit", "-m", "x"], id="git-commit"),
        pytest.param(["git", "rev-parse", "--verify", "refs/heads/x"],
                     id="git-rev-parse"),
        pytest.param(["git", "ls-remote", "--heads", "origin", "x"],
                     id="git-ls-remote-is-read-only"),
        pytest.param(["gh", "run", "list"], id="gh-run-list-is-read-only"),
        pytest.param(["npm", "run", "build:public"], id="npm"),
        pytest.param(["npx", "netlify", "deploy", "--prod"], id="netlify-deploy"),
        pytest.param([], id="empty-argv"),
    ],
)
def test_these_are_allowed(argv: list[str]) -> None:
    """The guard stops the suite ACTING on the repository, not looking at it.

    Local git matters here: several tests legitimately build throwaway repositories
    in tmp_path and run init/add/commit against them. A guard that broke those would
    be removed within a week, which is the failure mode of an over-broad guard.
    """
    assert _blocked_reason(argv, PROJECT_ROOT) is None


def test_the_program_name_is_matched_however_it_was_spelled() -> None:
    """`_default_git_runner` resolves through shutil.which before spawning.

    By the time argv reaches subprocess it reads an absolute path with a .exe
    suffix, so matching argv[0] verbatim would have missed the call that opened
    PR #20 — which is exactly what it did.
    """
    assert _blocked_reason([r"C:\Program Files\Git\cmd\git.exe", "push"],
                           PROJECT_ROOT) is not None
    assert _blocked_reason(["/usr/bin/git", "push"], PROJECT_ROOT) is not None
    assert _blocked_reason(["git.cmd", "push"], PROJECT_ROOT) is not None


# --------------------------------------------------------------------------- #
# The fixture actually intercepts                                              #
# --------------------------------------------------------------------------- #

def test_subprocess_run_is_intercepted() -> None:
    """Not just the matcher — the autouse fixture must be in the call path.

    No cwd, so the call would inherit the checkout: the shape the incident had.
    """
    with pytest.raises(RemoteCallBlocked) as excinfo:
        subprocess.run(["git", "push", "origin", "main"], capture_output=True)
    message = str(excinfo.value)
    assert "git push" in message
    assert "allow_remote" in message          # the message says how to opt in
    assert "#20" in message                   # ...and why the guard exists


def test_subprocess_popen_is_intercepted() -> None:
    """Popen too: `call` and `check_call` route through it, not through `run`."""
    with pytest.raises(RemoteCallBlocked):
        subprocess.Popen(["gh", "pr", "create"])


def test_a_keyword_args_call_is_intercepted() -> None:
    """`subprocess.run(args=[...])` must not slip past a positional-only check."""
    with pytest.raises(RemoteCallBlocked):
        subprocess.run(args=["git", "push"], capture_output=True)


def test_read_only_git_still_runs(tmp_path: Path) -> None:
    """The guard must not make the suite unable to use git at all."""
    done = subprocess.run(["git", "rev-parse", "--git-dir"],
                          cwd=str(tmp_path), capture_output=True, text=True)
    assert done.returncode != 0                # not a repo, but it RAN
    assert "not a git repository" in (done.stderr or "").lower()


# --------------------------------------------------------------------------- #
# Opting in                                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.allow_remote
def test_the_marker_lifts_the_guard(tmp_path: Path) -> None:
    """A marked test may push. This one asks git to, in a directory that is not a repo.

    So the call is genuinely un-guarded — it reaches git and git refuses it — while
    touching no network and no real repository. The assertion is that
    RemoteCallBlocked was NOT raised.
    """
    done = subprocess.run(["git", "push", "origin", "main"],
                          cwd=str(tmp_path), capture_output=True, text=True)
    assert done.returncode != 0
    assert "not a git repository" in (done.stderr or "").lower()


# --------------------------------------------------------------------------- #
# The discriminator: where it runs, not what it says                          #
# --------------------------------------------------------------------------- #

def test_a_push_in_a_throwaway_repo_is_allowed(tmp_path: Path) -> None:
    """`git push -u origin main` is argv-identical to the incident.

    Several tests legitimately build a repo and a bare upstream under tmp_path and
    push between them -- test_repo_state's unpushed-commit arithmetic needs exactly
    that. A guard that blocked them would be ripped out within a week, which is the
    failure mode of an over-broad guard. What separates them from the incident is
    not the command; it is that the incident ran against THIS checkout.
    """
    assert _blocked_reason(["git", "push", "-u", "origin", "main"], tmp_path) is None


def test_a_push_from_a_throwaway_repo_to_a_network_remote_is_still_blocked(
    tmp_path: Path,
) -> None:
    """tmp_path is not a licence to reach the internet."""
    for remote in (
        "https://github.com/danielfmonzon/quantlab.git",
        "git@github.com:danielfmonzon/quantlab.git",
        "ssh://git@github.com/o/r.git",
    ):
        assert _blocked_reason(["git", "push", remote, "main"], tmp_path) is not None


def test_a_subdirectory_of_the_checkout_counts_as_the_checkout() -> None:
    """`cwd=frontend/` is still this repository."""
    assert _blocked_reason(
        ["git", "push", "origin", "main"], PROJECT_ROOT / "frontend"
    ) is not None


# --------------------------------------------------------------------------- #
# gh is not bound to cwd, so it gets no cwd exemption                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["gh", "pr", "create"], id="gh-pr"),
        pytest.param(["gh", "api", "-X", "PATCH", "repos/o/r/pulls/1"], id="gh-api"),
        pytest.param(["gh", "issue", "create", "--title", "x"], id="gh-issue"),
        pytest.param(["gh", "pr", "create", "--repo", "danielfmonzon/quantlab"],
                     id="gh-pr-explicitly-naming-this-repo"),
    ],
)
@pytest.mark.parametrize(
    "cwd",
    [
        pytest.param(None, id="cwd-inherited"),
        pytest.param(PROJECT_ROOT, id="cwd-checkout"),
        pytest.param(Path("/tmp/throwaway"), id="cwd-elsewhere"),
    ],
)
def test_gh_is_blocked_regardless_of_cwd(argv: list[str], cwd: Path | None) -> None:
    """`gh` resolves its target BEFORE it looks at the working directory.

    It takes the repository from `--repo`, then from the `GH_REPO` environment
    variable, and only then from the git remote of cwd. So `gh pr create --repo
    danielfmonzon/quantlab` run from /tmp acts on this repository, and so does a bare
    `gh pr create` with GH_REPO exported. Giving gh the same cwd exemption that
    `git push` legitimately gets would leave the guard open in exactly the direction
    it was written to close.
    """
    assert _blocked_reason(argv, cwd) is not None


def test_only_git_push_carries_the_cwd_exemption(tmp_path: Path) -> None:
    """The asymmetry stated as one assertion, so it cannot drift unnoticed."""
    # git push is bound to the repo it runs in: a throwaway repo is harmless.
    assert _blocked_reason(["git", "push", "-u", "origin", "main"], tmp_path) is None
    # gh, from the same directory, is not.
    assert _blocked_reason(["gh", "pr", "create"], tmp_path) is not None


def test_the_gh_refusal_says_why_cwd_did_not_save_it(tmp_path: Path) -> None:
    reason = _blocked_reason(["gh", "api", "repos/o/r"], tmp_path)
    assert reason is not None
    assert "regardless of cwd" in reason
