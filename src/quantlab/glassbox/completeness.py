"""Positive assertions about a built site: does it actually contain the data it claims?

WHY THIS EXISTS. `verify_dist` only ever asserted the ABSENCE of bad content, and on
2026-07-26 it happily passed a build with no snapshot in it at all — because with no data
there was nothing forbidden to find. A gate that only looks for poison cannot notice an
empty plate. The deploy that followed served a working shell with zero figures in it.

So this module asserts presence. Each check is a claim the published site makes implicitly
by existing, restated as something falsifiable:

* there is a manifest, and it parses;
* it declares a plausible number of endpoints, and that number matches the files present;
* the capture is recent enough to be worth publishing;
* at least one account carries a real equity figure — the site's whole subject;
* the HTML references its entry bundle, and that bundle is on disk.

The sanitization patterns are NOT touched here. They are frozen by ruling, and this is a
separate concern in a separate module for exactly that reason: content completeness and
secret detection fail for different causes and should be readable independently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# A published snapshot below this endpoint count is not a snapshot of this system — it is
# a partial write or a broken capture. The real figure is ~85; 20 is a floor low enough to
# survive endpoints being removed, high enough to catch an empty or truncated capture.
MIN_ENDPOINTS = 20

# Snapshots are refreshed by hand, so some staleness is expected and fine. Two weeks is
# the point at which "manually refreshed" stops being an explanation.
DEFAULT_MAX_AGE_DAYS = 14

SNAPSHOT_DIR = "snapshot"
MANIFEST_NAME = "manifest.json"
OVERVIEW_NAME = "api-overview.json"


class ContentCheck(BaseModel):
    """One positive assertion, and whether the built site satisfies it."""

    name: str
    passed: bool
    detail: str


class ContentReport(BaseModel):
    checks: list[ContentCheck] = []
    max_age_days: int = DEFAULT_MAX_AGE_DAYS

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[ContentCheck]:
        return [c for c in self.checks if not c.passed]

    def render(self) -> str:
        lines = [
            "CONTENT COMPLETENESS (the site must contain what it claims to)",
            "-" * 72,
        ]
        width = max((len(c.name) for c in self.checks), default=20)
        for check in self.checks:
            status = "ok" if check.passed else "*** FAIL ***"
            lines.append(f"  {check.name:<{width}}  {status}")
            lines.append(f"  {'':<{width}}  {check.detail}")
        lines.append("")
        if self.passed:
            lines.append(f"  CONTENT PASS — {len(self.checks)} assertion(s) satisfied.")
        else:
            names = ", ".join(c.name for c in self.failures)
            lines.append(f"  CONTENT FAIL — {names}")
            lines.append("  The build is missing data it needs. Re-run the snapshot.")
        return "\n".join(lines)


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    if not path.exists():
        return None, f"missing: {path.name}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return None, f"unreadable ({type(exc).__name__})"


def check_content(
    dist_dir: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> ContentReport:
    """Run every completeness assertion against a built site."""
    moment = now if now is not None else datetime.now(UTC)
    snapshot = dist_dir / SNAPSHOT_DIR
    checks: list[ContentCheck] = []

    # -- 1. manifest exists and parses ------------------------------------
    manifest, error = _read_json(snapshot / MANIFEST_NAME)
    if manifest is None or not isinstance(manifest, dict):
        checks.append(ContentCheck(
            name="manifest_present",
            passed=False,
            detail=f"{SNAPSHOT_DIR}/{MANIFEST_NAME} {error or 'is not an object'}",
        ))
        # Everything downstream reads the manifest; report the rest as unmet rather
        # than crashing, so one run of the gate lists every problem at once.
        checks.append(ContentCheck(name="endpoint_count", passed=False,
                                   detail="not checked — no manifest"))
        checks.append(ContentCheck(name="manifest_freshness", passed=False,
                                   detail="not checked — no manifest"))
    else:
        checks.append(ContentCheck(
            name="manifest_present", passed=True,
            detail=f"{SNAPSHOT_DIR}/{MANIFEST_NAME} parsed; "
                   f"quantlab {manifest.get('quantlab_version', '?')} @ "
                   f"{manifest.get('git_commit', '?')}",
        ))

        # -- 2. endpoint count is plausible AND matches the files present ---
        declared = manifest.get("endpoint_count")
        endpoints = manifest.get("endpoints")
        n_declared = declared if isinstance(declared, int) else -1
        n_listed = len(endpoints) if isinstance(endpoints, list) else -1
        present = sorted(p.name for p in snapshot.glob("*.json")
                         if p.name != MANIFEST_NAME) if snapshot.exists() else []
        n_present = len(present)

        problems: list[str] = []
        if n_declared < MIN_ENDPOINTS:
            problems.append(f"endpoint_count {n_declared} < minimum {MIN_ENDPOINTS}")
        if n_declared != n_listed:
            problems.append(f"endpoint_count {n_declared} != len(endpoints) {n_listed}")
        if n_declared != n_present:
            problems.append(
                f"endpoint_count {n_declared} != {n_present} snapshot/*.json on disk"
            )
        checks.append(ContentCheck(
            name="endpoint_count",
            passed=not problems,
            detail="; ".join(problems) if problems
                   else f"{n_declared} endpoints declared, listed, and present on disk",
        ))

        # -- 3. freshness --------------------------------------------------
        raw_stamp = manifest.get("generated_at")
        generated: datetime | None = None
        if isinstance(raw_stamp, str) and raw_stamp:
            text = raw_stamp[:-1] + "+00:00" if raw_stamp.endswith("Z") else raw_stamp
            try:
                parsed = datetime.fromisoformat(text)
                generated = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                generated = None
        if generated is None:
            checks.append(ContentCheck(
                name="manifest_freshness", passed=False,
                detail=f"generated_at unparseable: {raw_stamp!r}",
            ))
        else:
            age = moment - generated
            limit = timedelta(days=max_age_days)
            hours = age.total_seconds() / 3600
            checks.append(ContentCheck(
                name="manifest_freshness",
                passed=age <= limit,
                detail=(f"captured {generated.isoformat()} — {hours:.1f}h old"
                        f" (limit {max_age_days}d)"),
            ))

    # -- 4. the overview carries at least one real equity figure ----------
    overview, error = _read_json(snapshot / OVERVIEW_NAME)
    if overview is None or not isinstance(overview, dict):
        checks.append(ContentCheck(
            name="overview_has_data", passed=False,
            detail=f"{SNAPSHOT_DIR}/{OVERVIEW_NAME} {error or 'is not an object'}",
        ))
    else:
        accounts = overview.get("accounts")
        accounts = accounts if isinstance(accounts, list) else []
        with_equity = [
            a for a in accounts
            if isinstance(a, dict) and isinstance(a.get("latest_equity"), (int, float))
            and not isinstance(a.get("latest_equity"), bool)
        ]
        checks.append(ContentCheck(
            name="overview_has_data",
            passed=len(with_equity) >= 1,
            detail=(f"{len(with_equity)} of {len(accounts)} account(s) carry a "
                    "non-null equity figure"
                    if accounts else "no accounts in the overview capture"),
        ))

    # -- 5. the HTML references its entry bundle, and it exists ------------
    index = dist_dir / "index.html"
    if not index.exists():
        checks.append(ContentCheck(name="entry_bundle", passed=False,
                                   detail="index.html missing"))
    else:
        html = index.read_text(encoding="utf-8", errors="replace")
        import re

        refs = re.findall(r'src="(/assets/[^"]+\.js)"', html)
        missing = [r for r in refs if not (dist_dir / r.lstrip("/")).is_file()]
        if not refs:
            detail = "index.html references no /assets/*.js entry script"
        elif missing:
            detail = f"referenced but absent: {', '.join(missing)}"
        else:
            detail = f"{len(refs)} entry script(s) referenced and present: " + ", ".join(
                Path(r).name for r in refs
            )
        checks.append(ContentCheck(
            name="entry_bundle", passed=bool(refs) and not missing, detail=detail,
        ))

    return ContentReport(checks=checks, max_age_days=max_age_days)


__all__ = [
    "check_content",
    "ContentReport",
    "ContentCheck",
    "MIN_ENDPOINTS",
    "DEFAULT_MAX_AGE_DAYS",
]
