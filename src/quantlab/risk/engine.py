"""Risk engine: weight containment and portfolio/data decisions.

The engine never raises on limit violations — it corrects (clamps/rescales) and
records. Raising on malformed input is the backtest engine's job; the risk
engine's job is containment.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

from quantlab.data.health import HealthReport
from quantlab.risk.limits import RiskLimits

# Action strings.
ALLOW = "ALLOW"
HALT_DAILY_LOSS = "HALT_DAILY_LOSS"
HALT_WEEKLY_LOSS = "HALT_WEEKLY_LOSS"
KILL_DRAWDOWN = "KILL_DRAWDOWN"
FREEZE_STALE_DATA = "FREEZE_STALE_DATA"

# Precedence when combining decisions: KILL > HALT_* > FREEZE > ALLOW.
_PRECEDENCE = {
    ALLOW: 0,
    FREEZE_STALE_DATA: 1,
    HALT_DAILY_LOSS: 2,
    HALT_WEEKLY_LOSS: 2,
    KILL_DRAWDOWN: 3,
}


class WeightDecision(BaseModel):
    adjusted_weights: dict[str, float]
    adjustments: list[str]


class PortfolioDecision(BaseModel):
    action: str
    reason: str
    daily_return: float | None = None
    weekly_return: float | None = None
    drawdown: float | None = None


class DataDecision(BaseModel):
    action: str
    reason: str


class CombinedDecision(BaseModel):
    action: str
    reason: str


class RiskEngine:
    """Stateless evaluator over weights and portfolio/data state."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    # -- Weight containment --------------------------------------------------

    def check_weights(self, weights: dict[str, float]) -> WeightDecision:
        """Clamp per-symbol weights and rescale gross; record every adjustment."""
        adjusted = dict(weights)
        adjustments: list[str] = []

        cap = self.limits.max_position_weight
        for sym, w in list(adjusted.items()):
            if w > cap:
                adjustments.append(f"clamp {sym} {w:.4f}->{cap:.4f} (max_position_weight)")
                adjusted[sym] = cap

        gross = sum(adjusted.values())
        if gross > self.limits.max_gross_exposure and gross > 0.0:
            scale = self.limits.max_gross_exposure / gross
            for sym in adjusted:
                adjusted[sym] *= scale
            adjustments.append(
                f"rescale gross {gross:.4f}->{self.limits.max_gross_exposure:.4f}"
            )

        return WeightDecision(adjusted_weights=adjusted, adjustments=adjustments)

    # -- Portfolio evaluation ------------------------------------------------

    @staticmethod
    def _locate(equity: pd.Series, now_index: object) -> int:
        try:
            return int(equity.index.get_loc(now_index))
        except KeyError:
            return int(now_index)  # type: ignore[call-overload]

    def evaluate_portfolio(self, equity: pd.Series, now_index: object) -> PortfolioDecision:
        """Evaluate loss/drawdown limits at ``now_index`` (a label or position)."""
        t = self._locate(equity, now_index)
        val = float(equity.iloc[t])

        daily = float(val / equity.iloc[t - 1] - 1.0) if t >= 1 else None
        weekly = float(val / equity.iloc[t - 5] - 1.0) if t >= 5 else None
        peak = float(equity.iloc[: t + 1].max())  # running peak, not global
        drawdown = val / peak - 1.0

        lim = self.limits
        # Strict comparison: exactly at threshold does NOT trigger.
        if drawdown < -lim.max_drawdown_kill:
            return PortfolioDecision(
                action=KILL_DRAWDOWN,
                reason=f"drawdown {drawdown:.4f} beyond kill -{lim.max_drawdown_kill}",
                daily_return=daily, weekly_return=weekly, drawdown=drawdown,
            )
        if weekly is not None and weekly < -lim.max_weekly_loss:
            return PortfolioDecision(
                action=HALT_WEEKLY_LOSS,
                reason=f"weekly return {weekly:.4f} beyond -{lim.max_weekly_loss}",
                daily_return=daily, weekly_return=weekly, drawdown=drawdown,
            )
        if daily is not None and daily < -lim.max_daily_loss:
            return PortfolioDecision(
                action=HALT_DAILY_LOSS,
                reason=f"daily return {daily:.4f} beyond -{lim.max_daily_loss}",
                daily_return=daily, weekly_return=weekly, drawdown=drawdown,
            )
        return PortfolioDecision(
            action=ALLOW, reason="within portfolio limits",
            daily_return=daily, weekly_return=weekly, drawdown=drawdown,
        )

    # -- Data evaluation -----------------------------------------------------

    def evaluate_data(self, health: HealthReport) -> DataDecision:
        stale = [
            sh.symbol
            for sh in health.symbols
            if sh.has_data and sh.staleness_sessions > self.limits.staleness_max_sessions
        ]
        if stale or health.blocking_reasons:
            reasons: list[str] = []
            if stale:
                reasons.append("stale: " + ", ".join(stale))
            reasons.extend(health.blocking_reasons)
            return DataDecision(action=FREEZE_STALE_DATA, reason="; ".join(reasons))
        return DataDecision(action=ALLOW, reason="data fresh")

    # -- Combination ---------------------------------------------------------

    def combine(self, portfolio: PortfolioDecision, data: DataDecision) -> CombinedDecision:
        """Return the highest-precedence decision: KILL > HALT_* > FREEZE > ALLOW."""
        best = max(
            ((portfolio.action, portfolio.reason), (data.action, data.reason)),
            key=lambda pair: _PRECEDENCE[pair[0]],
        )
        return CombinedDecision(action=best[0], reason=best[1])


__all__ = [
    "RiskEngine",
    "WeightDecision",
    "PortfolioDecision",
    "DataDecision",
    "CombinedDecision",
    "ALLOW",
    "HALT_DAILY_LOSS",
    "HALT_WEEKLY_LOSS",
    "KILL_DRAWDOWN",
    "FREEZE_STALE_DATA",
]
