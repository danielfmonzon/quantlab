"""Localhost-only uvicorn runner for the Glass Box.

The bind host is the module constant ``HOST`` and is **not** configurable from the
CLI. That is a deliberate safety default, not an oversight:

* the API exposes account equity, positions, orders, and risk state, and has no
  authentication of any kind;
* it is a debugging and transparency surface for the operator of this machine, not
  a service;
* binding 0.0.0.0 without auth would publish an account's holdings to the local
  network on first run.

**Exposing this beyond localhost — and the authentication, TLS, and rate limiting
that would have to come with it — is a later, explicit decision.** Until that
decision is recorded, the only supported reach is a browser on this host, or an SSH
tunnel that a human sets up knowingly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quantlab.constants import PROJECT_ROOT

# Hardcoded. See the module docstring before considering a change.
HOST = "127.0.0.1"
DEFAULT_PORT = 8600

# Where `quantlab glassbox snapshot` writes by default. Inside the frontend's
# `public/` tree so `vite build` copies it into `dist/` untouched.
# Anchored to the repo root — see `snapshot.DEFAULT_REPORT_DIR`. This one is only
# reachable through an interactive `glassbox serve` / `glassbox snapshot --out`, so it
# never ran unattended, but it is the same defect and is fixed with its siblings rather
# than left as the one that got away.
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "frontend" / "public" / "snapshot"


def serve(
    port: int = DEFAULT_PORT,
    *,
    root: Path | None = None,
    runner: Any = None,
) -> int:
    """Run the Glass Box on ``HOST:port``. Returns a process exit code.

    ``runner`` is injectable so the CLI wiring test can assert the bind host
    without starting a real server.
    """
    from quantlab.glassbox.app import create_app
    from quantlab.glassbox.paths import GlassboxPaths

    app = create_app(GlassboxPaths.from_root(root))
    if runner is None:  # pragma: no cover - exercised by running the server for real
        import uvicorn

        runner = uvicorn.run
    runner(app, host=HOST, port=port, log_level="info")
    return 0


__all__ = ["serve", "HOST", "DEFAULT_PORT", "DEFAULT_SNAPSHOT_DIR"]
