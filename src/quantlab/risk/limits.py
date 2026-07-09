"""Risk limits: defaults, YAML overrides, and validation."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

from quantlab.constants import PROJECT_ROOT

RISK_YAML: Path = PROJECT_ROOT / "config" / "risk.yaml"

# Fraction fields that must lie in (0, 1].
_FRACTION_FIELDS = (
    "max_position_weight",
    "max_gross_exposure",
    "max_daily_loss",
    "max_weekly_loss",
    "max_drawdown_kill",
)


class RiskLimits(BaseModel):
    """Risk thresholds. Loss/exposure fields are fractions in (0, 1]."""

    max_position_weight: float = 1.00
    max_gross_exposure: float = 1.00
    max_daily_loss: float = 0.03
    max_weekly_loss: float = 0.08
    max_drawdown_kill: float = 0.25
    staleness_max_sessions: int = 1

    @model_validator(mode="after")
    def _validate(self) -> RiskLimits:
        for name in _FRACTION_FIELDS:
            value = getattr(self, name)
            if not (0.0 < value <= 1.0):
                raise ValueError(f"{name}={value} must be in (0, 1]")
        if self.staleness_max_sessions < 0:
            raise ValueError("staleness_max_sessions must be >= 0")
        if not (self.max_daily_loss < self.max_weekly_loss < self.max_drawdown_kill):
            raise ValueError(
                "require max_daily_loss < max_weekly_loss < max_drawdown_kill; got "
                f"{self.max_daily_loss} < {self.max_weekly_loss} < {self.max_drawdown_kill}"
            )
        return self


def load_risk_limits(path: Path = RISK_YAML) -> RiskLimits:
    """Load limits from ``config/risk.yaml``; fall back to defaults if absent."""
    if not path.exists():
        return RiskLimits()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return RiskLimits(**data)


__all__ = ["RiskLimits", "load_risk_limits", "RISK_YAML"]
