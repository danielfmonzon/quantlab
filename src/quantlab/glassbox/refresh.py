"""The automated Glass Box refresh: snapshot -> build -> gate -> deploy, fail-closed.

WHY THIS EXISTS. The deploy ritual in ``frontend/README.md`` is four commands across two
directories, and it was run by hand. The result was predictable: the published site sat at
its 2026-07-26 snapshot for **fifteen days** while the trading record moved underneath it,
and the completeness gate's own 14-day freshness limit had been breached for a day before
anyone noticed. A transparency site that lags its subject by two weeks is making a weaker
claim than it appears to. So the ritual is automated and scheduled.

FAIL-CLOSED. Each step runs only if every earlier step succeeded, and the chain reports
where it stopped. Nothing is deployed unless the gate that scans the published bytes has
already passed on those exact bytes.

DOCTRINE AMENDMENT (Quant Lead ruling, 2026-08-10; see docs/decisions.md). The pre-existing
rule was that a human reads the sanitization report before any deploy. That rule is
preserved for the case that matters and relaxed only where the machine's judgement is
total:

* deploy proceeds automatically **only** on gate PASS with **zero forbidden matches AND
  zero redactions** -- nothing found, and nothing that had to be scrubbed;
* **any** redaction aborts before deploy and raises a WARNING for human pre-review, even
  though the snapshot writer has already scrubbed it. A redaction means the capture
  contained something that should not be published. The scrub worked, but the reason it was
  needed is exactly what a human should see before those bytes go out;
* every run emails the full sanitization report, deployed or not -- INFO when deployed,
  WARNING on any abort. A gate whose output is only read after a failure trains its
  operator to ignore it, so the report arrives every week regardless.

The asymmetry is deliberate: automation is allowed to publish a clean build, and is never
allowed to publish one that needed cleaning.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quantlab.constants import PROJECT_ROOT
from quantlab.glassbox.completeness import DEFAULT_MAX_AGE_DAYS
from quantlab.logging_setup import get_logger
from quantlab.repo_state import RepoState, check_repo_state
from quantlab.reporting.alerts import Alert, DeliveryResult, dispatch

log = get_logger("quantlab.glassbox.refresh")

# The Netlify project the public site lives on. PINNED for the same reason
# frontend/README.md pins it on the command line: `npm run build:public` recreates
# `frontend/.netlify/`, which drops the site link, and an unlinked `netlify deploy` opens an
# interactive "Link this directory?" prompt. Inside an unattended chain that is worse than
# an error -- it blocks forever, or exits having deployed nothing while looking like it ran.
NETLIFY_SITE_ID = "be63f48c-4949-4603-b8dd-a6ccfdd996e7"
NETLIFY_SITE_NAME = "monzonautomation-glassbox"
CANONICAL_URL = "https://glassbox.danielmonzonautomation.com"

FRONTEND_DIR = PROJECT_ROOT / "frontend"
SNAPSHOT_OUT = FRONTEND_DIR / "public" / "snapshot"
DIST_DIR = FRONTEND_DIR / "dist"

STEP_SNAPSHOT = "snapshot"
STEP_BUILD = "build"
STEP_VERIFY = "verify-dist"
STEP_DEPLOY = "deploy"
# Runs ONLY after deploy has passed. It records what was published; it cannot publish,
# and it cannot un-publish (see record_snapshot).
STEP_RECORD = "record-snapshot"
STEP_ORDER = (STEP_SNAPSHOT, STEP_BUILD, STEP_VERIFY, STEP_DEPLOY, STEP_RECORD)

# The branch the published captures are recorded on. Generated from the date, never
# taken from input, so there is no value a caller could supply that names something
# else -- least of all the trunk.
SNAPSHOT_BRANCH_PREFIX = "snapshot/deploy-"
PROTECTED_BRANCH = "main"
SNAPSHOT_PATH = "frontend/public/snapshot"


class SnapshotBranchExists(RuntimeError):
    """The day's branch is already there. Raised BEFORE any git command runs."""

    def __init__(self, branch: str) -> None:
        super().__init__(
            f"{branch} already exists. The refresh records each publish once; a second "
            f"run on the same day would have to move a reference it did not create, "
            f"and this step never does that."
        )
        self.branch = branch


def build_snapshot_branch(day: date) -> str:
    """The branch name for ``day``'s publish. Pure, and the only source of the name."""
    return f"{SNAPSHOT_BRANCH_PREFIX}{day:%Y%m%d}"

# Netlify prints several URLs; this is the production one ("Website URL" on a --prod
# deploy). Captured so the chain can report where the bytes actually landed rather than
# assuming the canonical host resolved.
_DEPLOY_URL_PATTERNS = (
    re.compile(r"^\s*Website URL:\s*(\S+)", re.MULTILINE),
    re.compile(r"^\s*Unique deploy URL:\s*(\S+)", re.MULTILINE),
    re.compile(r"https://\S+\.netlify\.app\b"),
)

Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
AlertFn = Callable[[Alert], list[DeliveryResult]]


class StepOutcome(BaseModel):
    """One link in the chain: what ran, whether it passed, and why not."""

    name: str
    ran: bool = False
    ok: bool = False
    detail: str = ""
    # Populated for subprocess steps so a failure can be diagnosed from the report alone.
    argv: list[str] = []
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""

    @property
    def status(self) -> str:
        if not self.ran:
            return "SKIPPED"
        return "PASS" if self.ok else "FAIL"


class RefreshResult(BaseModel):
    started_at: datetime
    dry_run: bool = False
    # True when this run may publish without a human reading the report first. Only an
    # automated run treats an UNCHECKED env-secret gate as an abort; see the deploy
    # decision for why the two modes differ.
    automated: bool = True
    steps: list[StepOutcome] = []
    # The snapshot writer's report, then the published-bytes gate's report. Both are
    # rendered into the email; both feed the deploy decision.
    snapshot_report_text: str = ""
    verify_report_text: str = ""
    redaction_count: int = 0
    redactable_findings: list[str] = []
    forbidden_matches: list[str] = []
    # Whether each half of the secret search actually ran. A missing or unreadable `.env`
    # is not an error inside `load_env_secret_prefixes` — it returns an empty prefix set
    # with a note and the surrounding gate still PASSES. That is tolerable when a human
    # is reading the report and can see the note; it is not tolerable when the chain
    # deploys on its own. See the deploy decision.
    snapshot_env_checked: bool = True
    dist_env_checked: bool = True
    env_notes: list[str] = []

    @property
    def env_checked(self) -> bool:
        return self.snapshot_env_checked and self.dist_env_checked
    deployed: bool = False
    deploy_url: str | None = None
    aborted_at: str | None = None
    abort_reason: str | None = None
    # Where this publish was recorded, and the PR awaiting a human merge (PROP-9). Both
    # None when the recording step did not run or did not get that far. Deliberately NOT
    # part of ``ok``: the publish either happened or it did not, and how well it was
    # written down afterwards cannot change that answer.
    snapshot_branch: str | None = None
    snapshot_pr_url: str | None = None
    snapshot_record_note: str | None = None
    # Git provenance of the checkout that produced these bytes. Report-only: a dirty tree
    # warns and the chain proceeds (see repo_state for why blocking would be the wrong
    # trade), but the warning travels with the report so the claim is never silent.
    repo: RepoState | None = None

    @property
    def ok(self) -> bool:
        """True when the chain completed its intent: deployed, or dry-run gates passed."""
        return self.aborted_at is None

    def step(self, name: str) -> StepOutcome:
        for s in self.steps:
            if s.name == name:
                return s
        return StepOutcome(name=name)

    def render(self) -> str:
        lines = [
            "=" * 72,
            "GLASS BOX REFRESH — CHAIN REPORT",
            "=" * 72,
            f"started    : {self.started_at.isoformat()}",
            f"mode       : {'DRY RUN (stops before deploy)' if self.dry_run else 'LIVE'}",
            f"site       : {NETLIFY_SITE_NAME} ({NETLIFY_SITE_ID})",
            "",
            "CHAIN (each step runs only if every earlier step passed)",
            "-" * 72,
        ]
        for name in STEP_ORDER:
            s = self.step(name)
            lines.append(f"  {name:<12} {s.status:<8} {s.detail}")
        lines.append("")
        if self.repo is not None:
            lines.append("PROVENANCE")
            lines.append("-" * 72)
            lines.extend(self.repo.render())
            lines.append("")
        lines.append("DEPLOY DECISION")
        lines.append("-" * 72)
        lines.append(f"  forbidden matches : {len(self.forbidden_matches)} "
                     f"{'(must be 0)' if self.forbidden_matches else 'ok'}")
        lines.append(f"  redactions        : {self.redaction_count} "
                     f"{'(must be 0 to auto-deploy)' if self.redaction_count else 'ok'}")
        lines.append(f"  redactable found  : {len(self.redactable_findings)} "
                     f"{'(must be 0 to auto-deploy)' if self.redactable_findings else 'ok'}")
        # Stated on every report, not only when it fails: "the check ran" is a claim the
        # reader should be able to confirm rather than assume from the absence of a note.
        if self.env_checked:
            env_status = "ran"
        elif self.automated and not self.dry_run:
            env_status = "NOT CHECKED (must have run to auto-deploy)"
        else:
            env_status = "NOT CHECKED (note only — no automated deploy in this mode)"
        lines.append(f"  env-secret check  : {env_status}")
        for note in self.env_notes:
            lines.append(f"      {note}")
        for finding in self.redactable_findings:
            lines.append(f"      {finding}")
        if self.deployed:
            lines.append(f"  DEPLOYED -> {self.deploy_url or CANONICAL_URL}")
            if self.snapshot_branch:
                lines.append(f"  RECORDED -> {self.snapshot_branch}"
                             + (f"  (PR: {self.snapshot_pr_url})"
                                if self.snapshot_pr_url else ""))
                lines.append("  ^ one merge click closes the loop; the deploy is "
                             "already live either way")
            elif self.snapshot_record_note:
                lines.append(f"  NOT RECORDED — {self.snapshot_record_note}")
                lines.append("  ^ the publish SUCCEEDED; only the record of it did "
                             "not. Commit the captures by hand.")
        elif self.aborted_at:
            lines.append(f"  NOT DEPLOYED — aborted at '{self.aborted_at}': "
                         f"{self.abort_reason}")
        else:
            lines.append("  NOT DEPLOYED — dry run stopped before the deploy step")
        lines.append("")
        if self.snapshot_report_text:
            lines.append("SNAPSHOT SANITIZATION REPORT")
            lines.append("-" * 72)
            lines.append(self.snapshot_report_text)
            lines.append("")
        if self.verify_report_text:
            lines.append("PUBLISHED-BYTES GATE (verify-dist)")
            lines.append("-" * 72)
            lines.append(self.verify_report_text)
            lines.append("")
        verdict = (
            "DEPLOYED" if self.deployed
            else "DRY RUN — gates passed, deploy withheld" if self.ok
            else f"ABORTED at '{self.aborted_at}'"
        )
        lines.append("=" * 72)
        lines.append(verdict)
        lines.append("=" * 72)
        return "\n".join(lines)


def build_deploy_command() -> list[str]:
    """The ``netlify deploy`` argv (pure; nothing is executed).

    ``--dir=dist`` is relative to ``frontend/`` (the step's cwd), matching the documented
    ritual exactly so the automated path and the manual one deploy identical bytes.
    """
    return [
        "npx", "netlify", "deploy", "--prod", "--dir=dist",
        f"--site={NETLIFY_SITE_ID}",
    ]


def build_build_command() -> list[str]:
    """The public-build argv (pure). ``--mode public`` is set inside the npm script."""
    return ["npm", "run", "build:public"]


def _default_runner(cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` in ``cwd``, capturing output. Never uses a shell.

    The program name is resolved through ``shutil.which`` first because on Windows ``npm``
    and ``npx`` are ``.cmd`` shims: ``CreateProcess`` cannot execute them by bare name, so
    ``shell=False`` raises ``FileNotFoundError`` even though the tool is on PATH. Resolving
    explicitly keeps ``shell=False`` — the argv stays exactly the pinned list, with no shell
    to reinterpret any of it — while still finding the real executable.
    """
    argv = list(cmd)
    resolved = shutil.which(argv[0])
    if resolved:
        argv[0] = resolved
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, shell=False
    )


GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def _default_git_runner(
    cmd: Sequence[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a git/gh command, optionally with extra environment.

    Separate from ``_default_runner`` because this one needs ``GIT_INDEX_FILE``: the
    recording step builds its commit through a TEMPORARY index so it never stages
    anything in the operator's real index, never moves HEAD, and never disturbs the
    working tree of an unattended trading machine mid-chain.
    """
    argv = list(cmd)
    resolved = shutil.which(argv[0])
    if resolved:
        argv[0] = resolved
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, shell=False, env=merged,
    )


def record_snapshot(
    result: RefreshResult,
    *,
    root: Path,
    day: date,
    runner: GitRunner | None = None,
) -> StepOutcome:
    """Record the captures that were just published, on a branch, behind a human merge.

    ONLY REACHED AFTER A SUCCESSFUL DEPLOY. The bytes are already live when this runs,
    which fixes what this step is allowed to do to the chain's verdict: nothing. A
    failure here cannot retroactively fail a publish that succeeded — saying the deploy
    failed would simply be false — so it downgrades the run to a warning and leaves
    every earlier step reading exactly as it did.

    NEVER TOUCHES THE TRUNK, structurally rather than by care:

    * the branch name is GENERATED from the date (``build_snapshot_branch``), so no
      input reaches it;
    * its absence is asserted before anything is written, and the assertion raises with
      no git command issued;
    * the branch is created with ``git branch`` and no force argument, so even a
      defeated assertion cannot move a reference;
    * the commit is built through a temporary index and ``commit-tree``, so HEAD, the
      real index and the working tree are all untouched;
    * the push names the generated branch explicitly and is refused outright if that
      name is the protected branch.
    """
    run = runner if runner is not None else _default_git_runner
    step = StepOutcome(name=STEP_RECORD, ran=True)
    branch = build_snapshot_branch(day)

    if branch == PROTECTED_BRANCH or not branch.startswith(SNAPSHOT_BRANCH_PREFIX):
        raise SnapshotBranchExists(branch)

    # ASSERT BEFORE CREATE. Both namespaces: a branch pushed by an earlier run exists
    # remotely even after the local one is pruned.
    local = run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], root)
    remote = run(["git", "ls-remote", "--heads", "origin", branch], root)
    if local.returncode == 0 or (remote.returncode == 0 and (remote.stdout or "").strip()):
        raise SnapshotBranchExists(branch)

    with tempfile.TemporaryDirectory() as tmp:
        index = str(Path(tmp) / "index")
        env = {"GIT_INDEX_FILE": index}
        for argv in (
            ["git", "read-tree", "HEAD"],
            ["git", "add", "--all", "--", SNAPSHOT_PATH],
        ):
            done = run(argv, root, env)
            if done.returncode != 0:
                step.detail = f"{' '.join(argv[:3])} failed: {_tail(done)}"
                return step
        tree = run(["git", "write-tree"], root, env)
        if tree.returncode != 0:
            step.detail = f"git write-tree failed: {_tail(tree)}"
            return step
        tree_sha = (tree.stdout or "").strip()

    message = (
        f"snapshot: captures from the {day:%Y-%m-%d} refresh\n\n"
        f"Published to {result.deploy_url or CANONICAL_URL} by the automated chain. "
        f"Recorded so main can answer what the site is serving; the site itself is "
        f"deployed from frontend/dist by Netlify, not from git.\n"
    )
    commit = run(["git", "commit-tree", tree_sha, "-p", "HEAD", "-m", message], root)
    if commit.returncode != 0:
        step.detail = f"git commit-tree failed: {_tail(commit)}"
        return step
    commit_sha = (commit.stdout or "").strip()

    made = run(["git", "branch", branch, commit_sha], root)   # no --force, ever
    if made.returncode != 0:
        step.detail = f"could not create {branch}: {_tail(made)}"
        return step

    pushed = run(["git", "push", "--set-upstream", "origin", branch], root)
    if pushed.returncode != 0:
        step.detail = f"branch {branch} created but NOT pushed: {_tail(pushed)}"
        return step

    opened = run([
        "gh", "pr", "create", "--base", PROTECTED_BRANCH, "--head", branch,
        "--title", f"snapshot: captures from the {day:%Y-%m-%d} refresh",
        "--body", message,
    ], root)
    if opened.returncode != 0:
        step.detail = f"branch {branch} pushed but no PR opened: {_tail(opened)}"
        return step

    step.ok = True
    result.snapshot_branch = branch
    result.snapshot_pr_url = (opened.stdout or "").strip().splitlines()[-1] if opened.stdout else ""
    step.detail = f"recorded on {branch}; PR opened for human merge"
    return step


def _tail(proc: subprocess.CompletedProcess[str]) -> str:
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return detail[-1] if detail else "unknown error"


def extract_deploy_url(stdout: str) -> str | None:
    """The production URL Netlify reported, or None when its output did not name one."""
    for pattern in _DEPLOY_URL_PATTERNS:
        match = pattern.search(stdout)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return None


def relativize_paths(text: str, root: Path = PROJECT_ROOT) -> str:
    """Rewrite absolute paths under ``root`` as repo-relative ones.

    Applied to the chain report before it becomes an alert body, and it is load-bearing
    rather than cosmetic. Alerts are PUBLISHED: ``glassbox.app`` puts an alert's ``body``
    verbatim into ``/api/timeline`` as the event detail. The gate reports embedded here name
    the directory they scanned (``verify_dist`` renders ``directory : <abs path>``), so an
    unmodified report carries the operator's home directory into the published snapshot.

    The sanitizer already catches that and scrubs it to ``<path>`` — but under the amended
    doctrine a redaction ABORTS the deploy, so the first automated run would have poisoned
    every subsequent one: run N's alert becomes run N+1's redaction, and the chain could
    never deploy again. Observed exactly that way on the first live run (2026-08-10,
    ``windows_user_path x1 in api-timeline.json``).

    Both separator forms are handled because the report mixes them: pathlib renders native
    backslashes on Windows while ``as_posix`` and URLs use forward slashes.
    """
    root_str = str(root)
    return text.replace(root_str, ".").replace(root_str.replace("\\", "/"), ".")


def _alert(result: RefreshResult, alert_fn: AlertFn) -> None:
    """Email the full chain report. INFO when deployed, WARNING on any abort.

    The body is the whole report, not a summary: the point of mailing it every week is that
    the operator reads a real gate output rather than a green tick.
    """
    if result.deployed and result.snapshot_record_note:
        # Published, but the record of it did not land. WARNING, because the operator
        # has one thing to do by hand -- and the report still says DEPLOYED, because
        # it was.
        level, title = (
            "WARNING",
            "glass box deployed, but the snapshot was NOT recorded",
        )
    elif result.deployed:
        level, title = "INFO", "glass box refreshed and deployed"
    elif result.ok:
        level, title = "INFO", "glass box refresh dry run — gates passed, not deployed"
    else:
        level = "WARNING"
        title = f"glass box refresh ABORTED at '{result.aborted_at}' — human review needed"
    alert_fn(Alert(level=level, title=title,
                   body=relativize_paths(result.render()),
                   source="glassbox.refresh"))


def refresh(
    *,
    dry_run: bool = False,
    # Defaults to True — fail closed. A run that did not say it had a human attached is
    # assumed not to, so the stricter gate applies unless the operator opts out.
    automated: bool = True,
    runner: Runner = _default_runner,
    alert_fn: AlertFn = dispatch,
    now: datetime | None = None,
    frontend_dir: Path = FRONTEND_DIR,
    snapshot_out: Path = SNAPSHOT_OUT,
    dist_dir: Path = DIST_DIR,
    env_path: Path | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    repo_state: RepoState | None = None,
    # Test seams. Typed loosely on purpose: the real callables return concrete
    # SnapshotResult / DistVerifyResult, while the suite injects structural doubles.
    snapshot_fn: Callable[..., Any] | None = None,
    verify_fn: Callable[..., Any] | None = None,
    # PROP-9. `record` is opt-out so the pre-existing suite, whose FakeRunner takes no
    # env argument and would otherwise reach real git, keeps testing what it tested.
    record: bool = True,
    git_runner: GitRunner | None = None,
) -> RefreshResult:
    """Run the refresh chain. Returns the outcome; never raises for an expected failure.

    ``now`` is threaded into the published-bytes gate so the freshness check measures the
    snapshot against the instant this chain started, not a drifting wall clock -- the gate
    and the report it emails then agree about what "fresh" meant.
    """
    from quantlab.glassbox.sanitize import SanitizationError
    from quantlab.glassbox.snapshot import write_snapshot
    from quantlab.glassbox.verify_dist import verify_dist

    started = now if now is not None else datetime.now(UTC)
    result = RefreshResult(started_at=started, dry_run=dry_run, automated=automated)

    # Provenance first, so it is on the report even if the chain aborts at step one.
    # Report-only: a dirty tree never blocks a publish.
    result.repo = repo_state if repo_state is not None else check_repo_state()
    for warning in result.repo.warnings:
        log.warning("glassbox_refresh_repo_unclean", detail=warning)
    take_snapshot = snapshot_fn if snapshot_fn is not None else write_snapshot
    run_gate = verify_fn if verify_fn is not None else verify_dist

    def abort(step: str, reason: str) -> RefreshResult:
        result.aborted_at = step
        result.abort_reason = reason
        log.error("glassbox_refresh_aborted", step=step, reason=reason)
        _alert(result, alert_fn)
        return result

    # -- 1. snapshot -------------------------------------------------------
    snap = StepOutcome(name=STEP_SNAPSHOT, ran=True)
    result.steps.append(snap)
    try:
        snapshot = take_snapshot(snapshot_out, env_path=env_path)
    except SanitizationError as exc:
        # Nothing was written: the snapshot gate refuses partial output by design.
        result.snapshot_report_text = exc.report.render()
        result.forbidden_matches = [f.pattern for f in exc.report.failures]
        snap.detail = (f"REFUSED — forbidden pattern(s): "
                       f"{', '.join(result.forbidden_matches)}; nothing written")
        return abort(STEP_SNAPSHOT, snap.detail)
    except Exception as exc:  # pragma: no cover - environment failure
        snap.detail = f"{type(exc).__name__}: {exc}"
        return abort(STEP_SNAPSHOT, snap.detail)

    report = snapshot.report
    result.snapshot_report_text = report.render()
    result.snapshot_env_checked = bool(getattr(report, "env_checked", True))
    if getattr(report, "env_note", None):
        result.env_notes.append(f"snapshot: {report.env_note}")
    result.redaction_count = report.redaction_count
    result.forbidden_matches = [f.pattern for f in report.failures]
    snap.ok = True
    snap.detail = (
        f"{snapshot.manifest.endpoint_count} endpoint(s) captured, "
        f"{len(snapshot.files_written)} file(s) written, "
        f"{report.redaction_count} redaction(s)"
    )

    # -- 2. build ----------------------------------------------------------
    build = StepOutcome(name=STEP_BUILD, ran=True, argv=build_build_command())
    result.steps.append(build)
    try:
        proc = runner(build.argv, frontend_dir)
    except OSError as exc:
        # e.g. npm not installed or not on PATH. An unlaunchable tool is a chain
        # failure to report, not a traceback for the scheduler to swallow.
        build.detail = f"could not launch {build.argv[0]}: {exc}"
        return abort(STEP_BUILD, build.detail)
    build.returncode, build.stdout, build.stderr = (
        proc.returncode, proc.stdout or "", proc.stderr or ""
    )
    if proc.returncode != 0:
        build.detail = f"npm run build:public exited {proc.returncode}"
        return abort(STEP_BUILD, build.detail)
    build.ok = True
    build.detail = "public bundle built into frontend/dist"

    # -- 3. verify the published bytes -------------------------------------
    gate = StepOutcome(name=STEP_VERIFY, ran=True)
    result.steps.append(gate)
    try:
        verified = run_gate(dist_dir, env_path=env_path,
                           max_age_days=max_age_days, now=started)
    except FileNotFoundError as exc:
        gate.detail = str(exc)
        return abort(STEP_VERIFY, gate.detail)
    result.verify_report_text = verified.render()
    dist_report = getattr(verified, "report", None)
    result.dist_env_checked = bool(getattr(dist_report, "env_checked", True))
    dist_env_note = getattr(dist_report, "env_note", None)
    if dist_env_note:
        result.env_notes.append(f"verify-dist: {dist_env_note}")
    result.redactable_findings = list(verified.redactable_findings)
    result.forbidden_matches = sorted(
        set(result.forbidden_matches) | {f.pattern for f in verified.report.failures}
    )
    if not verified.passed:
        failures = [f.pattern for f in verified.report.failures] + \
                   [c.name for c in verified.content.failures]
        gate.detail = f"gate FAILED: {', '.join(failures)}"
        return abort(STEP_VERIFY, gate.detail)
    gate.ok = True
    gate.detail = (f"{verified.files_text} published file(s) scanned, 0 forbidden, "
                   f"{len(result.redactable_findings)} redactable finding(s)")

    # -- doctrine gate: clean, or a human looks ----------------------------
    #
    # AN UNCHECKED SECRET GATE IS TREATED EXACTLY AS A REDACTION: hold the bytes, raise a
    # WARNING, let a human look. Consequence of Defect #2 (2026-08-15): the `.env`
    # fallback in `verify_dist` was CWD-relative, and a missing `.env` is not an error
    # there — `load_env_secret_prefixes` returns an empty prefix set with a note and the
    # gate still reports PASS. Under the scheduler that combination would have published
    # bytes whose env-secret half had searched for nothing, while the chain report said
    # PASS. The path bug is fixed; this closes the class, because "the check silently did
    # not run" must never be indistinguishable from "the check ran and found nothing".
    #
    # AUTOMATED ONLY. Interactive runs and `--dry-run` keep the note and proceed: there a
    # human is reading the report, the note is visible in it, and nothing publishes
    # without them. The distinction is not convenience — it is that the abort exists to
    # substitute for a reader who is absent, so it fires exactly when the reader is.
    if result.automated and not dry_run and not result.env_checked:
        notes = "; ".join(result.env_notes) or "no note recorded"
        return abort(
            STEP_DEPLOY,
            "env-secret check did NOT run "
            f"({notes}); an automated deploy requires the secret search to have actually "
            "executed, so these bytes are held for human pre-review exactly as a "
            "redaction would hold them",
        )
    if result.redaction_count > 0:
        return abort(
            STEP_DEPLOY,
            f"{result.redaction_count} redaction(s) performed during capture; the "
            f"amended doctrine requires ZERO for an automated deploy, so these bytes "
            f"are held for human pre-review",
        )
    if result.redactable_findings:
        return abort(
            STEP_DEPLOY,
            f"{len(result.redactable_findings)} redactable finding(s) in the published "
            f"bytes; fix at source and re-run. Held for human pre-review",
        )

    # -- 4. deploy ---------------------------------------------------------
    deploy = StepOutcome(name=STEP_DEPLOY, argv=build_deploy_command())
    result.steps.append(deploy)
    if dry_run:
        deploy.detail = "withheld (--dry-run); all gates passed"
        log.info("glassbox_refresh_dry_run_complete")
        _alert(result, alert_fn)
        return result

    deploy.ran = True
    try:
        proc = runner(deploy.argv, frontend_dir)
    except OSError as exc:
        deploy.detail = f"could not launch {deploy.argv[0]}: {exc}"
        return abort(STEP_DEPLOY, deploy.detail)
    deploy.returncode, deploy.stdout, deploy.stderr = (
        proc.returncode, proc.stdout or "", proc.stderr or ""
    )
    if proc.returncode != 0:
        deploy.detail = f"netlify deploy exited {proc.returncode}"
        return abort(STEP_DEPLOY, deploy.detail)
    deploy.ok = True
    result.deployed = True
    result.deploy_url = extract_deploy_url(deploy.stdout) or CANONICAL_URL
    deploy.detail = f"published to {result.deploy_url}"
    log.info("glassbox_refresh_deployed", url=result.deploy_url,
             endpoints=snapshot.manifest.endpoint_count)

    # -- 5. record what was published (PROP-9) -----------------------------
    # After the publish, never before, and never able to undo it. Every failure mode
    # here is caught: this step exists to improve the record, and a bookkeeping problem
    # must not be able to report a successful publish as a failed one.
    if record:
        try:
            step = record_snapshot(
                result, root=PROJECT_ROOT, day=(now or datetime.now(UTC)).date(),
                runner=git_runner,
            )
        except SnapshotBranchExists as exc:
            step = StepOutcome(name=STEP_RECORD, ran=True, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 - see the docstring above
            step = StepOutcome(name=STEP_RECORD, ran=True,
                               detail=f"{type(exc).__name__}: {exc}")
        result.steps.append(step)
        if not step.ok:
            result.snapshot_record_note = step.detail
            log.warning("glassbox_snapshot_not_recorded", detail=step.detail)

    _alert(result, alert_fn)
    return result


__all__ = [
    "CANONICAL_URL",
    "NETLIFY_SITE_ID",
    "NETLIFY_SITE_NAME",
    "RefreshResult",
    "StepOutcome",
    "STEP_ORDER",
    "SNAPSHOT_BRANCH_PREFIX",
    "SnapshotBranchExists",
    "build_build_command",
    "build_deploy_command",
    "build_snapshot_branch",
    "record_snapshot",
    "extract_deploy_url",
    "refresh",
    "relativize_paths",
]
