"""Persistent kill-switch state at ``data/risk_state.json``.

Writes are atomic (temp file + ``os.replace``) so a crash mid-write cannot
corrupt the live state — the previous good file remains until the replace lands.
A KILL sets ``requires_manual_reset=True`` and survives process restarts until an
explicit reset; HALTs auto-clear next session and do not require a manual reset.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from quantlab.constants import PROJECT_ROOT

_DATA_DIR: Path = PROJECT_ROOT / "data"
DEFAULT_STATE_PATH: Path = _DATA_DIR / "risk_state.json"


def risk_state_path_for(label: str, data_dir: Path = _DATA_DIR) -> Path:
    """Per-account kill-switch state path, e.g. ``data/risk_state_trend.json``.

    Each account's runner reads and writes ONLY its own label's file, so a KILL in
    one paper account can never halt another.
    """
    return data_dir / f"risk_state_{label}.json"


class RiskState(BaseModel):
    halted: bool = False
    reason: str | None = None
    triggered_at: datetime | None = None
    requires_manual_reset: bool = False


def load_risk_state(path: Path = DEFAULT_STATE_PATH) -> RiskState:
    """Load the persisted state; a missing file means 'not halted'."""
    if not path.exists():
        return RiskState()
    return RiskState.model_validate_json(path.read_text(encoding="utf-8"))


def save_risk_state(state: RiskState, path: Path = DEFAULT_STATE_PATH) -> None:
    """Atomically persist ``state`` (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


def reset_risk_state(path: Path = DEFAULT_STATE_PATH) -> RiskState:
    """Clear any halted state and return what was cleared."""
    cleared = load_risk_state(path)
    save_risk_state(RiskState(), path)
    return cleared


__all__ = [
    "RiskState",
    "DEFAULT_STATE_PATH",
    "risk_state_path_for",
    "load_risk_state",
    "save_risk_state",
    "reset_risk_state",
]
