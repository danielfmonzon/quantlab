"""Refresh-chain tests: fail-closed ordering, the doctrine gate, and the alerts.

Nothing here runs npm, netlify, or a real capture. A fake runner records every argv and a
fake alert sink records every Alert, so the assertions are about the CHAIN's decisions
rather than about any tool's behaviour.

The load-bearing property is negative: for each way a step can fail, the steps after it
must not have run. A chain that merely reports a failure while having already deployed
would be worse than no automation at all.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from quantlab.glassbox.refresh import (
    NETLIFY_SITE_ID,
    STEP_ORDER,
    RefreshResult,
    SnapshotBranchExists,
    _alert,
    build_build_command,
    build_deploy_command,
    build_snapshot_branch,
    extract_deploy_url,
    record_snapshot,
    refresh,
)
from quantlab.glassbox.sanitize import (
    ForbiddenRecord,
    RedactionRecord,
    SanitizationError,
    SanitizationReport,
)
from quantlab.reporting.alerts import Alert

NOW = datetime(2026, 8, 10, 22, 0, 0, tzinfo=UTC)

_NETLIFY_STDOUT = """
Deploying to main site URL...
✔ Finished hashing
✔ Deploy is live!

Build logs:        https://app.netlify.com/sites/monzonautomation-glassbox/deploys/abc
Unique deploy URL: https://abc123--monzonautomation-glassbox.netlify.app
Website URL:       https://glassbox.danielmonzonautomation.com
"""


class FakeRunner:
    """Records (argv, cwd) and returns a scripted returncode per command word."""

    def __init__(self, fail: str | None = None, stdout: str = _NETLIFY_STDOUT):
        self.calls: list[tuple[list[str], str]] = []
        self._fail = fail
        self._stdout = stdout

    def __call__(self, cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        argv = list(cmd)
        self.calls.append((argv, str(cwd)))
        joined = " ".join(argv)
        rc = 1 if (self._fail and self._fail in joined) else 0
        out = self._stdout if "netlify" in joined else "built"
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="boom" if rc else "")

    @property
    def ran(self) -> list[str]:
        """A coarse label per executed command, for order assertions."""
        return ["build" if "npm" in c[0][0] else "deploy" for c in self.calls]


class FakeManifest:
    endpoint_count = 85


class FakeSnapshot:
    def __init__(self, report: SanitizationReport):
        self.report = report
        self.manifest = FakeManifest()
        self.files_written = [f"api-e{i}.json" for i in range(85)]


class FakeContent:
    def __init__(self, passed: bool = True):
        self.passed = passed
        self.failures: list[object] = []


class FakeVerified:
    # `env_checked` defaults to True here because the double stands in for a NORMAL run,
    # in which the secret search did execute. It is False on the model by default, which
    # is the right default for the model (absence of evidence is not a passing check) but
    # the wrong one for a fixture claiming to represent a clean gate.
    def __init__(self, *, passed: bool = True, redactable: list[str] | None = None,
                 forbidden: list[ForbiddenRecord] | None = None,
                 env_checked: bool = True, env_note: str | None = None):
        self.report = SanitizationReport(
            passed=not forbidden, forbidden=forbidden or [],
            env_checked=env_checked, env_note=env_note,
        )
        self.content = FakeContent(passed)
        self.passed = passed and not forbidden
        self.redactable_findings = redactable or []
        self.files_text = 88
        self.now_seen: datetime | None = None

    def render(self) -> str:
        return "VERIFY REPORT BODY"


def _clean_report(redactions: int = 0, *, env_checked: bool = True,
                  env_note: str | None = None) -> SanitizationReport:
    records = (
        [RedactionRecord(pattern="windows_user_path", location="assets/index.js",
                         count=redactions, replacement="<path>")]
        if redactions else []
    )
    return SanitizationReport(
        passed=True, files_scanned=22, bytes_scanned=27_321, redactions=records,
        forbidden=[ForbiddenRecord(pattern="alpaca_account_id", count=0)],
        env_checked=env_checked, env_note=env_note,
    )


def _run(*, runner: FakeRunner | None = None, report: SanitizationReport | None = None,
         verified: FakeVerified | None = None, dry_run: bool = False,
         automated: bool = True,
         snapshot_raises: SanitizationError | None = None, alerts: list[Alert] | None = None,
         tmp: Path | None = None, git_runner: object | None = None):
    used_runner = runner or FakeRunner()
    sink = alerts if alerts is not None else []
    captured: dict[str, object] = {}

    def snapshot_fn(out_dir: Path, **kwargs: object) -> FakeSnapshot:
        if snapshot_raises is not None:
            raise snapshot_raises
        return FakeSnapshot(report or _clean_report())

    def verify_fn(dist: Path, **kwargs: object) -> FakeVerified:
        captured["now"] = kwargs.get("now")
        captured["max_age_days"] = kwargs.get("max_age_days")
        return verified or FakeVerified()

    result = refresh(
        dry_run=dry_run, automated=automated,
        runner=used_runner, alert_fn=lambda a: sink.append(a) or [],
        now=NOW, snapshot_fn=snapshot_fn, verify_fn=verify_fn,
        frontend_dir=tmp or Path("frontend"), dist_dir=(tmp or Path("frontend")) / "dist",
        # PROP-9: opt in only when a test injects a git double. The default is already
        # off, so this is belt-and-braces rather than the guarantee.
        record=git_runner is not None, git_runner=git_runner,  # type: ignore[arg-type]
    )
    return result, used_runner, sink, captured


# --------------------------------------------------------------------------- #
# The pinned commands                                                         #
# --------------------------------------------------------------------------- #


def test_deploy_command_pins_the_site_id() -> None:
    """An unpinned deploy prompts interactively and can exit having deployed nothing.

    `npm run build:public` recreates frontend/.netlify/, dropping the site link, so the
    ID must travel on the command line for an unattended run to be deterministic.
    """
    assert build_deploy_command() == [
        "npx", "netlify", "deploy", "--prod", "--dir=dist",
        f"--site={NETLIFY_SITE_ID}",
    ]
    assert NETLIFY_SITE_ID == "be63f48c-4949-4603-b8dd-a6ccfdd996e7"


def test_build_command_is_the_public_build() -> None:
    assert build_build_command() == ["npm", "run", "build:public"]


@pytest.mark.parametrize("stdout,expected", [
    (_NETLIFY_STDOUT, "https://glassbox.danielmonzonautomation.com"),
    ("Unique deploy URL: https://x--y.netlify.app\n", "https://x--y.netlify.app"),
    ("nothing useful here", None),
])
def test_extract_deploy_url(stdout: str, expected: str | None) -> None:
    assert extract_deploy_url(stdout) == expected


# --------------------------------------------------------------------------- #
# The happy path                                                              #
# --------------------------------------------------------------------------- #


def test_clean_chain_deploys_and_reports_the_url() -> None:
    result, runner, alerts, captured = _run()
    assert result.ok and result.deployed
    assert result.deploy_url == "https://glassbox.danielmonzonautomation.com"
    assert runner.ran == ["build", "deploy"]
    # The four PUBLISH steps, in order. The fifth (record-snapshot, PROP-9) runs only
    # after a successful deploy and only when a git runner is supplied, so it is absent
    # here by design -- recording what was published cannot be a precondition of
    # publishing it.
    assert [s.name for s in result.steps] == list(STEP_ORDER[:4])
    assert all(s.ok for s in result.steps)
    # The gate measures freshness against the instant the chain started, not the clock.
    assert captured["now"] == NOW


def test_a_deploy_sends_one_info_alert_carrying_the_whole_report() -> None:
    """Every run mails the report -- a gate only read on failure gets ignored."""
    result, _runner, alerts, _c = _run()
    assert len(alerts) == 1
    assert alerts[0].level == "INFO"
    assert alerts[0].source == "glassbox.refresh"
    # Not a summary: both gate reports are in the body.
    assert "SANITIZATION REPORT" in alerts[0].body
    assert "VERIFY REPORT BODY" in alerts[0].body
    assert result.render() == alerts[0].body


def test_dry_run_passes_every_gate_but_does_not_deploy() -> None:
    result, runner, alerts, _c = _run(dry_run=True)
    assert result.ok is True
    assert result.deployed is False
    assert runner.ran == ["build"]  # netlify never invoked
    assert result.step("deploy").ran is False
    assert result.step("deploy").status == "SKIPPED"
    assert alerts[0].level == "INFO"
    assert "not deployed" in alerts[0].title


# --------------------------------------------------------------------------- #
# Fail-closed: nothing downstream runs                                        #
# --------------------------------------------------------------------------- #


def test_snapshot_refusal_stops_the_chain_before_building() -> None:
    """A forbidden pattern in the capture writes nothing and must build nothing."""
    bad = SanitizationReport(
        passed=False,
        forbidden=[ForbiddenRecord(pattern="alpaca_account_id", count=2,
                                   locations=["api-overview.json"])],
    )
    result, runner, alerts, _c = _run(snapshot_raises=SanitizationError(bad))
    assert result.ok is False
    assert result.aborted_at == "snapshot"
    assert runner.calls == []  # neither build nor deploy ran
    assert result.deployed is False
    assert alerts[0].level == "WARNING"
    assert "alpaca_account_id" in result.abort_reason


def test_build_failure_stops_the_chain_before_deploying() -> None:
    result, runner, alerts, _c = _run(runner=FakeRunner(fail="npm"))
    assert result.ok is False
    assert result.aborted_at == "build"
    assert runner.ran == ["build"]  # netlify never invoked
    assert alerts[0].level == "WARNING"


def test_gate_failure_stops_the_chain_before_deploying() -> None:
    """The published-bytes gate is the last thing between a build and the public."""
    result, runner, alerts, _c = _run(verified=FakeVerified(passed=False))
    assert result.ok is False
    assert result.aborted_at == "verify-dist"
    assert runner.ran == ["build"]
    assert result.deployed is False
    assert alerts[0].level == "WARNING"


def test_an_unlaunchable_tool_aborts_cleanly_instead_of_raising() -> None:
    """A missing npm must abort the chain, not surface a traceback to the scheduler.

    Regression for the first live run: `npm` and `npx` are `.cmd` shims on Windows, which
    CreateProcess cannot execute by bare name under shell=False, so the chain died with a
    FileNotFoundError before it could report or alert. The runner now resolves the program
    through shutil.which, and an OSError here is still a reportable abort.
    """
    def exploding(cmd: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "The system cannot find the file specified")

    alerts: list[Alert] = []
    result = refresh(
        runner=exploding, alert_fn=lambda a: alerts.append(a) or [], now=NOW,
        snapshot_fn=lambda out, **kw: FakeSnapshot(_clean_report()),
        verify_fn=lambda d, **kw: FakeVerified(),
    )
    assert result.ok is False
    assert result.aborted_at == "build"
    assert "could not launch npm" in result.abort_reason
    assert result.deployed is False
    assert alerts[0].level == "WARNING"


def test_default_runner_resolves_shims_without_a_shell() -> None:
    """The argv must stay exactly the pinned list -- only argv[0] may be made absolute."""
    from quantlab.glassbox.refresh import _default_runner

    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        captured["argv"] = argv
        captured["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    import quantlab.glassbox.refresh as mod

    original = mod.subprocess.run
    mod.subprocess.run = fake_run  # type: ignore[assignment]
    try:
        _default_runner(["python", "--version"], Path("."))
    finally:
        mod.subprocess.run = original  # type: ignore[assignment]

    argv = captured["argv"]
    assert captured["shell"] is False          # never a shell
    assert argv[1:] == ["--version"]           # arguments untouched
    assert argv[0].lower().endswith(("python", "python.exe"))  # argv[0] resolved


def test_a_failing_deploy_is_reported_not_swallowed() -> None:
    result, runner, alerts, _c = _run(runner=FakeRunner(fail="netlify"))
    assert result.ok is False
    assert result.aborted_at == "deploy"
    assert result.deployed is False
    assert runner.ran == ["build", "deploy"]
    assert alerts[0].level == "WARNING"


# --------------------------------------------------------------------------- #
# The doctrine amendment: zero redactions, or a human looks                   #
# --------------------------------------------------------------------------- #


def test_any_redaction_aborts_before_deploy_for_human_pre_review() -> None:
    """The scrub worked; the REASON it was needed is what a human must see.

    Doctrine amendment 2026-08-10: automation may publish a clean build and may never
    publish one that needed cleaning. The gate itself still PASSES here -- so this is the
    doctrine talking, not the sanitizer.
    """
    result, runner, alerts, _c = _run(report=_clean_report(redactions=1))
    assert result.step("verify-dist").ok is True  # the gate passed...
    assert result.ok is False                     # ...and the doctrine still refused
    assert result.aborted_at == "deploy"
    assert result.deployed is False
    assert runner.ran == ["build"]  # netlify never invoked
    assert "ZERO" in result.abort_reason
    assert "human pre-review" in result.abort_reason
    assert alerts[0].level == "WARNING"
    assert result.redaction_count == 1


def test_redactable_findings_in_published_bytes_also_abort() -> None:
    """Found in already-written bytes, so it cannot be scrubbed here -- fix at source."""
    result, runner, alerts, _c = _run(
        verified=FakeVerified(redactable=["assets/index-abc.js: windows_user_path"])
    )
    assert result.ok is False
    assert result.aborted_at == "deploy"
    assert runner.ran == ["build"]
    assert "human pre-review" in result.abort_reason
    assert alerts[0].level == "WARNING"


def test_zero_redactions_is_what_permits_the_deploy() -> None:
    """The positive control for the test above: same chain, no redaction, deploys."""
    clean, runner_clean, _a, _c = _run(report=_clean_report(redactions=0))
    assert clean.redaction_count == 0
    assert clean.deployed is True
    assert runner_clean.ran == ["build", "deploy"]


def test_dry_run_still_enforces_the_redaction_doctrine() -> None:
    """A dry run must not report 'gates passed' when the doctrine would have refused."""
    result, _runner, alerts, _c = _run(report=_clean_report(redactions=3), dry_run=True)
    assert result.ok is False
    assert result.aborted_at == "deploy"
    assert alerts[0].level == "WARNING"


# --------------------------------------------------------------------------- #
# The report                                                                  #
# --------------------------------------------------------------------------- #


def test_alert_body_carries_no_absolute_project_path() -> None:
    """Alerts are PUBLISHED, so the body must not name the operator's home directory.

    glassbox.app copies an alert's body verbatim into /api/timeline. The gate reports
    embedded in the chain report render the absolute directory they scanned, so without
    relativizing, run N's alert becomes run N+1's `windows_user_path` redaction — and under
    the amended doctrine a redaction aborts the deploy, so the chain would poison itself
    into never deploying again. Observed on the first live run, 2026-08-10.
    """
    from quantlab.constants import PROJECT_ROOT

    verified = FakeVerified()
    verified.render = lambda: f"directory      : {PROJECT_ROOT / 'frontend' / 'dist'}"  # type: ignore[method-assign]
    _result, _runner, alerts, _c = _run(verified=verified)
    body = alerts[0].body
    assert str(PROJECT_ROOT) not in body
    assert str(PROJECT_ROOT).replace("\\", "/") not in body
    # The information survives, only the machine-specific prefix goes.
    assert "frontend" in body and "dist" in body


def test_relativize_paths_handles_both_separator_forms() -> None:
    from quantlab.glassbox.refresh import relativize_paths

    root = Path("/repo/quantlab")
    native = str(root)
    posix = native.replace("\\", "/")
    text = f"a={native}/frontend b={posix}/dist c=untouched"
    out = relativize_paths(text, root=root)
    assert native not in out and posix not in out
    assert "c=untouched" in out


def test_report_names_every_step_and_its_status() -> None:
    result, _runner, _a, _c = _run()
    rendered = result.render()
    for name in STEP_ORDER:
        assert name in rendered
    assert "DEPLOYED" in rendered
    assert NETLIFY_SITE_ID in rendered


def test_an_aborted_report_says_where_and_why() -> None:
    result, _runner, _a, _c = _run(report=_clean_report(redactions=2))
    rendered = result.render()
    assert "NOT DEPLOYED" in rendered
    assert "aborted at 'deploy'" in rendered
    assert "redactions        : 2" in rendered
    assert "SKIPPED" in rendered  # the deploy step is visibly not run


# --------------------------------------------------------------------------- #
# The env-secret gate (2026-08-15, consequence of Defect #2)                   #
# --------------------------------------------------------------------------- #
#
# `load_env_secret_prefixes` treats a missing `.env` as a note, not an error: it returns
# an empty prefix set and the surrounding gate still reports PASS. Combined with the
# CWD-relative `.env` fallback that Defect #2 fixed, an unattended chain could have
# published bytes whose env-secret half searched for nothing while the report said PASS.
# The path bug is fixed; these tests close the class.


_NO_ENV = "no .env at .env; secret-prefix check skipped"


def test_automated_run_aborts_when_the_env_secret_check_did_not_run() -> None:
    """The ruling: NOT CHECKED holds the bytes exactly as a redaction does."""
    result, runner, alerts, _c = _run(
        verified=FakeVerified(env_checked=False, env_note=_NO_ENV),
    )
    assert not result.ok
    assert result.aborted_at == "deploy"
    assert "env-secret check did NOT run" in (result.abort_reason or "")
    assert "held for human pre-review" in (result.abort_reason or "")
    # Held, not published: the deploy command never ran.
    assert "deploy" not in runner.ran
    assert not result.deployed
    # And a human is told, at WARNING, exactly as a redaction abort does.
    assert len(alerts) == 1
    assert alerts[0].level == "WARNING"


def test_automated_run_aborts_when_the_snapshot_half_did_not_check() -> None:
    """Either half being unchecked is enough; the gate is the conjunction of both."""
    result, runner, _a, _c = _run(
        report=_clean_report(env_checked=False, env_note=_NO_ENV),
    )
    assert not result.ok
    assert result.aborted_at == "deploy"
    assert "deploy" not in runner.ran


def test_interactive_run_keeps_the_note_and_deploys() -> None:
    """A human is reading the report, so the note is enough and nothing is held."""
    result, runner, _a, _c = _run(
        automated=False, verified=FakeVerified(env_checked=False, env_note=_NO_ENV),
    )
    assert result.ok, result.abort_reason
    assert result.deployed
    assert "deploy" in runner.ran
    assert not result.env_checked
    rendered = result.render()
    assert "NOT CHECKED (note only" in rendered
    assert _NO_ENV in rendered


def test_dry_run_keeps_the_note_and_does_not_abort() -> None:
    """`--dry-run` publishes nothing, so the stricter gate has nothing to protect."""
    result, runner, _a, _c = _run(
        dry_run=True, verified=FakeVerified(env_checked=False, env_note=_NO_ENV),
    )
    assert result.ok, result.abort_reason
    assert not result.deployed
    assert "deploy" not in runner.ran
    assert _NO_ENV in result.render()


def test_a_checked_env_gate_deploys_normally_and_says_so() -> None:
    """The gate must not fire on the happy path, or it is just an off switch."""
    result, runner, _a, _c = _run()
    assert result.ok and result.deployed
    assert result.env_checked
    assert "env-secret check  : ran" in result.render()


def test_the_env_gate_is_reported_on_every_run_not_only_on_failure() -> None:
    """"The check ran" should be confirmable, not inferred from the absence of a note."""
    assert "env-secret check" in _run()[0].render()
    assert "env-secret check" in _run(dry_run=True)[0].render()


# --------------------------------------------------------------------------- #
# Recording the published snapshot (PROP-9)                                    #
# --------------------------------------------------------------------------- #

class GitRecorder:
    """Records every git/gh invocation and executes NONE of them.

    The point of this double is negative, as in PROP-3 and PROP-7: it lets a test assert
    that a code path never reached git at all, which is stronger than asserting it
    reached git and was rejected.
    """

    def __init__(self, fail: str | None = None, exists: bool = False) -> None:
        self.calls: list[list[str]] = []
        self._fail = fail
        self._exists = exists

    def __call__(self, cmd, cwd, env=None):  # noqa: ANN001, ANN204
        argv = list(cmd)
        self.calls.append(argv)
        joined = " ".join(argv)
        if argv[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(argv, 0 if self._exists else 1, "", "")
        if argv[:2] == ["git", "ls-remote"]:
            out = "abc123\trefs/heads/x\n" if self._exists else ""
            return subprocess.CompletedProcess(argv, 0, out, "")
        if self._fail and self._fail in joined:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        if argv[:2] == ["git", "write-tree"]:
            return subprocess.CompletedProcess(argv, 0, "treesha\n", "")
        if argv[:2] == ["git", "commit-tree"]:
            return subprocess.CompletedProcess(argv, 0, "commitsha\n", "")
        if argv[:3] == ["gh", "pr", "create"]:
            return subprocess.CompletedProcess(
                argv, 0, "https://github.com/o/r/pull/99\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def argv_for(self, *prefix: str) -> list[list[str]]:
        n = len(prefix)
        return [c for c in self.calls if c[:n] == list(prefix)]


def _deployed_result() -> RefreshResult:
    r = RefreshResult(started_at=datetime(2026, 9, 4, 21, 30, tzinfo=UTC))
    r.deployed = True
    r.deploy_url = "https://glassbox.danielmonzonautomation.com"
    return r


DAY = date(2026, 9, 4)


def test_the_branch_name_is_generated_from_the_date_and_nothing_else() -> None:
    assert build_snapshot_branch(DAY) == "snapshot/deploy-20260904"
    assert build_snapshot_branch(date(2026, 12, 31)) == "snapshot/deploy-20261231"


def test_a_clean_deploy_records_pushes_and_opens_a_pr(tmp_path: Path) -> None:
    """The happy path: branch created, pushed, PR opened for a human to merge."""
    runner = GitRecorder()
    result = _deployed_result()
    step = record_snapshot(result, root=tmp_path, day=DAY, runner=runner)

    assert step.ok
    assert result.snapshot_branch == "snapshot/deploy-20260904"
    assert result.snapshot_pr_url == "https://github.com/o/r/pull/99"

    branch_calls = runner.argv_for("git", "branch")
    assert branch_calls == [["git", "branch", "snapshot/deploy-20260904", "commitsha"]]
    for call in branch_calls:
        assert "--force" not in call and "-f" not in call

    push = runner.argv_for("git", "push")[0]
    assert "snapshot/deploy-20260904" in push
    assert "main" not in push

    pr = runner.argv_for("gh", "pr", "create")[0]
    assert "snapshot: captures from the 2026-09-04 refresh" in pr
    assert pr[pr.index("--base") + 1] == "main"


def test_nothing_touches_the_trunk(tmp_path: Path) -> None:
    """No recorded command may name `main` as something to write to."""
    runner = GitRecorder()
    record_snapshot(_deployed_result(), root=tmp_path, day=DAY, runner=runner)
    for call in runner.calls:
        if call[:2] in (["git", "branch"], ["git", "push"], ["git", "checkout"]):
            assert "main" not in call, call
    assert runner.argv_for("git", "checkout") == []      # HEAD is never moved
    assert runner.argv_for("git", "commit") == []        # the real index is never used


def test_an_existing_branch_raises_before_any_git_command_runs(tmp_path: Path) -> None:
    """Assert-before-create, and the assertion is what stops it.

    Only the two existence probes may have run. Nothing is committed, nothing pushed,
    no PR opened -- a branch this step did not create is never moved.
    """
    runner = GitRecorder(exists=True)
    with pytest.raises(SnapshotBranchExists) as excinfo:
        record_snapshot(_deployed_result(), root=tmp_path, day=DAY, runner=runner)

    assert excinfo.value.branch == "snapshot/deploy-20260904"
    assert runner.argv_for("git", "branch") == []
    assert runner.argv_for("git", "push") == []
    assert runner.argv_for("gh", "pr", "create") == []
    assert runner.argv_for("git", "commit-tree") == []


def test_a_failed_push_does_not_retroactively_fail_the_deploy(tmp_path: Path) -> None:
    """The bytes are already live. Reporting the publish as failed would be false."""
    runner = GitRecorder(fail="git push")
    result = _deployed_result()
    step = record_snapshot(result, root=tmp_path, day=DAY, runner=runner)

    assert not step.ok
    assert "NOT pushed" in step.detail
    assert result.deployed is True                       # unchanged
    assert result.deploy_url == "https://glassbox.danielmonzonautomation.com"
    assert result.aborted_at is None                     # not an abort


def test_a_recording_failure_downgrades_the_run_to_a_warning(tmp_path: Path) -> None:
    """WARNING, not INFO and not an abort: one thing is owed, by hand."""
    result = _deployed_result()
    result.snapshot_record_note = "branch created but NOT pushed: boom"
    alerts: list[Alert] = []
    _alert(result, alerts.append)

    assert len(alerts) == 1
    assert alerts[0].level == "WARNING"
    assert "NOT recorded" in alerts[0].title
    rendered = result.render()
    assert "DEPLOYED ->" in rendered                     # still says it published
    assert "NOT RECORDED" in rendered


def test_a_successful_record_keeps_the_run_at_info(tmp_path: Path) -> None:
    result = _deployed_result()
    result.snapshot_branch = "snapshot/deploy-20260904"
    result.snapshot_pr_url = "https://github.com/o/r/pull/99"
    alerts: list[Alert] = []
    _alert(result, alerts.append)

    assert alerts[0].level == "INFO"
    assert "RECORDED -> snapshot/deploy-20260904" in result.render()


def test_a_dry_run_never_reaches_the_recording_step(tmp_path: Path) -> None:
    """Nothing was published, so there is nothing to record."""
    runner = GitRecorder()
    result, _r, _a, _c = _run(dry_run=True, git_runner=runner)
    assert result.snapshot_branch is None
    assert runner.calls == []
    assert not any(s.name == "record-snapshot" for s in result.steps)


def test_a_chain_that_aborts_before_deploy_never_records(tmp_path: Path) -> None:
    """Fail-closed ordering holds: no publish, no record."""
    runner = GitRecorder()
    result, _r, _a, _c = _run(runner=FakeRunner(fail="netlify"), git_runner=runner)
    assert result.deployed is False
    assert runner.calls == []
    assert result.snapshot_branch is None


def test_recording_is_off_by_default_so_no_test_can_reach_real_git() -> None:
    """The default must be safe, not merely guarded at the call sites we remembered.

    An earlier draft defaulted this on.  calls refresh()
    directly, reaches a successful deploy, and had no reason to know about a flag that
    did not exist when it was written -- so it used the REAL git and gh, created a
    branch and opened a pull request against this repository during a test run. That is
    the failure this pins: a default that is only safe while every caller remembers a
    flag is not safe.
    """
    import inspect

    from quantlab.glassbox.refresh import refresh as refresh_fn

    assert inspect.signature(refresh_fn).parameters["record"].default is False


def test_a_deploy_without_opting_in_records_nothing(tmp_path: Path) -> None:
    """Reaching a successful deploy is not enough to make it touch a repository."""
    result, _runner, _alerts, _c = _run()
    assert result.deployed is True
    assert result.snapshot_branch is None
    assert result.snapshot_record_note is None
    assert not any(s.name == "record-snapshot" for s in result.steps)
