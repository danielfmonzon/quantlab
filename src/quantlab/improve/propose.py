"""`quantlab propose` — write a proposal, never a line of code.

The command reads the artifacts listed in :mod:`quantlab.improve.sources`, runs the
candidate through :mod:`quantlab.improve.firewall`, and — only if the firewall passes —
writes ``docs/proposals/PROP-{n}-{slug}.md``.

IT NEVER EDITS CODE. Not as a matter of discipline but of construction: the only write
this module performs is the proposal file itself, and the only directory it can write
into is ``docs/proposals``. Applying a change is `implement`'s job, on a branch, behind
a human merge gate.

The separation matters because the two halves have genuinely different risk. Writing a
document is safe and can be wrong without cost. Touching the tree is neither. Keeping
them in separate commands means the analysis can run as often as you like — including
unattended — without any path by which a bad observation becomes a bad commit.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quantlab.constants import PROJECT_ROOT
from quantlab.improve import firewall, sources

PROPOSALS_DIR = PROJECT_ROOT / "docs" / "proposals"

# THE ONLY NAMESPACE THIS COMMAND MAY EVER PUSH.
# `propose` publishes the analysis so it survives the loss of this checkout. That means it
# needs the network, and a command that can push is a command that can push to the wrong
# place. The blast radius is therefore bounded in code rather than by care: `assert_prop_ref`
# is the single chokepoint every push goes through, and it raises BEFORE any subprocess is
# constructed, so a bad target never reaches the network even transiently.
PROP_REF_PREFIX = "prop/"

# Characters that turn a ref into something other than a plain branch name — refspec
# separators, globs, and the reflog/ancestry operators. None of them belong in a name this
# command generates, so their presence means the value did not come from where we think.
_REF_FORBIDDEN = frozenset(':+~^?*[]\\ \t\n')


class UnsafePushTarget(RuntimeError):
    """A push was attempted at something outside the `prop/*` namespace."""


def assert_prop_ref(ref: str) -> str:
    """Validate a push target. Raises :class:`UnsafePushTarget` before any git runs.

    Fails closed on everything that is not obviously a `prop/<something>` branch name.
    `main` and `origin/main` are the targets that matter, but the traversal case
    (`prop/../main`) is why a prefix check alone is not enough: it satisfies
    `startswith("prop/")` and still names the trunk.
    """
    if not isinstance(ref, str) or not ref:
        raise UnsafePushTarget(f"refusing to push: empty or non-string ref {ref!r}")
    if not ref.startswith(PROP_REF_PREFIX):
        raise UnsafePushTarget(
            f"refusing to push {ref!r}: `propose` may only push refs under "
            f"{PROP_REF_PREFIX!r}. This is enforced in code, not by convention — there is "
            f"no flag that widens it."
        )
    remainder = ref[len(PROP_REF_PREFIX):]
    if not remainder:
        raise UnsafePushTarget(f"refusing to push bare prefix {ref!r}")
    if ".." in ref or ref.endswith("/") or "//" in ref:
        raise UnsafePushTarget(
            f"refusing to push {ref!r}: path traversal or empty segment. A prefix check "
            f"alone would accept 'prop/../main', which names the trunk."
        )
    bad = sorted(set(ref) & _REF_FORBIDDEN)
    if bad:
        raise UnsafePushTarget(
            f"refusing to push {ref!r}: illegal character(s) {''.join(bad)!r} in a ref name"
        )
    return ref


# The two states a proposal file can be in. `propose` writes AWAITING; `implement` flips
# it to IMPLEMENTED on the prop branch only, so the trunk keeps saying AWAITING until a
# human merges. The status therefore answers "has this been done?" honestly from
# whichever branch you are reading.
STATUS_AWAITING = "AWAITING IMPLEMENTATION"
STATUS_IMPLEMENTED = "IMPLEMENTED — awaiting human merge"

# A proposal's blast radius, stated by the author and checked by the reviewer. Ordered
# least to most consequential; `implement` prints it back before it gates.
RISK_CLASSES = ("cosmetic", "content", "infrastructure", "operational")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class ProposalRefused(RuntimeError):
    """The firewall refused. Carries the rendered refusal for the caller to print."""

    def __init__(self, verdict: firewall.FirewallVerdict) -> None:
        super().__init__("proposal refused by the firewall")
        self.verdict = verdict


def slugify(title: str) -> str:
    return _SLUG_STRIP.sub("-", title.lower()).strip("-")[:60]


def next_number(proposals_dir: Path | None = None) -> int:
    """One higher than the highest PROP- on disk. Numbers are never reused."""
    directory = proposals_dir if proposals_dir is not None else PROPOSALS_DIR
    if not directory.exists():
        return 1
    highest = 0
    for path in directory.glob("PROP-*.md"):
        match = re.match(r"PROP-(\d+)", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


@dataclass
class Proposal:
    """Everything a proposal must state. No field is optional by accident."""

    title: str
    observation: str
    change: str
    affected_paths: list[str]
    risk_class: str
    test_plan: str
    evidence: list[str] = field(default_factory=list)
    number: int = 0
    slug: str = ""
    # Filled in by `write_proposal`; reported to the operator, never rendered into the
    # document (a file cannot truthfully describe the commit that carries it).
    commit_status: str = ""

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = slugify(self.title)
        if self.risk_class not in RISK_CLASSES:
            raise ValueError(
                f"risk class {self.risk_class!r} is not one of {', '.join(RISK_CLASSES)}"
            )

    @property
    def filename(self) -> str:
        return f"PROP-{self.number}-{self.slug}.md"

    @property
    def firewall_text(self) -> str:
        """Everything the class check reads. Deliberately includes the title and test
        plan — an intent stated only in the test plan is still the intent."""
        return "\n".join([self.title, self.observation, self.change, self.test_plan])


def render(proposal: Proposal, *, generated_at: datetime | None = None) -> str:
    """The proposal document. Stable shape so `implement` can append to it by anchor."""
    stamp = (generated_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    lines = [
        f"# PROP-{proposal.number} — {proposal.title}",
        "",
        f"_proposed {stamp}  |  risk class: **{proposal.risk_class}**  |  "
        f"status: **{STATUS_AWAITING}**_",
        "",
        "## Observation",
        "",
        proposal.observation.strip(),
        "",
        "### Evidence",
        "",
    ]
    if proposal.evidence:
        lines += [f"- `{e}`" for e in proposal.evidence]
    else:
        lines.append("- _(none cited)_")
    lines += [
        "",
        "## Proposed change",
        "",
        proposal.change.strip(),
        "",
        "## Affected files",
        "",
    ]
    lines += [f"- `{p}`" for p in proposal.affected_paths] or ["- _(none)_"]
    lines += [
        "",
        "## Risk class",
        "",
        f"**{proposal.risk_class}**",
        "",
        "## Test plan",
        "",
        proposal.test_plan.strip(),
        "",
        "## Firewall",
        "",
        "```",
        firewall.check(
            affected_paths=proposal.affected_paths, text=proposal.firewall_text
        ).render(),
        "```",
        "",
        "## Merge gate",
        "",
        "`implement` stops after pushing the branch. **Merge is human-only:** Daniel "
        "merges via pull request after Quant Lead review. No automated path to `main` "
        "exists in this pipeline.",
        "",
        "---",
        "",
        "<!-- IMPLEMENTATION REPORT ANCHOR -->",
        "",
    ]
    return "\n".join(lines)


def commit_proposal(path: Path, number: int, *, root: Path | None = None) -> str:
    """Commit the proposal where it was written. Returns a short status string.

    WHY AT PROPOSE TIME. Until 2026-08-15 the proposal was left untracked and `implement`
    was what first committed it — onto `prop/n`. That put the analysis record on the
    implementation branch only, with three consequences. Switching back to the trunk
    removed the file from the working tree; deleting the branch destroyed it (observed
    during the PROP-1 dogfood, where it had to be recovered from the remote by hand); and
    a proposal that was never implemented left no trace anywhere that the analysis had
    been done and set aside. A pipeline that claims to be auditable has to record what was
    considered, not only what was carried out.

    Failures here are reported, never raised: a proposal that is written but uncommitted
    is a worse outcome than one that is written and committed, but it is far better than
    losing the document because git was unhappy.
    """
    repo = root if root is not None else PROJECT_ROOT

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, text=True, shell=False,
        )

    added = git("add", "--", str(path))
    if added.returncode != 0:
        return f"NOT COMMITTED (git add failed: {added.stderr.strip()})"
    # Commit ONLY this path, so a dirty working tree is never swept in alongside it.
    # `-m` MUST precede the `--` separator: everything after `--` is a pathspec, so
    # putting the message there made git look for a file named after the commit body.
    committed = git(
        "commit", "--only",
        "-m", f"PROP-{number}: propose — {path.stem}\n\n"
              f"Analysis recorded at propose time, status {STATUS_AWAITING}. "
              f"Implementation, if any, happens on prop/{number} behind a human merge.",
        "--", str(path),
    )
    if committed.returncode != 0:
        detail = (committed.stderr or committed.stdout).strip().splitlines()
        return f"NOT COMMITTED ({detail[-1] if detail else 'unknown error'})"
    sha = git("rev-parse", "--short", "HEAD").stdout.strip()
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return f"committed {sha} on {branch}"


def push_prop_ref(
    ref: str,
    *,
    root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str:
    """Push ``ref`` to origin. THE GUARD RUNS FIRST, before any subprocess exists.

    That ordering is the point, and it is asserted as an observable rather than claimed:
    the test injects a recording runner, calls this with ``main``, and requires both that
    :class:`UnsafePushTarget` is raised and that the recorder captured **zero** git
    invocations. A guard that ran after the argv was assembled would still be a guard, but
    it would not be one you could prove had never reached the network.
    """
    assert_prop_ref(ref)  # <- first statement. Nothing above it may touch git.

    repo = root if root is not None else PROJECT_ROOT
    run = runner if runner is not None else _subprocess_runner
    pushed = run(["git", "push", "--set-upstream", "origin", ref], repo)
    if pushed.returncode != 0:
        detail = (pushed.stderr or pushed.stdout).strip().splitlines()
        return f"NOT PUSHED ({detail[-1] if detail else 'unknown error'})"
    return f"pushed origin/{ref}"


def _subprocess_runner(
    cmd: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd), cwd=str(cwd), capture_output=True, text=True, shell=False,
    )


def publish_proposal(
    path: Path,
    number: int,
    *,
    root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str:
    """Seed ``prop/{number}`` with the proposal and push it, then return to where we were.

    NO PULL REQUEST IS OPENED HERE. A proposal is not a request to merge anything — it is
    an observation with evidence, and most of them should be readable without ever
    entering a review queue. `implement` opens the PR once the gates pass, which is the
    first moment "please merge this" is a meaningful thing to say.

    Returning to the original branch matters: `propose` is an analysis command and must
    not leave the operator somewhere they did not ask to be.
    """
    repo = root if root is not None else PROJECT_ROOT
    run = runner if runner is not None else _subprocess_runner
    ref = f"{PROP_REF_PREFIX}{number}"
    assert_prop_ref(ref)

    # Commit WHERE WE ARE first — PROP-2's local durability, unchanged. The proposal has
    # to stay in the working tree: an earlier draft of this function checked out `prop/n`
    # to commit there and then returned, which made the file vanish from the operator's
    # tree and left `implement` unable to find it. That is the PROP-1 failure in a new
    # costume, and it is why the branch is created by POINTER here rather than by
    # checkout — no HEAD movement, nothing to restore, nothing to lose if it fails.
    committed = commit_proposal(path, number, root=repo)
    if committed.startswith("NOT COMMITTED"):
        return committed

    # `prop/n` is just a name for the commit we already made. Force is safe: it names a
    # ref this command owns, and the guard has already refused anything outside `prop/*`.
    pointed = run(["git", "branch", "--force", ref, "HEAD"], repo)
    if pointed.returncode != 0:
        detail = (pointed.stderr or pointed.stdout).strip().splitlines()
        return f"{committed}; NOT PUBLISHED ({detail[-1] if detail else 'branch failed'})"

    pushed = push_prop_ref(ref, root=repo, runner=run)
    return f"{committed}; {pushed}"


def write_proposal(
    proposal: Proposal,
    *,
    proposals_dir: Path | None = None,
    generated_at: datetime | None = None,
    commit: bool = True,
    root: Path | None = None,
) -> Path:
    """Gate, then write, then commit. Raises :class:`ProposalRefused` without writing.

    The firewall runs BEFORE the directory is created, so a refused proposal leaves no
    trace on disk at all — the same "nothing is written unless the gate passes" posture
    the snapshot writer takes.
    """
    verdict = firewall.check(
        affected_paths=proposal.affected_paths, text=proposal.firewall_text
    )
    if not verdict.allowed:
        raise ProposalRefused(verdict)

    for path in proposal.evidence:
        sources.assert_allowed(path)

    directory = proposals_dir if proposals_dir is not None else PROPOSALS_DIR
    if proposal.number == 0:
        proposal.number = next_number(directory)
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / proposal.filename
    out.write_text(render(proposal, generated_at=generated_at) + "\n", encoding="utf-8")
    proposal.commit_status = (
        publish_proposal(out, proposal.number, root=root) if commit
        else "not committed (--no-commit)"
    )
    return out


def find_proposal(number: int, proposals_dir: Path | None = None) -> Path:
    """The file for PROP-{number}, or a clear error naming what exists."""
    directory = proposals_dir if proposals_dir is not None else PROPOSALS_DIR
    matches = sorted(directory.glob(f"PROP-{number}-*.md")) if directory.exists() else []
    if not matches:
        available = (
            ", ".join(sorted(p.name for p in directory.glob("PROP-*.md")))
            if directory.exists() else "(no proposals directory)"
        )
        raise FileNotFoundError(
            f"no proposal numbered {number}. Available: {available or '(none)'}"
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"PROP-{number} is ambiguous: {', '.join(p.name for p in matches)}"
        )
    return matches[0]


__all__ = [
    "PROPOSALS_DIR",
    "RISK_CLASSES",
    "Proposal",
    "ProposalRefused",
    "slugify",
    "next_number",
    "render",
    "write_proposal",
    "find_proposal",
    "PROP_REF_PREFIX",
    "UnsafePushTarget",
    "assert_prop_ref",
    "push_prop_ref",
    "publish_proposal",
    "commit_proposal",
    "STATUS_AWAITING",
    "STATUS_IMPLEMENTED",
]
