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
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantlab.glassbox.refresh import (
    NETLIFY_SITE_ID,
    STEP_ORDER,
    build_build_command,
    build_deploy_command,
    extract_deploy_url,
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
    def __init__(self, *, passed: bool = True, redactable: list[str] | None = None,
                 forbidden: list[ForbiddenRecord] | None = None):
        self.report = SanitizationReport(passed=not forbidden, forbidden=forbidden or [])
        self.content = FakeContent(passed)
        self.passed = passed and not forbidden
        self.redactable_findings = redactable or []
        self.files_text = 88
        self.now_seen: datetime | None = None

    def render(self) -> str:
        return "VERIFY REPORT BODY"


def _clean_report(redactions: int = 0) -> SanitizationReport:
    records = (
        [RedactionRecord(pattern="windows_user_path", location="assets/index.js",
                         count=redactions, replacement="<path>")]
        if redactions else []
    )
    return SanitizationReport(
        passed=True, files_scanned=22, bytes_scanned=27_321, redactions=records,
        forbidden=[ForbiddenRecord(pattern="alpaca_account_id", count=0)],
    )


def _run(*, runner: FakeRunner | None = None, report: SanitizationReport | None = None,
         verified: FakeVerified | None = None, dry_run: bool = False,
         snapshot_raises: SanitizationError | None = None, alerts: list[Alert] | None = None,
         tmp: Path | None = None):
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
        dry_run=dry_run, runner=used_runner, alert_fn=lambda a: sink.append(a) or [],
        now=NOW, snapshot_fn=snapshot_fn, verify_fn=verify_fn,
        frontend_dir=tmp or Path("frontend"), dist_dir=(tmp or Path("frontend")) / "dist",
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
    assert [s.name for s in result.steps] == list(STEP_ORDER)
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
