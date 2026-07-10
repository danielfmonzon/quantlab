"""Build version + git provenance, so every generated report is traceable.

``version_string()`` pairs the release version (:data:`VERSION`, defined in the
package ``__init__``) with the current git short hash, e.g. ``1.0.0+g1a2b3c4``.
When git is unavailable (no repo, git not installed) it degrades cleanly to the
bare version. Report headers embed this string so any digest or weekly review can
be tied back to the exact commit that produced it.
"""

from __future__ import annotations

import subprocess

from quantlab import __version__
from quantlab.constants import PROJECT_ROOT

VERSION: str = __version__


def git_short_hash() -> str | None:
    """The repo's current short commit hash, or ``None`` if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def version_string() -> str:
    """``VERSION`` annotated with the git short hash when one is resolvable."""
    short = git_short_hash()
    return f"{VERSION}+g{short}" if short else VERSION


__all__ = ["VERSION", "git_short_hash", "version_string"]
