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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from quantlab.constants import PROJECT_ROOT
from quantlab.improve import firewall, sources

PROPOSALS_DIR = PROJECT_ROOT / "docs" / "proposals"

# The two states a proposal file can be in. `propose` writes AWAITING and commits it
# where it was run; `implement` flips it to IMPLEMENTED on the prop branch only, so the
# trunk keeps saying AWAITING until a human merges. The status therefore answers "has
# this been done?" honestly from whichever branch you are reading.
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
        commit_proposal(out, proposal.number, root=root) if commit
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
]
