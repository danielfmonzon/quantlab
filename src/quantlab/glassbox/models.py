"""Response models for the Glass Box API.

Every endpoint returns a model, and every collection field defaults to empty, so
an absent artifact tree produces an explicit, well-typed empty answer instead of a
null or a 500. Optional scalars are ``None`` where a value genuinely does not exist
yet — an account with no snapshots has no latest equity, and saying so is more
honest than reporting 0.0.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

# ``DecisionEntry`` exposes a field literally named ``date``, which shadows the
# imported type inside that class body and breaks annotation evaluation. Alias.
_Date = date

# --------------------------------------------------------------------------- #
# Shared                                                                      #
# --------------------------------------------------------------------------- #


class RiskStateView(BaseModel):
    halted: bool = False
    reason: str | None = None
    triggered_at: datetime | None = None
    requires_manual_reset: bool = False


class ClockView(BaseModel):
    """One asset class's 90-day readiness clock, as the latest weekly review saw it."""

    asset_class: str
    paper_start_date: date | None = None
    calendar_days_elapsed: int = 0
    target_days: int = 90
    pct_complete: float = 0.0
    start_note: str | None = None
    blockers: list[str] = []


# --------------------------------------------------------------------------- #
# /api/overview                                                               #
# --------------------------------------------------------------------------- #


class AccountOverview(BaseModel):
    label: str
    asset_class: str
    latest_equity: float | None = None
    latest_snapshot_at: datetime | None = None
    latest_snapshot_provenance: str | None = None
    snapshot_count: int = 0
    risk: RiskStateView = RiskStateView()
    validation_tier: str
    validation_tier_rationale: str
    clock: ClockView | None = None


class OverviewResponse(BaseModel):
    generated_at: datetime
    accounts: list[AccountOverview] = []
    week_ending: date | None = None
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/runs                                                                   #
# --------------------------------------------------------------------------- #


class StageView(BaseModel):
    stage: str
    ok: bool
    detail: str | None = None


class OrderView(BaseModel):
    symbol: str | None = None
    side: str | None = None
    notional: float | None = None
    status: str | None = None
    client_order_id: str | None = None
    submitted_at: datetime | None = None
    was_duplicate: bool = False


class IntentView(BaseModel):
    symbol: str | None = None
    side: str | None = None
    notional: float | None = None
    current_w: float | None = None
    target_w: float | None = None


class RunView(BaseModel):
    run_id: str
    strategy: str | None = None
    timestamp: datetime | None = None
    dry_run: bool | None = None
    aborted: bool = False
    abort_stage: str | None = None
    abort_reason: str | None = None
    equity: float | None = None
    target_weights: dict[str, float] = {}
    no_trades: bool | None = None
    est_turnover: float | None = None
    min_trade_frac: float | None = None
    stages: list[StageView] = []
    intents: list[IntentView] = []
    submitted_orders: list[OrderView] = []


class RunsResponse(BaseModel):
    count: int = 0
    label: str | None = None
    runs: list[RunView] = []
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/divergence                                                             #
# --------------------------------------------------------------------------- #


class WeekDivergence(BaseModel):
    week_ending: date | None = None
    label: str
    asset_class: str | None = None
    paper_week_return: float | None = None
    shadow_week_return: float | None = None
    divergence_bps: float | None = None
    cumulative_divergence_bps: float | None = None
    verdict: str | None = None
    threshold_bps: float | None = None
    excluded_tail_days: list[date] = []
    window_start: date | None = None
    window_end: date | None = None
    structural_note: str | None = None


class WeekCorrection(BaseModel):
    """A published figure and its later correction, surfaced side by side.

    Neither number is recomputed here; both are quoted, and ``reference`` points at
    the decisions-log entry that ruled the correction.
    """

    week_ending: str
    label: str
    published_divergence_bps: float | None = None
    published_verdict: str | None = None
    corrected_divergence_bps: float | None = None
    corrected_verdict: str | None = None
    corrected_window: str | None = None
    cause: str | None = None
    reference: str


class DivergenceResponse(BaseModel):
    label: str | None = None
    weeks: list[WeekDivergence] = []
    corrections: list[WeekCorrection] = []
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/equity                                                                 #
# --------------------------------------------------------------------------- #


class EquityPoint(BaseModel):
    timestamp: datetime
    equity: float
    provenance: str
    provenance_rationale: str


class EquitySeries(BaseModel):
    label: str
    asset_class: str
    points: list[EquityPoint] = []
    provenance_counts: dict[str, int] = {}


class EquityResponse(BaseModel):
    label: str | None = None
    series: list[EquitySeries] = []
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/risk                                                                   #
# --------------------------------------------------------------------------- #


class LimitsView(BaseModel):
    max_position_weight: float | None = None
    max_gross_exposure: float | None = None
    max_daily_loss: float | None = None
    max_weekly_loss: float | None = None
    max_drawdown_kill: float | None = None
    staleness_max_sessions: int | None = None
    weekly_divergence_alert_bps: float | None = None


class AccountRisk(BaseModel):
    label: str
    asset_class: str
    limits: LimitsView = LimitsView()
    limits_source: str
    peak_equity: float | None = None
    latest_equity: float | None = None
    current_drawdown: float | None = None
    drawdown_kill_limit: float | None = None
    # Fractional headroom before the kill threshold trips, e.g. 0.235 == the
    # drawdown could deepen by 23.5 percentage points before a KILL.
    drawdown_headroom: float | None = None
    kill_switch: RiskStateView = RiskStateView()
    note: str | None = None


class RiskResponse(BaseModel):
    accounts: list[AccountRisk] = []
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/timeline                                                               #
# --------------------------------------------------------------------------- #


class TimelineEvent(BaseModel):
    at: datetime | None = None
    kind: str  # order | alert | weekly_verdict | decision
    label: str | None = None
    title: str
    detail: str | None = None
    level: str | None = None


class TimelineResponse(BaseModel):
    count: int = 0
    events: list[TimelineEvent] = []
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/decisions                                                              #
# --------------------------------------------------------------------------- #


class DecisionEntry(BaseModel):
    date: _Date | None = None
    title: str
    body: str


class DecisionsResponse(BaseModel):
    count: int = 0
    entries: list[DecisionEntry] = []
    note: str | None = None


# --------------------------------------------------------------------------- #
# /api/ignored-inputs                                                         #
# --------------------------------------------------------------------------- #


class InputRead(BaseModel):
    name: str
    role: str
    rationale: str


class InputIgnored(BaseModel):
    name: str
    rationale: str


class IgnoredInputsResponse(BaseModel):
    statement: str
    reads: list[InputRead] = []
    ignores: list[InputIgnored] = []


__all__ = [
    "RiskStateView",
    "ClockView",
    "AccountOverview",
    "OverviewResponse",
    "StageView",
    "OrderView",
    "IntentView",
    "RunView",
    "RunsResponse",
    "WeekDivergence",
    "WeekCorrection",
    "DivergenceResponse",
    "EquityPoint",
    "EquitySeries",
    "EquityResponse",
    "LimitsView",
    "AccountRisk",
    "RiskResponse",
    "TimelineEvent",
    "TimelineResponse",
    "DecisionEntry",
    "DecisionsResponse",
    "InputRead",
    "InputIgnored",
    "IgnoredInputsResponse",
]
