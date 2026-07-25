"""Tolerant readers for every artifact the Glass Box surfaces.

Two rules throughout:

* **Absence is a valid state.** A fresh clone has no reports and no parquet files;
  every reader returns an empty collection or None rather than raising, so the API
  answers 200 with an explicit empty model instead of 500.
* **Corruption is a valid state too.** These files are written by scheduled jobs
  that can be killed mid-write. A malformed JSON line or a truncated parquet is
  skipped, never propagated as a server error.

Read-only by construction: this module opens files for reading only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quantlab.glassbox.paths import GlassboxPaths

# --------------------------------------------------------------------------- #
# Paper run reports                                                           #
# --------------------------------------------------------------------------- #

_RUN_PREFIX = "run_"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def run_id_for(path: Path) -> str:
    """The stable, URL-safe id of a run report: its filename stem."""
    return path.stem


def _run_sort_key(path: Path) -> tuple[str, str]:
    """Sort a run report by its embedded UTC stamp, then its name.

    Report names are ``run_{label}_{stamp}.json``. Sorting on the WHOLE name would
    sort by label first and only then by time — ``run_voltarget_…`` would outrank a
    later ``run_crypto_voltarget_…`` purely alphabetically. Splitting the stamp off
    the end makes the ordering chronological across accounts; the name is kept as a
    tiebreak so equal stamps stay deterministic, and an unexpected name shape
    degrades to an empty stamp rather than raising.
    """
    stem = path.stem
    stamp = stem.rsplit("_", 1)[-1] if "_" in stem else ""
    return (stamp, stem)


def list_run_paths(paths: GlassboxPaths, label: str | None = None) -> list[Path]:
    """Run-report paths, NEWEST FIRST (chronologically, across all accounts)."""
    if not paths.paper_dir.exists():
        return []
    pattern = f"{_RUN_PREFIX}{label}_*.json" if label else f"{_RUN_PREFIX}*.json"
    try:
        return sorted(paths.paper_dir.glob(pattern), key=_run_sort_key, reverse=True)
    except OSError:
        return []


def read_runs(
    paths: GlassboxPaths, label: str | None = None, limit: int | None = None
) -> list[tuple[str, dict[str, Any]]]:
    """``(run_id, payload)`` pairs, newest first, skipping unreadable files.

    ``limit`` is applied AFTER unreadable files are skipped, so a corrupt report
    never silently shortens the page.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for path in list_run_paths(paths, label):
        payload = _load_json(path)
        if payload is None:
            continue
        # A glob on `run_{label}_*` can also match a longer label (`run_trend_*`
        # never matches `run_crypto_trend_*`, but the reverse containment is worth
        # guarding): trust the report's own strategy field when it has one.
        if label is not None:
            recorded = payload.get("strategy")
            if isinstance(recorded, str) and recorded and recorded != label:
                continue
        out.append((run_id_for(path), payload))
        if limit is not None and len(out) >= limit:
            break
    return out


def read_run(paths: GlassboxPaths, run_id: str) -> dict[str, Any] | None:
    """One run report by id, or None if absent/unreadable.

    ``run_id`` is resolved against the directory listing rather than joined onto a
    path, so a traversal attempt (``../../etc/passwd``) cannot escape the reports
    directory — it simply fails to match.
    """
    for path in list_run_paths(paths):
        if run_id_for(path) == run_id:
            return _load_json(path)
    return None


# --------------------------------------------------------------------------- #
# Weekly reviews                                                              #
# --------------------------------------------------------------------------- #

def read_weekly_reviews(paths: GlassboxPaths) -> list[dict[str, Any]]:
    """Every ``week_*.json``, OLDEST FIRST (a series reads forward in time)."""
    if not paths.weekly_dir.exists():
        return []
    try:
        candidates = sorted(paths.weekly_dir.glob("week_*.json"), key=lambda p: p.name)
    except OSError:
        return []
    out = []
    for path in candidates:
        payload = _load_json(path)
        if payload is not None:
            out.append(payload)
    return out


def latest_weekly_review(paths: GlassboxPaths) -> dict[str, Any] | None:
    reviews = read_weekly_reviews(paths)
    return reviews[-1] if reviews else None


# --------------------------------------------------------------------------- #
# Digests                                                                     #
# --------------------------------------------------------------------------- #

def read_digests(paths: GlassboxPaths) -> list[dict[str, Any]]:
    """Every ``digest_*.json``, oldest first."""
    if not paths.digests_dir.exists():
        return []
    try:
        candidates = sorted(paths.digests_dir.glob("digest_*.json"), key=lambda p: p.name)
    except OSError:
        return []
    return [p for p in (_load_json(c) for c in candidates) if p is not None]


# --------------------------------------------------------------------------- #
# Alerts                                                                      #
# --------------------------------------------------------------------------- #

def read_alerts(paths: GlassboxPaths) -> list[dict[str, Any]]:
    """Alert records from the JSONL log, in file order; bad lines skipped."""
    path = paths.alerts_path
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


# --------------------------------------------------------------------------- #
# Equity history                                                              #
# --------------------------------------------------------------------------- #

def read_equity_history(paths: GlassboxPaths, label: str) -> list[tuple[datetime, float]]:
    """``(timestamp, equity)`` points for one account, oldest first.

    Returns ``[]`` for a missing, empty, or unreadable parquet file.
    """
    path = paths.equity_history_path(label)
    if not path.exists():
        return []
    try:
        frame = pd.read_parquet(path)
    except Exception:  # noqa: BLE001 - a truncated parquet is an empty state, not a 500
        return []
    if frame.empty or not {"timestamp", "equity"}.issubset(frame.columns):
        return []
    frame = frame.sort_values("timestamp")
    out: list[tuple[datetime, float]] = []
    for ts, equity in zip(frame["timestamp"], frame["equity"], strict=False):
        stamp = pd.Timestamp(ts)
        if pd.isna(stamp) or pd.isna(equity):
            continue
        out.append((stamp.to_pydatetime(), float(equity)))
    return out


# --------------------------------------------------------------------------- #
# Risk state + limits                                                         #
# --------------------------------------------------------------------------- #

def read_risk_state(paths: GlassboxPaths, label: str) -> dict[str, Any]:
    """The account's kill-switch state; a missing file means 'not halted'."""
    payload = _load_json(paths.risk_state_path(label))
    if payload is None:
        return {"halted": False, "reason": None, "triggered_at": None,
                "requires_manual_reset": False}
    return payload


def read_risk_limits(paths: GlassboxPaths, asset_class: str) -> dict[str, Any]:
    """Limits from the yaml that governs ``asset_class``, or ``{}`` if absent.

    Mirrors the runner's selection (crypto accounts read ``crypto_risk.yaml``) by
    reading the same files, without importing the trading path's loader — the
    Glass Box reports what the config SAYS, and must not fail because a config
    would not validate.
    """
    path = paths.crypto_risk_yaml if asset_class == "crypto" else paths.risk_yaml
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def parse_timestamp(raw: object) -> datetime | None:
    """Best-effort ISO-8601 parse, tolerating a trailing ``Z``.

    Returns tz-aware UTC so mixed naive/aware artifact timestamps stay sortable.
    """
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


__all__ = [
    "run_id_for",
    "list_run_paths",
    "read_runs",
    "read_run",
    "read_weekly_reviews",
    "latest_weekly_review",
    "read_digests",
    "read_alerts",
    "read_equity_history",
    "read_risk_state",
    "read_risk_limits",
    "parse_timestamp",
]
