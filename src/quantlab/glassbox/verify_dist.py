"""Run the sanitization gate over an entire built site, not just the snapshot JSON.

WHY THIS EXISTS SEPARATELY FROM `snapshot`. The snapshot gate vets the JSON it is about
to write. That is necessary and not sufficient: what actually gets *published* is
``dist/`` — compiled JavaScript, CSS, HTML, SVG, the copied snapshot, and anything else
a build tool decided to emit. A secret could reach the public through a source map, an
inlined constant, a comment surviving minification, or a file someone dropped in
``public/`` by hand. None of those pass through the snapshot writer.

So this scans the published bytes. It is the last check before a deploy, and it is the
one whose scope matches the thing being deployed.

Read-only: nothing is rewritten. Where the snapshot gate redacts and then writes, this
gate can only *report* — the bytes already exist — so a redactable pattern found here is
surfaced as a finding to fix at source, and any forbidden match exits non-zero.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from quantlab.glassbox.completeness import (
    DEFAULT_MAX_AGE_DAYS,
    ContentReport,
    check_content,
)
from quantlab.glassbox.sanitize import (
    SanitizationReport,
    load_env_secret_prefixes,
    redact,
    scan_forbidden,
)

# Extensions worth scanning as text. Binary assets (png/ico/woff2) cannot carry a
# greppable secret in any form this gate could detect, and decoding them as text would
# produce noise; they are counted as skipped so the report is explicit about coverage.
TEXT_SUFFIXES = frozenset({
    ".js", ".mjs", ".cjs", ".css", ".html", ".htm", ".json", ".svg", ".txt",
    ".xml", ".map", ".webmanifest", ".toml", ".md", "",
})

BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pdf", ".zip", ".gz",
})


class DistVerifyResult(BaseModel):
    report: SanitizationReport
    # Positive assertions about what the site CONTAINS. The pattern scan above can only
    # find bad content; without this, an empty build passes.
    content: ContentReport = ContentReport()
    dir: str
    files_text: int = 0
    files_binary_skipped: int = 0
    binary_names: list[str] = []
    # Redactable content found in already-written bytes. Cannot be fixed here — the
    # build must be regenerated from a clean source — so it is a finding, not a fix.
    redactable_findings: list[str] = []

    def render(self) -> str:
        lines = [
            "=" * 72,
            "GLASS BOX DIST VERIFICATION — published bytes",
            "=" * 72,
            f"directory      : {self.dir}",
            f"text files     : {self.files_text} scanned",
            f"binary files   : {self.files_binary_skipped} skipped (not text-scannable)",
        ]
        if self.binary_names:
            lines.append(f"                 {', '.join(self.binary_names)}")
        lines.append("")
        lines.append(self.content.render())
        lines.append("")
        lines.append(self.report.render())
        lines.append("")
        lines.append(f"REDACTABLE CONTENT IN PUBLISHED BYTES ({len(self.redactable_findings)})")
        lines.append("-" * 72)
        if not self.redactable_findings:
            lines.append("  (none — no local path leaked into the build)")
        else:
            lines.append("  These are already written and CANNOT be fixed by redaction here.")
            lines.append("  Fix the source and rebuild:")
            for finding in self.redactable_findings:
                lines.append(f"    {finding}")
        lines.append("")
        lines.append("=" * 72)
        if self.passed:
            lines.append("DIST PASS — safe to deploy, subject to human review of this report.")
        else:
            reasons = []
            if not self.content.passed:
                reasons.append("missing content")
            if not self.report.passed:
                reasons.append("forbidden pattern")
            lines.append(f"DIST FAIL ({', '.join(reasons)}) — do not deploy.")
        lines.append("=" * 72)
        return "\n".join(lines)

    @property
    def passed(self) -> bool:
        # A leaked local path is a finding, not a hard failure: it is embarrassing
        # rather than dangerous, and blocking on it would tempt someone to skip the
        # gate. A forbidden match is a hard failure — and so is missing content, which
        # is the hole that let a data-less build ship on 2026-07-26.
        return self.report.passed and self.content.passed


def verify_dist(
    dist_dir: Path,
    *,
    env_path: Path | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> DistVerifyResult:
    """Scan every text file under ``dist_dir`` and assert it contains real data.

    Never modifies anything.
    """
    if not dist_dir.exists():
        raise FileNotFoundError(f"no such directory: {dist_dir}")

    resolved_env = env_path if env_path is not None else Path(".env")
    env = load_env_secret_prefixes(resolved_env)

    forbidden_counts: dict[str, int] = {}
    forbidden_locations: dict[str, list[str]] = {}
    redactable: list[str] = []
    binary_names: list[str] = []
    text_count = 0
    bytes_scanned = 0

    for path in sorted(dist_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(dist_dir).as_posix()
        suffix = path.suffix.lower()
        if suffix in BINARY_SUFFIXES:
            binary_names.append(rel)
            continue
        if suffix not in TEXT_SUFFIXES:
            # Unknown extension: scan it anyway. An unrecognised text file that the
            # gate skipped is exactly the hole this module exists to close.
            pass
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        text_count += 1
        bytes_scanned += path.stat().st_size

        _redacted, performed = redact(text)
        for name, count, _replacement in performed:
            redactable.append(f"{rel}: {name} x{count}")

        for name, count in scan_forbidden(text, env):
            forbidden_counts[name] = forbidden_counts.get(name, 0) + count
            forbidden_locations.setdefault(name, []).append(rel)

    from quantlab.glassbox.sanitize import (
        ENV_SECRET_PATTERN_PREFIX,
        FORBIDDEN_PATTERNS,
        ForbiddenRecord,
    )

    records: list[ForbiddenRecord] = []
    for name, _pattern in FORBIDDEN_PATTERNS:
        records.append(ForbiddenRecord(
            pattern=name,
            count=forbidden_counts.get(name, 0),
            locations=sorted(set(forbidden_locations.get(name, []))),
        ))
    if env.found:
        for key in env.keys:
            name = f"{ENV_SECRET_PATTERN_PREFIX}:{key}"
            records.append(ForbiddenRecord(
                pattern=name,
                count=forbidden_counts.get(name, 0),
                locations=sorted(set(forbidden_locations.get(name, []))),
            ))
    else:
        records.append(ForbiddenRecord(
            pattern=f"{ENV_SECRET_PATTERN_PREFIX}:*",
            count=0, checked=False, note=env.note,
        ))

    report = SanitizationReport(
        passed=all(r.count == 0 for r in records),
        files_scanned=text_count,
        bytes_scanned=bytes_scanned,
        redactions=[],  # nothing is rewritten here
        forbidden=records,
        env_checked=env.found,
        env_keys_checked=env.keys if env.found else [],
        env_keys_excluded=env.excluded if env.found else [],
        env_note=env.note,
    )

    return DistVerifyResult(
        report=report,
        content=check_content(dist_dir, max_age_days=max_age_days),
        dir=str(dist_dir), files_text=text_count,
        files_binary_skipped=len(binary_names), binary_names=binary_names,
        redactable_findings=redactable,
    )


__all__ = ["verify_dist", "DistVerifyResult", "TEXT_SUFFIXES", "BINARY_SUFFIXES"]
