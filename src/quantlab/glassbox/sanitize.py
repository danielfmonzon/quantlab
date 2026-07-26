"""Sanitization gate for public snapshots.

Every byte destined for a public snapshot passes through :func:`sanitize` BEFORE it
is written. Two distinct mechanisms, deliberately not interchangeable:

* **Redactions** rewrite content that is merely *local* rather than secret — a
  Windows user path leaks an operator's username into a public artifact, but
  replacing it costs nothing.
* **Forbidden patterns** ABORT the whole snapshot. These are things that must never
  appear in a public artifact and whose presence means an assumption is wrong
  somewhere upstream. A gate that redacted them instead would quietly paper over
  the bug that produced them, so the only safe response is to fail loudly and make
  a human look.

WHAT THE REPORT DOES NOT CONTAIN. The report is written to disk and pasted into
review threads, so it must be safe to share. It therefore records pattern names,
match counts, and file locations — never the matched text. A report that echoed the
secret it found in order to prove it found one would be the leak it was built to
prevent. Redaction entries likewise record the replacement, not the original.

ENV-SECRET CHECK. Secret *values* are read from a local ``.env`` and reduced to
their first :data:`_ENV_PREFIX_LEN` characters, which is what gets searched for. The
values are never logged, never stored on the report, and never returned. If ``.env``
is absent the check cannot run, and the report says so explicitly rather than
reporting a vacuous pass — "0 matches" and "not checked" are different claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

# How many leading characters of each .env value to search for. Long enough that a
# match is not coincidence, short enough to catch a truncated or partial leak.
_ENV_PREFIX_LEN = 8
# Values shorter than this are skipped: a 4-character "secret" would match ordinary
# prose and turn the gate into noise.
_ENV_MIN_LEN = 6


# --------------------------------------------------------------------------- #
# Patterns                                                                    #
# --------------------------------------------------------------------------- #

# A Windows user directory in any of the forms JSON encoding can produce: raw
# (``C:\Users\x``), JSON-escaped (``C:\\Users\\x``), or forward-slashed
# (``C:/Users/x``). Only the user-directory prefix is replaced; the rest of the path
# survives, so a redacted path still reads as a path.
# The separator matches one to four backslashes so raw, JSON-escaped, and
# doubly-escaped forms all redact — text reaches here after ``json.dumps``, and a
# nested payload can be escaped twice over.
_WIN_USER_PATH = re.compile(
    r"[A-Za-z]:(?:\\{1,4}|/)Users(?:\\{1,4}|/)[^\\/\"\s,;:*?<>|]+"
)
_WIN_USER_PATH_REPLACEMENT = "<path>"

# A POSIX home directory, for the same reason. Not required by the brief, but a
# snapshot generated on a Mac or Linux host would leak exactly the same thing, and a
# gate that only guards the current developer's OS is a gate with a hole in it.
_POSIX_HOME_PATH = re.compile(r"/(?:home|Users)/[^/\"\s,;:*?<>|]+")
_POSIX_HOME_REPLACEMENT = "<path>"

REDACTION_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("windows_user_path", _WIN_USER_PATH, _WIN_USER_PATH_REPLACEMENT),
    ("posix_home_path", _POSIX_HOME_PATH, _POSIX_HOME_REPLACEMENT),
)

# Presence of any of these FAILS the snapshot. Names are stable so the report can be
# diffed across runs.
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Alpaca account identifiers. Paper ids are PA-prefixed; the pattern is
    # deliberately broad because a live-account id in a public artifact would be
    # strictly worse than a paper one.
    ("alpaca_account_id", re.compile(r"PA[A-Z0-9]{8,}")),
    ("email_address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # Broker auth header names. Their presence means a request or response envelope
    # has been captured, not just a computed figure.
    ("apca_api_header", re.compile(r"APCA-API", re.IGNORECASE)),
    ("authorization_header", re.compile(r"Authorization", re.IGNORECASE)),
)

ENV_SECRET_PATTERN_PREFIX = "env_secret_prefix"


# --------------------------------------------------------------------------- #
# Report models                                                              #
# --------------------------------------------------------------------------- #


class RedactionRecord(BaseModel):
    """One redaction. Records the replacement, never the original."""

    pattern: str
    location: str
    count: int
    replacement: str


class ForbiddenRecord(BaseModel):
    """One forbidden-pattern result. Zero count is required to pass."""

    pattern: str
    count: int
    # File locations only — never the matched text.
    locations: list[str] = []
    checked: bool = True
    note: str | None = None


class SanitizationReport(BaseModel):
    passed: bool
    files_scanned: int = 0
    bytes_scanned: int = 0
    redactions: list[RedactionRecord] = []
    forbidden: list[ForbiddenRecord] = []
    env_checked: bool = False
    env_keys_checked: list[str] = []
    env_note: str | None = None

    @property
    def redaction_count(self) -> int:
        return sum(r.count for r in self.redactions)

    @property
    def failures(self) -> list[ForbiddenRecord]:
        return [f for f in self.forbidden if f.count > 0]

    def render(self) -> str:
        """Human-readable report. Safe to paste into a review thread."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append("GLASS BOX SNAPSHOT — SANITIZATION REPORT")
        lines.append("=" * 72)
        lines.append(
            f"files scanned : {self.files_scanned}\n"
            f"bytes scanned : {self.bytes_scanned:,}\n"
            f"verdict       : {'PASS' if self.passed else 'FAIL'}"
        )
        lines.append("")
        lines.append("FORBIDDEN PATTERNS (zero matches required to pass)")
        lines.append("-" * 72)
        width = max((len(f.pattern) for f in self.forbidden), default=20)
        for record in self.forbidden:
            if not record.checked:
                status = "NOT CHECKED"
            elif record.count == 0:
                status = "0  ok"
            else:
                status = f"{record.count}  *** FAIL ***"
            lines.append(f"  {record.pattern:<{width}}  {status}")
            if record.note:
                lines.append(f"  {'':<{width}}  ({record.note})")
            for location in record.locations:
                lines.append(f"  {'':<{width}}  in {location}")
        lines.append("")
        lines.append("ENV-SECRET CHECK")
        lines.append("-" * 72)
        if self.env_checked:
            lines.append(
                f"  .env read locally; {len(self.env_keys_checked)} value(s) reduced to "
                f"{_ENV_PREFIX_LEN}-char prefixes and searched."
            )
            lines.append(f"  keys checked: {', '.join(self.env_keys_checked) or '(none)'}")
            lines.append("  (prefixes themselves are never printed or stored)")
        else:
            lines.append(f"  NOT CHECKED — {self.env_note or 'no .env found'}")
        lines.append("")
        lines.append(f"REDACTIONS PERFORMED ({self.redaction_count})")
        lines.append("-" * 72)
        if not self.redactions:
            lines.append("  (none)")
        for redaction in self.redactions:
            lines.append(
                f"  {redaction.pattern}  x{redaction.count}  ->  {redaction.replacement}"
                f"   in {redaction.location}"
            )
        lines.append("")
        lines.append("=" * 72)
        if self.passed:
            lines.append("PASS — no forbidden pattern matched. Snapshot may be written.")
        else:
            names = ", ".join(f.pattern for f in self.failures)
            lines.append(f"FAIL — forbidden pattern(s) matched: {names}")
            lines.append("Nothing was written. Fix the source, then re-run.")
        lines.append("=" * 72)
        return "\n".join(lines)


class SanitizationError(RuntimeError):
    """Raised when a forbidden pattern is found. Carries the report."""

    def __init__(self, report: SanitizationReport):
        self.report = report
        names = ", ".join(f.pattern for f in report.failures)
        super().__init__(f"snapshot sanitization FAILED: {names}")


# --------------------------------------------------------------------------- #
# Env secrets                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class _EnvSecrets:
    """Secret prefixes to search for. Values never leave this object."""

    prefixes: dict[str, str] = field(default_factory=dict)
    found: bool = False
    note: str | None = None

    @property
    def keys(self) -> list[str]:
        return sorted(self.prefixes)


def load_env_secret_prefixes(env_path: Path) -> _EnvSecrets:
    """Read ``.env`` and reduce each value to its leading characters.

    The returned prefixes are used only as search needles. They are never printed,
    logged, or attached to a report.
    """
    if not env_path.exists():
        return _EnvSecrets(note=f"no .env at {env_path.name}; secret-prefix check skipped")
    try:
        raw = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _EnvSecrets(note=f".env unreadable ({type(exc).__name__}); check skipped")

    prefixes: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if len(value) < _ENV_MIN_LEN:
            continue
        prefixes[key] = value[:_ENV_PREFIX_LEN]
    return _EnvSecrets(prefixes=prefixes, found=True)


# --------------------------------------------------------------------------- #
# The gate                                                                   #
# --------------------------------------------------------------------------- #


def redact(text: str) -> tuple[str, list[tuple[str, int, str]]]:
    """Apply every redaction pattern. Returns the clean text and what was replaced.

    The tuples are ``(pattern_name, count, replacement)`` — never the original text.
    """
    performed: list[tuple[str, int, str]] = []
    out = text
    for name, pattern, replacement in REDACTION_PATTERNS:
        out, count = pattern.subn(replacement, out)
        if count:
            performed.append((name, count, replacement))
    return out, performed


def scan_forbidden(
    text: str, env: _EnvSecrets
) -> list[tuple[str, int]]:
    """Count forbidden matches in ``text``. Returns ``(pattern_name, count)`` pairs."""
    results: list[tuple[str, int]] = []
    for name, pattern in FORBIDDEN_PATTERNS:
        count = len(pattern.findall(text))
        if count:
            results.append((name, count))
    for key, prefix in env.prefixes.items():
        count = text.count(prefix)
        if count:
            # The key NAME is safe to report; the prefix is not, and is not included.
            results.append((f"{ENV_SECRET_PATTERN_PREFIX}:{key}", count))
    return results


def sanitize(
    documents: dict[str, str],
    *,
    env_path: Path,
) -> tuple[dict[str, str], SanitizationReport]:
    """Redact and vet every document. Raises :class:`SanitizationError` on failure.

    ``documents`` maps a location label (the snapshot's relative filename) to its
    full text. Redaction runs FIRST, so a forbidden pattern hidden inside a path that
    was about to be redacted is still caught in the redacted output — the text that
    would actually ship is the text that gets vetted.
    """
    env = load_env_secret_prefixes(env_path)

    clean: dict[str, str] = {}
    redactions: list[RedactionRecord] = []
    forbidden_counts: dict[str, int] = {}
    forbidden_locations: dict[str, list[str]] = {}
    bytes_scanned = 0

    for location in sorted(documents):
        text = documents[location]
        redacted, performed = redact(text)
        clean[location] = redacted
        bytes_scanned += len(redacted.encode("utf-8"))
        for name, count, replacement in performed:
            redactions.append(RedactionRecord(
                pattern=name, location=location, count=count, replacement=replacement,
            ))
        for name, count in scan_forbidden(redacted, env):
            forbidden_counts[name] = forbidden_counts.get(name, 0) + count
            forbidden_locations.setdefault(name, []).append(location)

    # Every declared pattern appears in the report, matched or not: a reader must be
    # able to see WHICH checks ran, not just which ones fired.
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
        files_scanned=len(documents),
        bytes_scanned=bytes_scanned,
        redactions=redactions,
        forbidden=records,
        env_checked=env.found,
        env_keys_checked=env.keys if env.found else [],
        env_note=env.note,
    )
    if not report.passed:
        raise SanitizationError(report)
    return clean, report


__all__ = [
    "sanitize",
    "redact",
    "scan_forbidden",
    "load_env_secret_prefixes",
    "SanitizationReport",
    "SanitizationError",
    "RedactionRecord",
    "ForbiddenRecord",
    "REDACTION_PATTERNS",
    "FORBIDDEN_PATTERNS",
    "ENV_SECRET_PATTERN_PREFIX",
]
