"""Capture every Glass Box endpoint to static JSON for public hosting.

The public site is a *snapshot* of this system, not a live window onto it. That is a
deliberate architectural split: the operational dashboard reads the API on localhost,
while the public build reads flat files captured at a known instant. Nothing public
ever touches the machine that trades.

HOW IT RUNS. In-process, via Starlette's ``TestClient`` — no server, no port, no
network. The routes are enumerated from the app itself rather than listed here, so a
new endpoint is captured automatically and cannot be silently omitted; parameterised
routes are expanded over the real ids on disk.

SANITIZATION IS A GATE, NOT A STEP. Every byte is redacted and vetted in memory
BEFORE anything is written. If a forbidden pattern is found, nothing is written at
all — not even the files that were clean. A partially-written snapshot is worse than
none, because it looks finished.

LOOKUP KEYS. Snapshot files are addressed by :func:`canonical_key`, which the
frontend mirrors exactly. ``limit`` is excluded from the key on purpose: snapshots
are captured at full depth, so a request for 50 rows is served the complete capture
rather than missing the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from quantlab.config import APPROVED_STRATEGIES
from quantlab.glassbox import readers
from quantlab.glassbox.app import create_app
from quantlab.glassbox.paths import GlassboxPaths
from quantlab.glassbox.sanitize import SanitizationReport, sanitize
from quantlab.version import VERSION, git_short_hash

# Capture depth per paginated endpoint. These MUST NOT exceed each endpoint's declared
# `le` ceiling: FastAPI rejects an over-limit query with 422, and the snapshot would
# then contain a validation-error body that looks like data. That is exactly what
# happened on the first run of this pipeline, which is why `capture` now also refuses
# any non-200 response rather than trusting these numbers to stay correct.
DEPTH_BY_PATH: dict[str, int] = {
    "/api/runs": 1000,      # app.py: Query(default=50, ge=1, le=1000)
    "/api/timeline": 5000,  # app.py: Query(default=500, ge=1, le=5000)
}
# Fallback for a future paginated endpoint whose ceiling is not yet recorded here.
DEFAULT_DEPTH = 1000


def depth_for(path: str) -> int:
    return DEPTH_BY_PATH.get(path, DEFAULT_DEPTH)

MANIFEST_NAME = "manifest.json"
REPORT_NAME = "sanitization-report.txt"

# Query parameters that do not participate in snapshot addressing (see module docstring).
_KEY_EXCLUDED_PARAMS = frozenset({"limit"})


def canonical_key(path: str, params: dict[str, str] | None = None) -> str:
    """The lookup key for a request. Mirrored verbatim in ``frontend/src/lib/snapshot.ts``.

    Query parameters are sorted so key construction is order-independent, and
    ``limit`` is dropped because captures are full-depth.
    """
    kept = {
        k: v
        for k, v in (params or {}).items()
        if k not in _KEY_EXCLUDED_PARAMS and v != ""
    }
    if not kept:
        return path
    query = "&".join(f"{k}={kept[k]}" for k in sorted(kept))
    return f"{path}?{query}"


def _file_name_for(key: str) -> str:
    """A filesystem-safe, deterministic filename for a lookup key."""
    slug = (
        key.lstrip("/")
        .replace("/", "-")
        .replace("?", "--")
        .replace("&", "--")
        .replace("=", "-")
    )
    safe = "".join(ch if (ch.isalnum() or ch in "-._") else "_" for ch in slug)
    return f"{safe}.json"


class SnapshotCaptureError(RuntimeError):
    """An endpoint returned a non-200 status. Nothing is written."""


@dataclass(frozen=True)
class Request:
    """One endpoint capture to perform."""

    path: str
    params: dict[str, str]

    @property
    def url(self) -> str:
        if not self.params:
            return self.path
        query = "&".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"{self.path}?{query}"

    @property
    def key(self) -> str:
        return canonical_key(self.path, self.params)

    @property
    def file_name(self) -> str:
        return _file_name_for(self.key)


class ManifestEntry(BaseModel):
    key: str
    file: str
    path: str
    params: dict[str, str] = {}
    status: int
    bytes: int


class Manifest(BaseModel):
    generated_at: str
    git_commit: str
    quantlab_version: str
    endpoints: list[ManifestEntry] = []
    # Recorded so the public build can state what it is without a second fetch.
    endpoint_count: int = 0
    note: str = (
        "Static capture of a localhost-only read-only API. Every figure was read from "
        "an artifact this system wrote. Refreshed manually."
    )


class SnapshotResult(BaseModel):
    manifest: Manifest
    report: SanitizationReport
    out_dir: str
    files_written: list[str] = []


def _api_get_paths(app: Any) -> list[str]:
    """Every GET path the app exposes under ``/api``, read from the app itself."""
    paths: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not path.startswith("/api"):
            continue
        if "GET" not in methods:
            continue
        paths.append(path)
    return sorted(set(paths))


def plan_requests(paths_on_disk: GlassboxPaths, app: Any) -> list[Request]:
    """Expand the app's route table into concrete requests to capture.

    Parameterised routes are expanded over the ids that actually exist; label-filtered
    routes are captured unfiltered AND once per approved account, because the frontend
    requests both shapes.
    """
    run_ids = [rid for rid, _ in readers.read_runs(paths_on_disk, None, None)]
    requests: list[Request] = []

    for path in _api_get_paths(app):
        if "{run_id}" in path:
            for run_id in run_ids:
                requests.append(Request(path.replace("{run_id}", run_id), {}))
            continue
        if "{" in path:  # an unrecognised parameter: skip rather than guess
            continue

        if path == "/api/runs":
            depth = str(depth_for(path))
            requests.append(Request(path, {"limit": depth}))
            for label in APPROVED_STRATEGIES:
                requests.append(Request(path, {"label": label, "limit": depth}))
        elif path in {"/api/divergence", "/api/equity"}:
            requests.append(Request(path, {}))
            for label in APPROVED_STRATEGIES:
                requests.append(Request(path, {"label": label}))
        elif path == "/api/timeline":
            requests.append(Request(path, {"limit": str(depth_for(path))}))
        else:
            requests.append(Request(path, {}))

    # Deduplicate by lookup key, preserving order.
    seen: set[str] = set()
    unique: list[Request] = []
    for request in requests:
        if request.key in seen:
            continue
        seen.add(request.key)
        unique.append(request)
    return unique


def capture(
    paths_on_disk: GlassboxPaths | None = None,
    *,
    env_path: Path | None = None,
) -> tuple[dict[str, str], Manifest, SanitizationReport]:
    """Capture and sanitize every endpoint IN MEMORY. Writes nothing.

    Raises :class:`~quantlab.glassbox.sanitize.SanitizationError` if any forbidden
    pattern is present, before any file is created.
    """
    from starlette.testclient import TestClient

    p = paths_on_disk if paths_on_disk is not None else GlassboxPaths.from_root()
    app = create_app(p)
    requests = plan_requests(p, app)

    documents: dict[str, str] = {}
    entries: list[ManifestEntry] = []

    bad: list[str] = []
    with TestClient(app) as client:
        for request in requests:
            response = client.get(request.url)
            if response.status_code != 200:
                bad.append(f"{request.url} -> {response.status_code}")
                continue
            # Pretty-printed so a curious reader can read the raw file directly; the
            # public site is about being checkable.
            body = json.dumps(response.json(), indent=2, sort_keys=False)
            documents[request.file_name] = body
            entries.append(ManifestEntry(
                key=request.key, file=request.file_name, path=request.path,
                params={k: v for k, v in request.params.items()
                        if k not in _KEY_EXCLUDED_PARAMS},
                status=response.status_code, bytes=len(body.encode("utf-8")),
            ))

    if bad:
        # A validation-error body serialises to JSON and would sit in the snapshot
        # looking like data. Refuse rather than publish it.
        raise SnapshotCaptureError(
            "endpoint(s) did not return 200; snapshot aborted:\n  "
            + "\n  ".join(bad)
        )

    manifest = Manifest(
        generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        git_commit=git_short_hash() or "unknown",
        quantlab_version=VERSION,
        endpoints=entries,
        endpoint_count=len(entries),
    )
    documents[MANIFEST_NAME] = json.dumps(manifest.model_dump(mode="json"), indent=2)

    resolved_env = env_path if env_path is not None else p.project_root / ".env"
    clean, report = sanitize(documents, env_path=resolved_env)
    return clean, manifest, report


def write_snapshot(
    out_dir: Path,
    paths_on_disk: GlassboxPaths | None = None,
    *,
    env_path: Path | None = None,
) -> SnapshotResult:
    """Capture, sanitize, then write. Nothing is written unless the gate passes."""
    clean, manifest, report = capture(paths_on_disk, env_path=env_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    # Remove stale captures so a renamed or dropped endpoint cannot linger and be
    # served as if it were current.
    for existing in out_dir.glob("*.json"):
        existing.unlink()
    stale_report = out_dir / REPORT_NAME
    if stale_report.exists():
        stale_report.unlink()

    written: list[str] = []
    for name in sorted(clean):
        (out_dir / name).write_text(clean[name], encoding="utf-8")
        written.append(name)
    (out_dir / REPORT_NAME).write_text(report.render() + "\n", encoding="utf-8")

    return SnapshotResult(
        manifest=manifest, report=report, out_dir=str(out_dir), files_written=written,
    )


__all__ = [
    "canonical_key",
    "plan_requests",
    "capture",
    "write_snapshot",
    "Manifest",
    "ManifestEntry",
    "SnapshotResult",
    "Request",
    "DEPTH_BY_PATH",
    "depth_for",
    "SnapshotCaptureError",
    "MANIFEST_NAME",
    "REPORT_NAME",
]
