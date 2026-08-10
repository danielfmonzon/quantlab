"""Working-tree provenance: is what is about to run the same as what is committed?

WHY. Two commands act on the outside world from whatever happens to be on disk: the Glass
Box refresh publishes a site, and ``schedule install`` writes tasks that will run this
checkout unattended for months. Both are perfectly happy to act on uncommitted edits, and
the artifacts they leave behind record a git commit — the snapshot manifest carries
``git_commit``, and every report carries ``version_string()``. If the tree was dirty, that
recorded commit is a claim the repository cannot substantiate: the published figures came
from code that exists nowhere but one laptop.

REPORT-ONLY, DELIBERATELY. This warns; it never blocks. A hard block would be the wrong
trade for a transparency site whose staleness is itself the bigger risk — refusing to
publish a fresh snapshot because a README line is unstaged would reintroduce the
fifteen-day-stale failure to protect a provenance detail. So the warning is recorded in the
run report and the chain proceeds.

Everything here is best-effort: no git, a detached HEAD, or no upstream configured produces
a ``note`` rather than an error, because none of those should stop a scheduled task.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

from quantlab.constants import PROJECT_ROOT
from quantlab.logging_setup import get_logger

log = get_logger("quantlab.repo_state")

_TIMEOUT_SECONDS = 15


class RepoState(BaseModel):
    """Git provenance of the checkout a command is about to act from."""

    checked: bool = False
    dirty: bool = False
    dirty_paths: list[str] = []
    unpushed_commits: int = 0
    branch: str | None = None
    upstream: str | None = None
    note: str | None = None

    @property
    def clean(self) -> bool:
        """True when the tree matches HEAD and HEAD matches its upstream."""
        return self.checked and not self.dirty and self.unpushed_commits == 0

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        if not self.checked:
            return out
        if self.dirty:
            shown = ", ".join(self.dirty_paths[:5])
            more = f" (+{len(self.dirty_paths) - 5} more)" if len(self.dirty_paths) > 5 else ""
            out.append(
                f"working tree is DIRTY: {len(self.dirty_paths)} path(s) differ from HEAD "
                f"[{shown}{more}] — artifacts will record a commit that does not contain them"
            )
        if self.unpushed_commits:
            out.append(
                f"{self.unpushed_commits} commit(s) not pushed to "
                f"{self.upstream or 'upstream'} — the recorded commit is not reachable "
                f"from the remote"
            )
        return out

    def render(self) -> list[str]:
        if not self.checked:
            return [f"  repo state    : NOT CHECKED ({self.note})"]
        if self.clean:
            return [f"  repo state    : clean ({self.branch} == {self.upstream})"]
        return ["  repo state    : WARNING"] + [f"                  {w}" for w in self.warnings]


def _git(args: list[str], repo: Path) -> tuple[int, str]:
    exe = shutil.which("git")
    if exe is None:
        return 127, "git not found on PATH"
    try:
        proc = subprocess.run(
            [exe, *args], cwd=str(repo), capture_output=True, text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def check_repo_state(repo: Path = PROJECT_ROOT) -> RepoState:
    """Best-effort git provenance for ``repo``. Never raises."""
    code, out = _git(["rev-parse", "--is-inside-work-tree"], repo)
    if code != 0 or "true" not in out:
        return RepoState(checked=False, note=out.strip()[:200] or "not a git work tree")

    state = RepoState(checked=True)

    code, out = _git(["status", "--porcelain"], repo)
    if code == 0:
        # Porcelain v1: two status columns, a space, then the path.
        paths = [line[3:].strip() for line in out.splitlines() if line.strip()]
        state.dirty_paths = sorted(paths)
        state.dirty = bool(paths)

    code, out = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    if code == 0:
        state.branch = out.strip() or None

    code, out = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"], repo)
    if code != 0:
        state.note = "no upstream configured for this branch; unpushed count unavailable"
        return state
    state.upstream = out.strip() or None

    code, out = _git(["rev-list", "--count", "@{upstream}..HEAD"], repo)
    if code == 0:
        try:
            state.unpushed_commits = int(out.strip().splitlines()[0])
        except (ValueError, IndexError):
            state.unpushed_commits = 0
    return state


def warn_if_unclean(state: RepoState, printer: object = print) -> list[str]:
    """Print and log each warning; return them. Report-only — nothing is blocked."""
    warnings = state.warnings
    for w in warnings:
        if callable(printer):
            printer(f"WARNING: {w}")
        log.warning("repo_state_unclean", detail=w)
    return warnings


__all__ = ["RepoState", "check_repo_state", "warn_if_unclean"]
