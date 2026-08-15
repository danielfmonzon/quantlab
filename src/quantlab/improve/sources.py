"""The only things `propose` is allowed to read.

`propose` is an ANALYSIS command. It reads artifacts this system produced about itself
and writes a document; it never reads source code and never edits anything. The allowlist
is here, in one place, for the same reason `GlassboxPaths` exists: a read-only surface
that is auditable at a glance is one you can actually reason about.

WHY AN ALLOWLIST AND NOT A DENYLIST. The forbidden-path firewall governs what a proposal
may CHANGE. This governs what the analysis may SEE, and the two want opposite defaults.
Change is denied by exception because most of the tree is safe to edit. Reading is
allowed by exception because the point of the exercise is that observations trace to
published artifacts — a proposal justified by something in the source tree is a proposal
justified by reading the implementation, which is how you end up "fixing" a measurement
to agree with the code rather than the other way round.

Every source here is an artifact the system emitted about its own behaviour, or a dated
human ruling. That is the entire evidence base.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quantlab.constants import PROJECT_ROOT


@dataclass(frozen=True)
class Source:
    """One allowed evidence location."""

    name: str
    path: Path
    what: str
    # A directory of artifacts, or a single file.
    is_dir: bool = True

    @property
    def rel(self) -> str:
        try:
            return self.path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return self.path.as_posix()

    def exists(self) -> bool:
        return self.path.exists()

    def inventory(self) -> list[Path]:
        """Concrete files available under this source, newest last. Never recurses into
        anything unexpected — a directory source lists its own files only."""
        if not self.exists():
            return []
        if not self.is_dir:
            return [self.path]
        return sorted(p for p in self.path.iterdir() if p.is_file())


def allowed_sources() -> tuple[Source, ...]:
    """The complete read set, resolved against the repo root (never the CWD)."""
    r = PROJECT_ROOT
    return (
        Source("weekly", r / "reports" / "weekly", "weekly review markdown + json"),
        Source("digests", r / "reports" / "digests", "daily paper digests"),
        Source("runs", r / "reports" / "paper", "per-run paper reports"),
        Source("alerts", r / "reports" / "alerts" / "alerts.jsonl",
               "the alert stream", is_dir=False),
        Source("ci", r / ".github" / "workflows", "CI workflow definition + status"),
        Source("site", r / "reports" / "glassbox",
               "Glass Box / Lighthouse / site artifacts"),
        Source("decisions", r / "docs" / "decisions.md",
               "the dated decision log", is_dir=False),
        Source("proposals", r / "docs" / "proposals",
               "previously written proposals (so numbering and duplication are visible)"),
    )


class SourceViolation(RuntimeError):
    """An evidence path was cited that is outside the allowed read set."""


def assert_allowed(path: str | Path) -> Path:
    """Resolve an evidence path and prove it lies inside an allowed source.

    Raises :class:`SourceViolation` otherwise. Called on every `--evidence` argument, so
    a proposal cannot cite the source tree as its justification.
    """
    p = Path(path)
    resolved = (p if p.is_absolute() else PROJECT_ROOT / p).resolve()
    for source in allowed_sources():
        root = source.path.resolve()
        if resolved == root or (source.is_dir and resolved.is_relative_to(root)):
            return resolved
    permitted = ", ".join(s.rel for s in allowed_sources())
    raise SourceViolation(
        f"evidence path is outside the allowed read set: {path}\n"
        f"  `propose` may read ONLY: {permitted}\n"
        f"  Source code is deliberately not readable here — an observation must trace "
        f"to an artifact this system published about itself, not to the implementation."
    )


def render_inventory() -> str:
    """What the analysis actually had available, including what was missing.

    Absent sources are reported, not skipped. A proposal written in a week where the
    Lighthouse artifacts were never produced should say so rather than quietly narrow
    its evidence base.
    """
    lines = ["EVIDENCE SOURCES READ", "-" * 72]
    for source in allowed_sources():
        if not source.exists():
            lines.append(f"  {source.name:<10} {source.rel:<34} ABSENT — not produced yet")
            continue
        files = source.inventory()
        count = f"{len(files)} file(s)" if source.is_dir else "present"
        lines.append(f"  {source.name:<10} {source.rel:<34} {count}  ({source.what})")
    return "\n".join(lines)


__all__ = [
    "Source",
    "SourceViolation",
    "allowed_sources",
    "assert_allowed",
    "render_inventory",
]
