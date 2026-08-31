"""Shared pytest fixtures for quantlab tests."""

from __future__ import annotations

import re
import shlex
import subprocess
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quantlab.constants import PROJECT_ROOT
from quantlab.data import CANONICAL_COLUMNS
from quantlab.reporting import alerts as alerts_module

FrameFactory = Callable[..., pd.DataFrame]

# Env vars that, when all present, activate the real SMTP EmailChannel.
_EMAIL_ENV_VARS = (
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "ALERT_EMAIL_TO",
)


@pytest.fixture(autouse=True)
def isolate_alert_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """Redirect ALL alert output to ``tmp_path`` for every test in the suite.

    Autouse and unconditional. Two things are neutralised:

    * ``alerts.ALERTS_JSONL`` — ``FileChannel`` resolves this at send time, so
      any test that reaches real ``dispatch`` writes here instead of the
      production ``reports/alerts/alerts.jsonl``.
    * the SMTP env vars — a developer with a configured ``.env`` exported into
      their shell would otherwise have the test suite send REAL alert emails.

    This exists because the suite silently appended ~50 fixture alerts to the
    production log on 2026-07-22, corrupting the weekly review's ops stats.
    """
    redirected = tmp_path / "alerts" / "alerts.jsonl"
    monkeypatch.setattr(alerts_module, "ALERTS_JSONL", redirected)
    for name in _EMAIL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield redirected


@pytest.fixture
def make_frame() -> FrameFactory:
    """Return a builder producing a valid canonical EOD frame.

    Pass ``dates`` (a sequence of ``date``) plus any canonical column as a keyword
    to override its default column values, e.g. ``make_frame(dates, close=[...])``.
    """

    def _make(dates: Sequence[date], **overrides: object) -> pd.DataFrame:
        n = len(dates)
        data: dict[str, object] = {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000] * n,
            "adj_open": [100.0] * n,
            "adj_high": [101.0] * n,
            "adj_low": [99.0] * n,
            "adj_close": [100.5] * n,
            "adj_volume": [1000] * n,
            "dividend": [0.0] * n,
            "split_factor": [1.0] * n,
        }
        data.update(overrides)
        frame = pd.DataFrame({"date": pd.to_datetime(list(dates)), **data})
        return frame[list(CANONICAL_COLUMNS)]

    return _make


# --------------------------------------------------------------------------- #
# The remote-call guard                                                        #
# --------------------------------------------------------------------------- #

# Subcommands that reach the network and CHANGE something owned by the project.
# Read-only calls (`git log`, `gh run list`) are deliberately not here: the guard
# exists to stop the suite acting on the repository, not to stop it looking.
_BLOCKED_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "git": frozenset({"push"}),
    "gh": frozenset({"pr", "api", "issue"}),
}

# `git -C <dir> push` and `git -c k=v push` put the subcommand past a flag AND its
# value, so a naive argv[1] check misses exactly the form a wrapper is most likely
# to build.
_GLOBAL_FLAGS_TAKING_A_VALUE = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
})


class RemoteCallBlocked(RuntimeError):
    """A test tried to reach the real repository or the GitHub API."""


def _program(arg0: str) -> str:
    """The bare program name, however the caller spelled it.

    ``glassbox.refresh._default_git_runner`` resolves ``git`` through
    ``shutil.which`` before spawning it, so by the time argv reaches subprocess it
    reads ``C:\\Program Files\\Git\\cmd\\git.exe``. Matching on argv[0] verbatim would
    have missed the exact call that opened PR #20.

    SPLIT ON BOTH SEPARATORS, not on the host's. ``Path(...).name`` is
    platform-dependent: on Linux it does not treat ``\\`` as a separator, so a Windows
    argv comes back whole and the match silently fails. That matters here rather than
    in theory -- the incident's argv IS a Windows path, and CI runs on Linux, so a
    host-dependent split makes the regression test unable to verify the regression.
    """
    name = re.split(r"[\\/]", str(arg0))[-1].lower()
    for suffix in (".exe", ".cmd", ".bat"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _subcommand(argv: list[str]) -> str | None:
    """The first real subcommand, skipping global flags and their values."""
    i = 1
    while i < len(argv):
        token = str(argv[i])
        if token in _GLOBAL_FLAGS_TAKING_A_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return token.lower()
    return None


def _names_a_network_remote(argv: list[str]) -> bool:
    """Whether any argument is a URL that leaves this machine."""
    return any(
        tok.startswith(("http://", "https://", "ssh://", "git://", "git@"))
        for tok in argv
    )


def _inside_the_real_checkout(cwd: object) -> bool:
    """Whether a command would run against THIS repository.

    The discriminator, and the only one that separates the incident from the tests
    that must keep working. `git push -u origin main` is argv-identical in both:
    what differs is that the incident ran with cwd at the project root, while every
    legitimate test push runs in a throwaway repository under tmp_path.

    ``cwd=None`` means the process inherits the caller's directory, which during a
    test run is the checkout. That counts.
    """
    if cwd is None:
        return True
    try:
        resolved = Path(str(cwd)).resolve()
    except (OSError, ValueError):
        return True                       # unreadable: assume the dangerous case
    return resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents


def _blocked_reason(args: object, cwd: object = None) -> str | None:
    """Why this command may not run, or None when it is fine to run it."""
    if isinstance(args, (str, bytes)):
        argv = shlex.split(args.decode() if isinstance(args, bytes) else args)
    elif isinstance(args, (list, tuple)):
        argv = [str(a) for a in args]
    else:
        return None
    if not argv:
        return None
    program = _program(argv[0])
    blocked = _BLOCKED_SUBCOMMANDS.get(program)
    if blocked is None:
        return None
    sub = _subcommand(argv)
    if sub is None or sub not in blocked:
        return None

    # Two ways to be dangerous, and a test push to a local bare repo is neither.
    if _inside_the_real_checkout(cwd):
        return f"{program} {sub} inside the real checkout"
    if _names_a_network_remote(argv):
        return f"{program} {sub} to a network remote"
    return None


@pytest.fixture(autouse=True)
def block_remote_calls(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Refuse any subprocess that would push, or act on GitHub, during a test.

    THIS EXISTS BECAUSE IT ALREADY HAPPENED. On 2026-08-30 a test run created the
    branch ``snapshot/deploy-20260830``, pushed it, and opened pull request #20
    against this repository, with a fixture URL in the commit body. The cause was a
    default: ``glassbox.refresh.refresh`` shipped with its recording step enabled,
    and ``tests/test_repo_state.py`` — written long before that step existed — calls
    ``refresh()`` directly and reaches a successful deploy. It had no reason to know
    about a flag it had never heard of.

    That default is now opt-in, which fixes that one path. This fixture fixes the
    CLASS: no test can reach the network by forgetting something, because forgetting
    is the normal case and the guard does not depend on anyone remembering.

    It is the same shape as ``isolate_alert_log`` above, and for the same reason —
    that fixture exists because the suite once appended fifty fixture alerts to the
    production log. Test suites acquire side effects the way anything else does: one
    default at a time.

    OPT IN, DELIBERATELY NARROWLY, with ``@pytest.mark.allow_remote``. A test that
    genuinely needs to push should be rare enough that the marker is conspicuous in
    review, which is the point of making it a marker rather than a fixture argument.

    Read-only commands are untouched. ``git log``, ``git rev-parse``, ``git init``
    and ``gh run list`` all still work: the guard stops the suite ACTING on the
    repository, not looking at it. Local git that builds throwaway repositories in
    ``tmp_path`` — which several tests legitimately do — is unaffected.
    """
    if request.node.get_closest_marker("allow_remote"):
        yield
        return

    real_run = subprocess.run
    real_popen = subprocess.Popen

    def _check(args: object, cwd: object) -> None:
        reason = _blocked_reason(args, cwd)
        if reason is None:
            return
        raise RemoteCallBlocked(
            f"blocked `{reason}` during a test.\n"
            f"  argv: {args!r}\n"
            f"  A test must not push, or act on GitHub. PR #20 was opened by a test "
            f"run on 2026-08-30 exactly this way.\n"
            f"  If this call is genuinely intended, mark the test "
            f"`@pytest.mark.allow_remote` — and say in the test why."
        )

    def guarded_run(*args: object, **kwargs: object):  # noqa: ANN202
        _check(args[0] if args else kwargs.get("args"), kwargs.get("cwd"))
        return real_run(*args, **kwargs)  # type: ignore[arg-type]

    def guarded_popen(*args: object, **kwargs: object):  # noqa: ANN202
        _check(args[0] if args else kwargs.get("args"), kwargs.get("cwd"))
        return real_popen(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)
    yield
