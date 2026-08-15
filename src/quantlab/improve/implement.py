"""`quantlab implement PROP-n` — apply on a branch, prove it, push, and STOP.

THE STOP IS THE FEATURE. This module creates ``prop/{n}``, applies the change, runs the
full gate battery, writes an implementation report into the proposal, commits, pushes,
and ends. It does not merge. It cannot merge: there is no code path here that runs
``git merge``, ``git rebase``, or a push to ``main``, and a test asserts that by reading
this file's own source. Merge is Daniel's, via pull request, after Quant Lead review.

WHY THE HUMAN GATE IS STRUCTURAL AND NOT A CONVENTION. The pipeline's whole claim is
that an automated loop can improve this system without being trusted. A loop that can
merge its own work is trusted by construction — every safety property downstream of it
reduces to "the analysis was right", which is the one thing that cannot be guaranteed.
Keeping the last step human means the worst case of a wrong proposal is a branch nobody
merges, which costs a review and nothing else.

DEFENCE IN DEPTH ON THE FIREWALL. `propose` already refused forbidden paths before
writing the document. This re-runs the same check against the ACTUAL diff, because the
document and the diff are different artifacts and only the second one becomes a commit.
A patch that quietly edits `config/risk.yaml` while the proposal says it edits the
frontend is caught here, at the point where it would otherwise matter.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from quantlab.constants import PROJECT_ROOT
from quantlab.improve import firewall
from quantlab.improve import propose as propose_mod

BRANCH_PREFIX = "prop/"
# The branch this pipeline must never write to. Named once so the guard and the report
# agree, and so a reader can find every mention of it.
PROTECTED_BRANCH = "main"

REPORT_ANCHOR = "<!-- IMPLEMENTATION REPORT ANCHOR -->"


class Runner(Protocol):
    def __call__(
        self, cmd: Sequence[str], cwd: Path
    ) -> subprocess.CompletedProcess[str]: ...


def _default_runner(cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` in ``cwd``. Never uses a shell — arguments stay a list end to end."""
    return subprocess.run(
        list(cmd), cwd=str(cwd), capture_output=True, text=True, shell=False,
    )


class NotOnBranch(RuntimeError):
    """The working branch is not ``prop/{n}``. Nothing further will run."""


@dataclass
class Gate:
    """One verification command and what it said."""

    name: str
    cmd: tuple[str, ...]
    ok: bool = False
    skipped: bool = False
    skip_reason: str = ""
    detail: str = ""

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.ok else "FAIL"


@dataclass
class ImplementResult:
    number: int
    branch: str
    proposal_path: Path
    started_at: datetime
    applied: bool = False
    apply_detail: str = ""
    diffstat: str = ""
    changed_paths: list[str] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)
    firewall_text: str = ""
    firewall_ok: bool = True
    committed: bool = False
    commit_sha: str = ""
    pushed: bool = False
    push_detail: str = ""
    aborted: str = ""
    # False while the report is being written INTO the proposal, true once the run has
    # finished. The report has to be written before the commit — it is part of what gets
    # committed — so at write time `committed` and `pushed` are necessarily still False.
    # Rendering them as False into the durable artifact stated the opposite of the truth:
    # the first dogfood run pushed successfully and left a file on the branch claiming it
    # had done neither. The file version therefore reports what is KNOWN at write time and
    # says plainly that the commit and push follow; the console version, rendered last,
    # carries the SHA and the push result.
    finalised: bool = False

    @property
    def gates_ok(self) -> bool:
        return all(g.ok or g.skipped for g in self.gates)

    @property
    def ok(self) -> bool:
        return not self.aborted and self.firewall_ok and self.gates_ok

    def render(self) -> str:
        stamp = self.started_at.isoformat().replace("+00:00", "Z")
        lines = [
            "## Implementation report",
            "",
            f"_implemented {stamp}  |  branch `{self.branch}`  |  "
            f"status: **{'GATES PASSED' if self.ok else 'NEEDS ATTENTION'}**_",
            "",
        ]
        if self.aborted:
            lines += [f"**ABORTED:** {self.aborted}", ""]

        lines += ["### Diff stat", "", "```", self.diffstat.strip() or "(no changes)", "```", ""]

        lines += ["### Firewall re-check (against the actual diff)", "", "```",
                  self.firewall_text.strip(), "```", ""]

        lines += ["### Gates", "", "| gate | result | detail |", "|---|---|---|"]
        for g in self.gates:
            detail = (g.skip_reason if g.skipped else g.detail).replace("|", "\\|")
            lines.append(f"| `{g.name}` | {g.status} | {detail} |")
        lines.append("")

        lines += ["### Branch", "", f"- branch: `{self.branch}`"]
        if self.finalised:
            lines.append(f"- committed: **{self.committed}**")
            if self.commit_sha:
                lines.append(f"- commit: `{self.commit_sha}`")
            lines.append(f"- pushed: **{self.pushed}** — {self.push_detail or 'n/a'}")
        else:
            lines.append(
                "- commit and push: performed immediately after this report was written "
                "into the proposal, since the report is part of what gets committed. The "
                "resulting SHA and push result are in the run output, and the commit "
                "itself is the one carrying this file."
            )
        lines += [
            "",
            "### Merge gate — STOPPED HERE",
            "",
            f"This pipeline does not merge. The change sits on `{self.branch}` and "
            f"`{PROTECTED_BRANCH}` is untouched. **Daniel merges via pull request after "
            "Quant Lead review.** There is no automated path to "
            f"`{PROTECTED_BRANCH}` in `quantlab implement` — verified by test, not by "
            "convention.",
            "",
        ]
        return "\n".join(lines)


def _git(runner: Runner, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return runner(["git", *args], root)


def current_branch(runner: Runner, root: Path) -> str:
    return _git(runner, root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def _assert_on_prop_branch(runner: Runner, root: Path, number: int) -> str:
    """The guard. Called before the commit and again before the push.

    Two independent calls on purpose: a single check at the top would be a check of what
    the branch was, not of what it is at the moment something is written.
    """
    branch = current_branch(runner, root)
    expected = f"{BRANCH_PREFIX}{number}"
    if branch != expected:
        raise NotOnBranch(
            f"refusing to write: expected branch {expected!r}, on {branch!r}. "
            f"`implement` never commits or pushes anywhere but its own prop branch, and "
            f"never to {PROTECTED_BRANCH!r}."
        )
    return branch


def _frontend_touched(paths: Sequence[str]) -> bool:
    return any(p.startswith("frontend/") for p in paths)


def implement(
    number: int,
    *,
    patch: Path | None = None,
    root: Path | None = None,
    proposals_dir: Path | None = None,
    runner: Runner | None = None,
    push: bool = True,
    now: datetime | None = None,
) -> ImplementResult:
    """Branch, apply, gate, report, commit, push, stop."""
    run = runner if runner is not None else _default_runner
    repo = root if root is not None else PROJECT_ROOT
    started = now or datetime.now(UTC)

    proposal_path = propose_mod.find_proposal(number, proposals_dir)
    branch = f"{BRANCH_PREFIX}{number}"
    result = ImplementResult(
        number=number, branch=branch, proposal_path=proposal_path, started_at=started,
    )

    def abort(reason: str) -> ImplementResult:
        result.aborted = reason
        return result

    # -- 1. branch ---------------------------------------------------------
    # `checkout -B` is deliberate: re-running `implement` for the same proposal resets
    # the branch rather than failing or stacking a second attempt on the first.
    made = _git(run, repo, "checkout", "-B", branch)
    if made.returncode != 0:
        return abort(f"could not create branch {branch}: {made.stderr.strip()}")

    # -- 2. apply ----------------------------------------------------------
    if patch is not None:
        applied = _git(run, repo, "apply", "--index", str(patch))
        if applied.returncode != 0:
            return abort(f"patch did not apply: {applied.stderr.strip()}")
        result.applied = True
        result.apply_detail = f"applied {patch}"
    else:
        result.apply_detail = (
            "no --patch given; using changes already present in the working tree"
        )
        # ONLY in worktree mode. `git apply --index` has already staged exactly the
        # patch's files, and an `add -A` on top of it would sweep every unrelated dirty
        # path in the checkout into the proposal's commit — which is precisely what a
        # reviewer reading "affected files: frontend/src/content/copy.ts" would not
        # expect. Worktree mode has no such boundary to draw, so it stages everything
        # and the diff stat in the report shows exactly what that turned out to be;
        # nothing is hidden, but `--patch` is the mode with a defensible blast radius.
        _git(run, repo, "add", "-A")

    # -- 3. what actually changed -----------------------------------------
    result.diffstat = _git(run, repo, "diff", "--cached", "--stat").stdout.strip()
    names = _git(run, repo, "diff", "--cached", "--name-only").stdout.strip()
    result.changed_paths = [p for p in names.splitlines() if p]

    if not result.changed_paths:
        return abort("nothing to implement: the staged diff is empty")

    # -- 4. firewall, against the DIFF this time --------------------------
    verdict = firewall.check(affected_paths=result.changed_paths)
    result.firewall_ok = verdict.allowed
    result.firewall_text = verdict.render()
    if not verdict.allowed:
        # Unstage so a refused attempt does not leave a staged forbidden change behind.
        _git(run, repo, "reset")
        return abort(
            "the actual diff touches a firewall path; see the refusal above. "
            "Nothing was committed."
        )

    # -- 5. gates ----------------------------------------------------------
    result.gates = _run_gates(run, repo, result.changed_paths)

    # -- 6. report into the proposal --------------------------------------
    write_report(proposal_path, result)
    _git(run, repo, "add", str(proposal_path))

    # -- 7. commit ---------------------------------------------------------
    _assert_on_prop_branch(run, repo, number)
    title = proposal_path.stem
    message = (
        f"PROP-{number}: {title}\n\n"
        f"Implemented by `quantlab implement`. Gates: "
        f"{'all passed' if result.gates_ok else 'SEE REPORT — not all passed'}.\n"
        f"Merge is human-only: Daniel merges via PR after Quant Lead review."
    )
    committed = _git(run, repo, "commit", "-m", message)
    if committed.returncode != 0:
        return abort(f"commit failed: {committed.stderr.strip() or committed.stdout.strip()}")
    result.committed = True
    result.commit_sha = _git(run, repo, "rev-parse", "--short", "HEAD").stdout.strip()

    # -- 8. push, then STOP ------------------------------------------------
    if push:
        _assert_on_prop_branch(run, repo, number)
        pushed = _git(run, repo, "push", "--set-upstream", "origin", branch)
        result.pushed = pushed.returncode == 0
        if result.pushed:
            result.push_detail = f"pushed to origin/{branch}"
        else:
            noise = (pushed.stderr or pushed.stdout).strip().splitlines()
            result.push_detail = f"push failed: {noise[-1] if noise else 'unknown error'}"
    else:
        result.push_detail = "push suppressed (--no-push)"

    # Only the console rendering may claim the commit and push, and only now that both
    # have actually happened. There is deliberately nothing after this point.
    result.finalised = True
    return result


def _run_gates(run: Runner, repo: Path, changed: Sequence[str]) -> list[Gate]:
    """ruff, mypy, pytest, the frontend suite, and verify-dist when the site is touched."""
    gates: list[Gate] = []

    def add(name: str, cmd: tuple[str, ...], *, cwd: Path | None = None,
            skip_reason: str = "") -> None:
        gate = Gate(name=name, cmd=cmd)
        if skip_reason:
            gate.skipped, gate.skip_reason = True, skip_reason
            gates.append(gate)
            return
        proc = run(list(cmd), cwd or repo)
        gate.ok = proc.returncode == 0
        tail = (proc.stdout or proc.stderr).strip().splitlines()
        gate.detail = tail[-1][:200] if tail else f"exit {proc.returncode}"
        gates.append(gate)

    add("ruff", ("uv", "run", "ruff", "check", "."))
    add("mypy", ("uv", "run", "mypy", "src/quantlab"))
    add("pytest", ("uv", "run", "pytest", "-q"))

    frontend = repo / "frontend"
    npm = shutil.which("npm")
    if not _frontend_touched(changed):
        add("frontend", (), skip_reason="no frontend/ path in the diff")
    elif npm is None:
        add("frontend", (), skip_reason="npm not on PATH")
    else:
        add("frontend", (npm, "run", "test"), cwd=frontend)
        add("frontend-lint", (npm, "run", "lint"), cwd=frontend)

    # verify-dist only means something against a built site.
    if _frontend_touched(changed):
        if (frontend / "dist").is_dir():
            add("verify-dist", ("uv", "run", "quantlab", "glassbox", "verify-dist"))
        else:
            add("verify-dist", (), skip_reason="frontend/dist not built in this checkout")
    else:
        add("verify-dist", (), skip_reason="site not touched")

    return gates


def write_report(proposal_path: Path, result: ImplementResult) -> None:
    """Append the report at the anchor, replacing any report from an earlier attempt."""
    text = proposal_path.read_text(encoding="utf-8")
    head = text.split(REPORT_ANCHOR)[0] if REPORT_ANCHOR in text else text.rstrip() + "\n\n---\n\n"
    body = head + REPORT_ANCHOR + "\n\n" + result.render()
    proposal_path.write_text(body.rstrip() + "\n", encoding="utf-8")


__all__ = [
    "BRANCH_PREFIX",
    "PROTECTED_BRANCH",
    "REPORT_ANCHOR",
    "Gate",
    "ImplementResult",
    "NotOnBranch",
    "Runner",
    "current_branch",
    "implement",
    "write_report",
]
