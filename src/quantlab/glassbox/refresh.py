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

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quantlab.constants import PROJECT_ROOT
from quantlab.glassbox.completeness import DEFAULT_MAX_AGE_DAYS
from quantlab.logging_setup import get_logger
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
STEP_ORDER = (STEP_SNAPSHOT, STEP_BUILD, STEP_VERIFY, STEP_DEPLOY)

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
    steps: list[StepOutcome] = []
    # The snapshot writer's report, then the published-bytes gate's report. Both are
    # rendered into the email; both feed the deploy decision.
    snapshot_report_text: str = ""
    verify_report_text: str = ""
    redaction_count: int = 0
    redactable_findings: list[str] = []
    forbidden_matches: list[str] = []
    deployed: bool = False
    deploy_url: str | None = None
    aborted_at: str | None = None
    abort_reason: str | None = None

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
        lines.append("DEPLOY DECISION")
        lines.append("-" * 72)
        lines.append(f"  forbidden matches : {len(self.forbidden_matches)} "
                     f"{'(must be 0)' if self.forbidden_matches else 'ok'}")
        lines.append(f"  redactions        : {self.redaction_count} "
                     f"{'(must be 0 to auto-deploy)' if self.redaction_count else 'ok'}")
        lines.append(f"  redactable found  : {len(self.redactable_findings)} "
                     f"{'(must be 0 to auto-deploy)' if self.redactable_findings else 'ok'}")
        for finding in self.redactable_findings:
            lines.append(f"      {finding}")
        if self.deployed:
            lines.append(f"  DEPLOYED -> {self.deploy_url or CANONICAL_URL}")
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
    if result.deployed:
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
    runner: Runner = _default_runner,
    alert_fn: AlertFn = dispatch,
    now: datetime | None = None,
    frontend_dir: Path = FRONTEND_DIR,
    snapshot_out: Path = SNAPSHOT_OUT,
    dist_dir: Path = DIST_DIR,
    env_path: Path | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    # Test seams. Typed loosely on purpose: the real callables return concrete
    # SnapshotResult / DistVerifyResult, while the suite injects structural doubles.
    snapshot_fn: Callable[..., Any] | None = None,
    verify_fn: Callable[..., Any] | None = None,
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
    result = RefreshResult(started_at=started, dry_run=dry_run)
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
    _alert(result, alert_fn)
    return result


__all__ = [
    "CANONICAL_URL",
    "NETLIFY_SITE_ID",
    "NETLIFY_SITE_NAME",
    "RefreshResult",
    "StepOutcome",
    "STEP_ORDER",
    "build_build_command",
    "build_deploy_command",
    "extract_deploy_url",
    "refresh",
    "relativize_paths",
]
