"""Parse ``docs/decisions.md`` into structured entries.

The file's convention (see its own header) is ``## YYYY-MM-DD — Title``, newest
first, entries separated by ``---``. The em dash is the real separator in the file;
a plain hyphen is accepted too so a future entry typed with an ASCII dash still
parses rather than silently vanishing.

Anything before the first ``##`` heading is the file's preamble and is not an
entry. A heading whose date does not parse is kept with ``date=None`` rather than
dropped — a malformed entry should be visible, not invisible.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# "## 2026-07-25 — Title text"  /  "## 2026-07-25 - Title text"
_HEADING = re.compile(
    r"^##\s+(?P<date>\d{4}-\d{2}-\d{2})?\s*[—-]?\s*(?P<title>.*?)\s*$"
)


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def parse_decisions(text: str) -> list[dict[str, object]]:
    """Split ``text`` into ``{date, title, body}`` entries, document order preserved."""
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    body: list[str] = []

    for line in text.splitlines():
        match = _HEADING.match(line) if line.startswith("##") else None
        if match is not None and not line.startswith("###"):
            if current is not None:
                current["body"] = _clean_body(body)
                entries.append(current)
            current = {
                "date": _parse_date(match.group("date")),
                "title": match.group("title").strip(),
            }
            body = []
        elif current is not None:
            body.append(line)

    if current is not None:
        current["body"] = _clean_body(body)
        entries.append(current)
    return entries


def _clean_body(lines: list[str]) -> str:
    """Drop the trailing ``---`` separator and surrounding blank lines."""
    out = list(lines)
    while out and not out[-1].strip():
        out.pop()
    if out and out[-1].strip() == "---":
        out.pop()
    while out and not out[-1].strip():
        out.pop()
    while out and not out[0].strip():
        out.pop(0)
    return "\n".join(out)


def read_decisions(path: Path) -> list[dict[str, object]]:
    """Parse the decisions log, or return ``[]`` when the file is absent."""
    if not path.exists():
        return []
    try:
        return parse_decisions(path.read_text(encoding="utf-8"))
    except OSError:
        return []


__all__ = ["parse_decisions", "read_decisions"]
