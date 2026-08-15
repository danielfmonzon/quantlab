"""`propose` writes documents, `implement` writes branches, and neither writes `main`.

The two structural claims this file exists to prove:

* `propose` NEVER edits code — enforced by construction (the only path it writes is
  under its proposals directory) and by an allowlist on what it may even read.
* `implement` NEVER touches `main` — proven twice, because one proof is not enough for
  a claim this load-bearing. Behaviourally, by running the real thing against a real
  git repository and asserting `main`'s SHA is byte-identical afterwards. Structurally,
  by reading `implement.py`'s own source and asserting no merge verb appears in it.
  The behavioural test catches a bug; the source test catches a future feature.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantlab.improve import firewall
from quantlab.improve.implement import (
    BRANCH_PREFIX,
    PROTECTED_BRANCH,
    NotOnBranch,
    current_branch,
    implement,
)
from quantlab.improve.propose import (
    Proposal,
    next_number,
    render,
    slugify,
    write_proposal,
)
from quantlab.improve.sources import SourceViolation, assert_allowed

STAMP = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, shell=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repository with a committed file and a `main` branch."""
    root = tmp_path / "repo"
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "docs" / "proposals").mkdir(parents=True)
    (root / "frontend" / "src" / "copy.ts").write_text(
        "export const COPY = 'caught itself twice'\n", encoding="utf-8"
    )
    _run(["git", "init", "-b", PROTECTED_BRANCH], root)
    _run(["git", "config", "user.email", "test@example.com"], root)
    _run(["git", "config", "user.name", "test"], root)
    _run(["git", "add", "-A"], root)
    _run(["git", "commit", "-m", "initial"], root)
    return root


def _proposal(**over: object) -> Proposal:
    base: dict[str, object] = dict(
        title="Emit a completion signal on an all-TRACKING week",
        observation="The weekly is silent when every account tracks.",
        change="Log one INFO recording the week ending and the four verdicts.",
        affected_paths=["src/quantlab/reporting/weekly.py"],
        risk_class="infrastructure",
        test_plan="Assert one INFO is emitted on an all-TRACKING fixture week.",
    )
    base.update(over)
    return Proposal(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- propose


def test_propose_writes_the_document_with_every_required_section(tmp_path: Path) -> None:
    path = write_proposal(_proposal(), proposals_dir=tmp_path, generated_at=STAMP)
    text = path.read_text(encoding="utf-8")
    for heading in (
        "## Observation", "### Evidence", "## Proposed change", "## Affected files",
        "## Risk class", "## Test plan", "## Firewall", "## Merge gate",
    ):
        assert heading in text, f"missing {heading}"
    assert "FIREWALL PASS" in text
    assert "Daniel merges via pull request" in text


def test_propose_writes_nothing_outside_its_proposals_directory(tmp_path: Path) -> None:
    """The 'never edits code' claim, made concrete: exactly one file appears."""
    before = {p for p in tmp_path.rglob("*")}
    write_proposal(_proposal(), proposals_dir=tmp_path, generated_at=STAMP)
    after = {p for p in tmp_path.rglob("*")}
    created = after - before
    assert len(created) == 1
    assert created.pop().suffix == ".md"


def test_evidence_outside_the_allowed_read_set_is_rejected() -> None:
    """Source code is not readable evidence — an observation traces to an artifact."""
    with pytest.raises(SourceViolation) as caught:
        assert_allowed("src/quantlab/reporting/weekly.py")
    assert "outside the allowed read set" in str(caught.value)


@pytest.mark.parametrize(
    "allowed",
    ["reports/weekly", "reports/paper", "reports/alerts/alerts.jsonl", "docs/decisions.md"],
)
def test_allowed_evidence_paths_are_accepted(allowed: str) -> None:
    assert assert_allowed(allowed).exists()


def test_numbers_are_never_reused(tmp_path: Path) -> None:
    assert next_number(tmp_path) == 1
    (tmp_path / "PROP-1-a.md").write_text("x", encoding="utf-8")
    (tmp_path / "PROP-7-b.md").write_text("x", encoding="utf-8")
    assert next_number(tmp_path) == 8


def test_slugify_is_filesystem_safe() -> None:
    assert slugify("Story page: 'twice' -> three!") == "story-page-twice-three"


def test_render_is_deterministic() -> None:
    p = _proposal()
    p.number = 3
    assert render(p, generated_at=STAMP) == render(p, generated_at=STAMP)


# ------------------------------------------------------------------------- implement


def test_implement_never_touches_main(repo: Path) -> None:
    """The behavioural proof. `main` must be byte-identical before and after."""
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(
        title="Story page says twice",
        affected_paths=["frontend/src/copy.ts"],
        risk_class="content",
    )
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP)

    main_before = _run(["git", "rev-parse", PROTECTED_BRANCH], repo).stdout.strip()
    assert main_before

    # The change the AI partner made, sitting in the working tree.
    (repo / "frontend" / "src" / "copy.ts").write_text(
        "export const COPY = 'caught itself three times'\n", encoding="utf-8"
    )

    result = implement(
        proposal.number, root=repo, proposals_dir=proposals, push=False, now=STAMP,
        runner=lambda cmd, cwd: _run(list(cmd), cwd),
    )

    main_after = _run(["git", "rev-parse", PROTECTED_BRANCH], repo).stdout.strip()
    assert main_after == main_before, "implement moved main"

    assert result.committed
    assert result.branch == f"{BRANCH_PREFIX}{proposal.number}"
    assert current_branch(lambda cmd, cwd: _run(list(cmd), cwd), repo) != PROTECTED_BRANCH

    # The commit exists on the prop branch and NOT on main.
    on_main = _run(["git", "branch", "--contains", result.commit_sha], repo).stdout
    assert PROTECTED_BRANCH not in on_main.replace("*", "").split()


def test_implement_writes_the_report_into_the_proposal(repo: Path) -> None:
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP)
    (repo / "frontend" / "src" / "copy.ts").write_text("changed\n", encoding="utf-8")

    implement(proposal.number, root=repo, proposals_dir=proposals, push=False, now=STAMP,
              runner=lambda cmd, cwd: _run(list(cmd), cwd))

    text = path.read_text(encoding="utf-8")
    assert "## Implementation report" in text
    assert "### Diff stat" in text
    assert "### Gates" in text
    assert "STOPPED HERE" in text
    assert "Daniel merges via pull request" in text


def test_report_in_the_file_never_claims_it_was_not_committed(repo: Path) -> None:
    """The durable artifact must not state the opposite of what happened.

    Regression for the first dogfood run: `write_report` runs BEFORE the commit (the
    report is part of what gets committed), so `committed`/`pushed` were still False and
    were rendered into the proposal as `committed: **False**` on a run that had in fact
    committed and pushed. The file now reports only what is known at write time.
    """
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP)
    (repo / "frontend" / "src" / "copy.ts").write_text("changed\n", encoding="utf-8")

    result = implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                       now=STAMP, runner=lambda cmd, cwd: _run(list(cmd), cwd))
    assert result.committed, "precondition: this run should have committed"

    text = path.read_text(encoding="utf-8")
    assert "committed: **False**" not in text
    assert "pushed: **False**" not in text
    assert "commit and push: performed immediately after" in text
    # The console rendering, by contrast, is finalised and may state both.
    assert result.finalised
    assert "committed: **True**" in result.render()


def test_implement_refuses_a_diff_that_touches_a_firewall_path(repo: Path) -> None:
    """Defence in depth: the DOCUMENT said frontend, the DIFF says risk limits."""
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP)

    (repo / "config").mkdir()
    (repo / "config" / "risk.yaml").write_text("max_drawdown: 0.99\n", encoding="utf-8")

    result = implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                       now=STAMP, runner=lambda cmd, cwd: _run(list(cmd), cwd))

    assert result.aborted
    assert not result.committed
    assert not result.firewall_ok
    assert "firewall" in result.aborted.lower()


def test_implement_aborts_on_an_empty_diff(repo: Path) -> None:
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP)
    # Commit the proposal so the tree is clean and the diff is genuinely empty.
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-m", "proposal"], repo)

    result = implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                       now=STAMP, runner=lambda cmd, cwd: _run(list(cmd), cwd))
    assert "empty" in result.aborted


def test_branch_guard_refuses_when_not_on_the_prop_branch(repo: Path) -> None:
    """The guard itself, exercised directly."""
    from quantlab.improve.implement import _assert_on_prop_branch

    runner = lambda cmd, cwd: _run(list(cmd), cwd)  # noqa: E731
    with pytest.raises(NotOnBranch) as caught:
        _assert_on_prop_branch(runner, repo, 99)
    assert PROTECTED_BRANCH in str(caught.value)


def test_no_auto_merge_path_exists_in_the_source() -> None:
    """The structural proof: read implement.py and assert no merge verb is present.

    This catches the case the behavioural test cannot — someone later ADDING a merge,
    where the old test would still pass because it only asserts about the runs it makes.
    """
    from quantlab.improve import implement as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    # Strip the prose, which legitimately discusses merging at length.
    code = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )
    code = code.split('"""')[0] + '"""'.join(code.split('"""')[2:])

    forbidden = [
        '"merge"', "'merge'", '"rebase"', "'rebase'", '"cherry-pick"',
        f'"origin", "{PROTECTED_BRANCH}"', f'"{PROTECTED_BRANCH}"]',
        "--ff", "gh pr merge", '"pr", "merge"',
    ]
    hits = [f for f in forbidden if f in code]
    assert not hits, f"an automated merge path appeared in implement.py: {hits}"


def test_implement_and_propose_agree_on_the_firewall(repo: Path) -> None:
    """One firewall, two call sites — not two copies that can drift apart."""
    from quantlab.improve import implement as impl_mod
    from quantlab.improve import propose as prop_mod

    assert impl_mod.firewall is firewall
    assert prop_mod.firewall is firewall
