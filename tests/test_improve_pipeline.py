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

import ast
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantlab.constants import PROJECT_ROOT
from quantlab.improve import firewall
from quantlab.improve.implement import (
    BRANCH_PREFIX,
    CONSOLE_SCRIPT_NAME,
    PROTECTED_BRANCH,
    SUPPORTED_INVOCATION,
    ConsoleScriptInvocation,
    NotOnBranch,
    assert_not_console_script,
    current_branch,
    implement,
    program_name,
)
from quantlab.improve.propose import (
    Proposal,
    ProposalNumberCollision,
    existing_prop_numbers,
    next_number,
    publish_proposal,
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
    path = write_proposal(_proposal(), proposals_dir=tmp_path, generated_at=STAMP, commit=False)
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
    write_proposal(_proposal(), proposals_dir=tmp_path, generated_at=STAMP, commit=False)
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
    """The allowlist decision is about LOCATION, not about what has been generated yet.

    This asserted `.exists()` until 2026-08-15, which passed on a developer machine with
    months of artifacts on disk and failed on CI, where `reports/*` is gitignored and a
    fresh clone therefore has none of it. The test was reading the developer's data, not
    the code's behaviour — so it could only ever have caught "you have not run the system
    yet", which is not a defect. What `assert_allowed` promises is that the path lies
    inside the permitted read set and resolves under the repo root; whether the artifact
    has been produced is the caller's problem, and `render_inventory` already reports
    absent sources as ABSENT rather than pretending they are there.
    """
    resolved = assert_allowed(allowed)
    assert resolved.is_absolute()
    assert resolved.is_relative_to(PROJECT_ROOT)


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
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)

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
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
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
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
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
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)

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
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
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
    # Strip PROSE only — comments and docstrings — and keep every other string literal,
    # because the thing being hunted (`_git(..., "merge", ...)`) IS a string literal.
    # The previous line-and-split approach removed only the module docstring, so the
    # sentence "there is no `gh pr merge` here" inside a FUNCTION docstring tripped the
    # test against code that contained no such call. A test that fires on its own
    # subject's documentation is the same false-positive failure the sanitizer's
    # `apca_api_header` pattern was narrowed to avoid (2026-07-26).
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    class _StripProse(ast.NodeTransformer):
        def visit_Constant(self, node: ast.Constant) -> ast.Constant:
            if id(node) in docstrings:
                return ast.Constant(value="")
            return node

    code = ast.unparse(_StripProse().visit(tree))

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


# ------------------------------------------------------- proposal lifecycle (PROP-2)


def test_propose_commits_the_proposal_where_it_was_run(repo: Path) -> None:
    """The analysis is recorded at propose time, not at implement time."""
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)

    assert "committed" in proposal.commit_status, proposal.commit_status
    tracked = _run(["git", "ls-files", "--", str(path)], repo).stdout.strip()
    assert tracked, "the proposal was not tracked after propose"
    # Committing the proposal must not sweep in an unrelated dirty working tree.
    assert _run(["git", "status", "--porcelain"], repo).stdout.strip() == ""


def test_a_committed_proposal_survives_a_branch_switch(repo: Path) -> None:
    """The PROP-1 failure, as a test: the record must not live only on prop/n."""
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)

    _run(["git", "checkout", "-b", "somewhere-else"], repo)
    _run(["git", "checkout", PROTECTED_BRANCH], repo)
    assert path.is_file(), "the proposal vanished across a branch switch"


def test_no_commit_leaves_the_proposal_untracked(repo: Path) -> None:
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP,
                          root=repo, commit=False)
    assert "--no-commit" in proposal.commit_status
    assert not _run(["git", "ls-files", "--", str(path)], repo).stdout.strip()


def test_status_is_awaiting_on_the_trunk_and_implemented_on_the_branch(repo: Path) -> None:
    """The same file answers "has this been done?" per branch, and both are true."""
    from quantlab.improve.propose import STATUS_AWAITING, STATUS_IMPLEMENTED

    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
    assert STATUS_AWAITING in path.read_text(encoding="utf-8")

    (repo / "frontend" / "src" / "copy.ts").write_text("changed\n", encoding="utf-8")
    implement(proposal.number, root=repo, proposals_dir=proposals, push=False, now=STAMP,
              runner=lambda cmd, cwd: _run(list(cmd), cwd))

    # On the prop branch: implemented.
    assert STATUS_IMPLEMENTED in path.read_text(encoding="utf-8")
    # On the trunk: still awaiting, because nobody has merged it.
    on_main = _run(
        ["git", "show", f"{PROTECTED_BRANCH}:docs/proposals/{path.name}"], repo
    ).stdout
    assert STATUS_AWAITING in on_main
    assert STATUS_IMPLEMENTED not in on_main


# ------------------------------------------- bounded push guard (PROP-3)


class RecordingRunner:
    """Captures every git invocation and executes NONE of them.

    The point of this double is negative: it lets a test assert that a code path never
    reached git at all, which is stronger than asserting it reached git and was rejected.

    ``stdout`` is what every recorded call returns, for the cases that read from git
    rather than write to it (PROP-7's ref enumeration). It defaults to empty, so the
    PROP-3 guard tests below are unaffected.
    """

    def __init__(self, stdout: str = "") -> None:
        self.calls: list[list[str]] = []
        self._stdout = stdout

    def __call__(self, cmd, cwd):  # noqa: ANN001, ANN204
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(list(cmd), 0, stdout=self._stdout, stderr="")


@pytest.mark.parametrize(
    "ref",
    [
        "main",
        "origin/main",
        "",
        "prop/",
        "prop/../main",
        "refs/heads/main",
        "prop/3:main",
        "prop/3 --force",
        "propose/3",
    ],
)
def test_unsafe_push_target_raises_before_any_git_invocation(ref: str) -> None:
    """THE guard test. Not "git refused it" — git was never asked.

    A guard that ran after the argv was assembled would still reject the push, but it
    could not prove the target never reached the network. Asserting zero recorded
    invocations makes "before any git call" an observable property rather than a claim
    about statement ordering that a later refactor could silently invert.
    """
    from quantlab.improve.propose import UnsafePushTarget, push_prop_ref

    recorder = RecordingRunner()
    with pytest.raises(UnsafePushTarget):
        push_prop_ref(ref, root=Path("."), runner=recorder)

    assert recorder.calls == [], (
        f"git was invoked {len(recorder.calls)} time(s) before the guard rejected {ref!r}: "
        f"{recorder.calls}"
    )


@pytest.mark.parametrize("ref", ["prop/1", "prop/42", "prop/3-retry"])
def test_prop_refs_are_accepted_and_pushed(ref: str) -> None:
    from quantlab.improve.propose import push_prop_ref

    recorder = RecordingRunner()
    push_prop_ref(ref, root=Path("."), runner=recorder)
    assert recorder.calls == [["git", "push", "--set-upstream", "origin", ref]]


def test_assert_prop_ref_returns_the_ref_unchanged() -> None:
    from quantlab.improve.propose import assert_prop_ref

    assert assert_prop_ref("prop/7") == "prop/7"


def test_propose_pushes_only_its_own_ref_and_opens_no_pull_request(repo: Path) -> None:
    """`propose` publishes; it does not queue anything for review."""
    from quantlab.improve.propose import publish_proposal

    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    path = write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP,
                          root=repo, commit=False)

    recorder = RecordingRunner()
    publish_proposal(path, 9, root=repo, runner=recorder)

    pushes = [c for c in recorder.calls if "push" in c]
    assert pushes == [["git", "push", "--set-upstream", "origin", "prop/9"]]
    assert not any(c[:1] == ["gh"] for c in recorder.calls), (
        "propose opened a pull request; a proposal is not a request to merge"
    )


def test_implement_opens_no_pull_request_when_a_gate_fails(repo: Path) -> None:
    """A red branch stays a branch — visible as evidence, not queued for review."""
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
    (repo / "frontend" / "src" / "copy.ts").write_text("changed\n", encoding="utf-8")

    result = implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                       now=STAMP, runner=lambda cmd, cwd: _run(list(cmd), cwd))
    assert not result.pushed
    assert result.pr_url == ""
    assert "no PR opened" in result.pr_detail


# --------------------------------------------------------------------------- #
# Global numbering, and a ref this command did not create (PROP-7)            #
# --------------------------------------------------------------------------- #

def test_a_taken_number_raises_before_any_git_command_runs(repo: Path) -> None:
    """The 2026-08-30 failure, refused: prop/5 exists, so 5 is not handed out again.

    `git branch --force prop/5 HEAD` destroyed the pointer to PROP-5's implemented work,
    which survived only because it had already been pushed. Nothing may run before this
    is refused — a commit made and then abandoned is still a commit on the operator's
    branch.
    """
    runner = RecordingRunner()
    path = repo / "docs" / "proposals" / "PROP-5-x.md"
    path.write_text("# PROP-5\n", encoding="utf-8")

    with pytest.raises(ProposalNumberCollision) as excinfo:
        publish_proposal(path, 5, root=repo, runner=runner, taken_numbers={5})

    assert excinfo.value.number == 5
    assert runner.calls == []          # nothing committed, nothing pointed, nothing pushed


def test_a_free_number_creates_the_branch_without_a_force_verb(repo: Path) -> None:
    """`git branch` and not `git branch --force`: the ref is created, never moved.

    Belt and braces behind the assertion above. If the check is ever defeated, the worst
    a defeated check can do is fail loudly rather than overwrite another proposal's only
    pointer to its work.
    """
    runner = RecordingRunner()
    path = repo / "docs" / "proposals" / "PROP-9-x.md"
    path.write_text("# PROP-9\n", encoding="utf-8")

    publish_proposal(path, 9, root=repo, runner=runner, taken_numbers={5, 6})

    branch_calls = [c for c in runner.calls if c[:2] == ["git", "branch"]]
    assert branch_calls, f"no branch command issued; recorded {runner.calls}"
    for call in branch_calls:
        assert "--force" not in call
        assert "-f" not in call
    assert ["git", "branch", "prop/9", "HEAD"] in branch_calls


def test_numbering_counts_refs_the_working_tree_cannot_see(tmp_path: Path) -> None:
    """The exact shape of the collision: PROP-1 on disk, prop/5 on a branch -> next is 6.

    Run from `main`, `docs/proposals` held PROP-1..4 while PROP-5 sat on its own branch,
    so numbering from the directory alone returned 5 for a number already in use.
    """
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    (proposals / "PROP-1-a.md").write_text("x", encoding="utf-8")

    assert next_number(proposals) == 2                 # disk alone, unchanged
    assert next_number(proposals, {5}) == 6            # a ref this branch cannot see
    assert next_number(proposals, {5, 6, 7}) == 8


def test_numbering_is_unchanged_when_no_prop_refs_exist(tmp_path: Path) -> None:
    """A repository with no prop refs numbers exactly as it did before PROP-7."""
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    for n in (1, 2, 3):
        (proposals / f"PROP-{n}-a.md").write_text("x", encoding="utf-8")
    assert next_number(proposals, set()) == 4
    assert next_number(proposals, None) == 4
    assert next_number(proposals) == 4


def test_existing_prop_numbers_reads_local_and_remote_refs(repo: Path) -> None:
    """Both namespaces count: a number claimed on the remote is claimed."""
    runner = RecordingRunner(
        "refs/heads/prop/5\n"
        "refs/heads/prop/6\n"
        "refs/remotes/origin/prop/11\n"
        "refs/remotes/origin/main\n"
        "refs/heads/docs/something\n"
    )
    assert existing_prop_numbers(root=repo, runner=runner) == {5, 6, 11}


def test_existing_prop_numbers_is_empty_when_git_fails(repo: Path) -> None:
    """A git that cannot answer must not block writing a proposal."""
    def failing(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(cmd), 128, "", "not a git repository")

    assert existing_prop_numbers(root=repo, runner=failing) == set()


# ------------------------------------------- the gates cannot uninstall us (PROP-12)
#
# On 2026-08-31 `implement` was invoked as `.venv/Scripts/quantlab.exe implement 11` and
# every gate reported FAIL with "The process cannot access the file because it is being
# used by another process" (commit 256d3b9). `uv run` had tried to reinstall the editable
# package -- replacing the very console script that was running the gates. The gates never
# executed, over a diff that was green when re-run correctly.

_WINDOWS_CONSOLE_ARGV = "C:\\Users\\danmo\\Dev\\quantlab\\.venv\\Scripts\\quantlab.exe"


def test_every_uv_gate_passes_no_sync(repo: Path) -> None:
    """The argv that WOULD have been issued, asserted without issuing it.

    A recording double executes nothing, so this is a claim about the command line rather
    than about whether some environment happened to tolerate it.
    """
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
    (repo / "frontend" / "src" / "copy.ts").write_text("changed\n", encoding="utf-8")

    real = lambda cmd, cwd: _run(list(cmd), cwd)  # noqa: E731
    seen: list[list[str]] = []

    def recording(cmd, cwd):  # noqa: ANN001, ANN202
        seen.append(list(cmd))
        if list(cmd)[:1] == ["git"]:
            return real(cmd, cwd)          # git must really run; the gates must not
        return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

    implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
              now=STAMP, runner=recording)

    uv_calls = [c for c in seen if c[:1] == ["uv"]]
    assert uv_calls, "precondition: the gates should have been invoked"
    for call in uv_calls:
        assert call[:3] == ["uv", "run", "--no-sync"], f"gate would resync: {call}"


@pytest.mark.parametrize(
    "argv0",
    [
        _WINDOWS_CONSOLE_ARGV,          # the exact invocation that broke 256d3b9
        "quantlab.exe",
        "quantlab",
        "quantlab.cmd",
        "/home/runner/work/quantlab/.venv/bin/quantlab",
    ],
)
def test_the_console_script_invocation_raises_before_any_git_command(
    repo: Path, argv0: str
) -> None:
    """Not "the gates failed and we noticed" -- git was never asked to do anything.

    The Windows-style argv is in this list deliberately, and it is the one that matters on
    the Linux runner: `Path(...).name` would return it whole there, so a host-dependent
    split makes CI unable to verify the regression it exists for (2026-08-15, 2026-08-31).
    """
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
    (repo / "frontend" / "src" / "copy.ts").write_text("changed\n", encoding="utf-8")

    recorder = RecordingRunner()
    with pytest.raises(ConsoleScriptInvocation) as raised:
        implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                  now=STAMP, runner=recorder, argv0=argv0)

    assert recorder.calls == [], "the guard ran after git had already been reached"
    assert SUPPORTED_INVOCATION in str(raised.value)
    assert CONSOLE_SCRIPT_NAME in str(raised.value)
    # And the branch was never created, so a refusal costs nothing to undo.
    assert current_branch(lambda cmd, cwd: _run(list(cmd), cwd), repo) == PROTECTED_BRANCH


@pytest.mark.parametrize(
    "argv0",
    ["/usr/bin/python3", "C:/x/.venv/Scripts/python.exe", "python", "pytest",
     "C:\\x\\src\\quantlab\\cli.py"],
)
def test_an_ordinary_interpreter_invocation_is_allowed(argv0: str) -> None:
    """The guard must not refuse the invocation it is telling people to use."""
    assert_not_console_script(argv0)          # does not raise


def test_program_name_splits_on_both_separators() -> None:
    """The normalisation itself, since its verdict must not depend on the host."""
    assert program_name(_WINDOWS_CONSOLE_ARGV) == "quantlab"
    assert program_name("/home/x/bin/quantlab") == "quantlab"
    assert program_name("QUANTLAB.EXE") == "quantlab"
    assert program_name("quantlabber.exe") == "quantlabber"     # no prefix matching


def test_the_report_stat_covers_the_whole_series_not_the_last_commit(
    repo: Path,
) -> None:
    """PROP-11's surviving report said "1 file changed" for a change of six.

    A branch whose first commit touched a file the second does not touch has to have BOTH
    files in its stat, which is exactly what the staged-only diff cannot show.
    """
    proposals = repo / "docs" / "proposals"
    proposal = _proposal(affected_paths=["frontend/src/copy.ts"], risk_class="content")
    write_proposal(proposal, proposals_dir=proposals, generated_at=STAMP, root=repo)
    real = lambda cmd, cwd: _run(list(cmd), cwd)  # noqa: E731

    # First run: commits `first.txt` on prop/{n}.
    (repo / "first.txt").write_text("one\n", encoding="utf-8")
    first = implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                      now=STAMP, runner=real)
    assert first.committed, "precondition: the first run should have committed"

    # Second run on the same branch: touches only `second.txt`.
    (repo / "second.txt").write_text("two\n", encoding="utf-8")
    second = implement(proposal.number, root=repo, proposals_dir=proposals, push=False,
                       now=STAMP, runner=real)

    assert second.committed
    assert "second.txt" in second.diffstat
    assert "first.txt" in second.diffstat, (
        "the stat covers only this run's commit and understates the branch"
    )
    assert second.diffstat_range == f"{PROTECTED_BRANCH}..{BRANCH_PREFIX}{proposal.number}"
    # And the report says what it is showing, so the number cannot be misread again.
    text = (proposals / proposal.filename).read_text(encoding="utf-8")
    assert f"`{PROTECTED_BRANCH}..{BRANCH_PREFIX}{proposal.number}`" in text
    assert "the whole series" in text
