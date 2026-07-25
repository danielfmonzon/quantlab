"""The Glass Box FastAPI app: a read-only window onto quantlab's own artifacts.

Design constraints, all deliberate:

* **Read-only.** Nothing here opens a file for writing. The app cannot start,
  stop, halt, reset, or trade anything, and it imports nothing from ``broker/``.
* **Absence is a state, not an error.** Every handler tolerates a completely empty
  repo. A fresh clone answers 200 with explicit empty models on every endpoint.
* **No fabrication.** Where the service interprets rather than reports — validation
  tiers, mark provenance, the week 2026-07-24 correction — the interpretation comes
  from documented constants and says so in the payload.

``create_app(paths=...)`` takes its artifact roots as an argument so the suite can
mount the whole API over a fixture tree in ``tmp_path``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from quantlab.config import APPROVED_STRATEGIES, account_asset_class
from quantlab.glassbox import readers
from quantlab.glassbox.constants import (
    DECISIONS_CORRECTION_REF,
    INPUTS_IGNORED,
    INPUTS_READ,
    PROVENANCE_RATIONALE,
    READINESS_TARGET_DAYS,
    TIER_PROBABLE,
    TIER_RATIONALE,
    VALIDATION_TIERS,
    WEEK_CORRECTIONS,
    upgrade_condition,
)
from quantlab.glassbox.decisions import read_decisions
from quantlab.glassbox.models import (
    AccountOverview,
    AccountRisk,
    ClockView,
    DecisionEntry,
    DecisionsResponse,
    DivergenceResponse,
    EquityPoint,
    EquityResponse,
    EquitySeries,
    IgnoredInputsResponse,
    InputIgnored,
    InputRead,
    IntentView,
    LimitsView,
    OrderView,
    OverviewResponse,
    RiskResponse,
    RiskStateView,
    RunsResponse,
    RunView,
    StageView,
    TimelineEvent,
    TimelineResponse,
    WeekCorrection,
    WeekDivergence,
)
from quantlab.glassbox.narrate import RunNarration, narrate_run
from quantlab.glassbox.paths import GlassboxPaths
from quantlab.glassbox.provenance import classify_mark

_IGNORED_INPUTS_STATEMENT = (
    "This system reads settled daily prices and its own account state. It reads no "
    "news, no sentiment, and no opinion — including its own. The list below is "
    "published so a reader can judge what the strategies CANNOT know, rather than "
    "inferring capability from a feature list."
)

_EMPTY_TREE_NOTE = "no artifacts found; this is an empty-state response, not an error"


def _labels(label: str | None) -> list[str]:
    """Requested accounts, restricted to the approved roster."""
    if label is None:
        return list(APPROVED_STRATEGIES)
    return [label] if label in APPROVED_STRATEGIES else []


def _as_float(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _as_list(raw: object) -> list[Any]:
    """A list, or an empty one — artifacts written by a killed job may hold anything."""
    return raw if isinstance(raw, list) else []


def _as_dict(raw: object) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _as_date(raw: object) -> date | None:
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def create_app(paths: GlassboxPaths | None = None) -> FastAPI:
    """Build the app over ``paths`` (defaults to this repo's artifact tree)."""
    p = paths if paths is not None else GlassboxPaths.from_root()

    app = FastAPI(
        title="quantlab Glass Box",
        version="1",
        summary="Read-only transparency API over quantlab's own artifacts.",
        description=(
            "Every response is derived from files on disk that the trading and "
            "reporting paths wrote. This service performs no trading, holds no "
            "credentials, and writes nothing."
        ),
    )
    app.state.glassbox_paths = p

    # ---------------------------------------------------------------- overview
    @app.get("/api/overview", response_model=OverviewResponse)
    def overview() -> OverviewResponse:
        review = readers.latest_weekly_review(p)
        clocks: dict[str, ClockView] = {}
        week_ending: date | None = None
        if review is not None:
            week_ending = _as_date(review.get("week_ending"))
            readiness = _as_dict(review.get("readiness"))
            blockers_all = [str(b) for b in _as_list(readiness.get("blockers"))]
            for entry in _as_list(readiness.get("clocks")):
                if not isinstance(entry, dict):
                    continue
                ac = str(entry.get("asset_class", ""))
                clocks[ac] = ClockView(
                    asset_class=ac,
                    paper_start_date=_as_date(entry.get("paper_start_date")),
                    calendar_days_elapsed=int(entry.get("calendar_days_elapsed") or 0),
                    target_days=int(entry.get("target_days") or 90),
                    pct_complete=float(entry.get("pct_complete") or 0.0),
                    start_note=entry.get("start_note"),
                    blockers=blockers_all,
                )

        accounts: list[AccountOverview] = []
        for label in APPROVED_STRATEGIES:
            asset_class = account_asset_class(label)
            history = readers.read_equity_history(p, label)
            latest_at, latest_eq, prov = None, None, None
            if history:
                latest_at, latest_eq = history[-1]
                prov = classify_mark(latest_at, asset_class)
            tier = VALIDATION_TIERS.get(label, TIER_PROBABLE)
            # A clock is per asset class; every account of that class shares it.
            clock = clocks.get(asset_class)
            if clock is not None:
                clock = clock.model_copy(
                    update={"blockers": [b for b in clock.blockers if b.startswith(label)]}
                )
            accounts.append(AccountOverview(
                label=label, asset_class=asset_class,
                latest_equity=latest_eq, latest_snapshot_at=latest_at,
                latest_snapshot_provenance=prov, snapshot_count=len(history),
                risk=RiskStateView(**readers.read_risk_state(p, label)),
                validation_tier=tier,
                validation_tier_rationale=TIER_RATIONALE.get(tier, ""),
                validation_tier_upgrade_condition=upgrade_condition(
                    asset_class,
                    clock.paper_start_date if clock is not None else None,
                    clock.target_days if clock is not None else READINESS_TARGET_DAYS,
                ),
                clock=clock,
            ))

        note = None if review is not None or any(a.snapshot_count for a in accounts) \
            else _EMPTY_TREE_NOTE
        return OverviewResponse(
            generated_at=datetime.now(UTC), accounts=accounts,
            week_ending=week_ending, note=note,
        )

    # ------------------------------------------------------------------- runs
    @app.get("/api/runs", response_model=RunsResponse)
    def runs(
        label: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=1000),
    ) -> RunsResponse:
        if label is not None and label not in APPROVED_STRATEGIES:
            return RunsResponse(count=0, label=label, runs=[],
                                note=f"unknown account {label!r}; no runs returned")
        views = [_run_view(rid, payload)
                 for rid, payload in readers.read_runs(p, label, limit)]
        return RunsResponse(
            count=len(views), label=label, runs=views,
            note=None if views else _EMPTY_TREE_NOTE,
        )

    @app.get("/api/runs/{run_id}/narrate", response_model=RunNarration)
    def narrate(run_id: str) -> RunNarration:
        report = readers.read_run(p, run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"no run report {run_id!r}")
        return narrate_run(run_id, report)

    # ------------------------------------------------------------- divergence
    @app.get("/api/divergence", response_model=DivergenceResponse)
    def divergence(label: str | None = Query(default=None)) -> DivergenceResponse:
        wanted = _labels(label)
        weeks: list[WeekDivergence] = []
        for review in readers.read_weekly_reviews(p):
            week_ending = _as_date(review.get("week_ending"))
            threshold = _as_float(review.get("divergence_threshold_bps"))
            for acct in _as_list(review.get("accounts")):
                if not isinstance(acct, dict):
                    continue
                acct_label = str(acct.get("label", ""))
                if acct_label not in wanted:
                    continue
                cumulative = _as_dict(acct.get("cumulative"))
                window = _as_dict(acct.get("window"))
                excluded = [d for d in (
                    _as_date(x) for x in _as_list(acct.get("excluded_tail_days"))
                ) if d is not None]
                weeks.append(WeekDivergence(
                    week_ending=week_ending, label=acct_label,
                    asset_class=acct.get("asset_class"),
                    paper_week_return=_as_float(acct.get("paper_week_return")),
                    shadow_week_return=_as_float(acct.get("shadow_week_return")),
                    divergence_bps=_as_float(acct.get("divergence_bps")),
                    cumulative_divergence_bps=_as_float(
                        cumulative.get("cumulative_divergence_bps")),
                    verdict=acct.get("verdict"), threshold_bps=threshold,
                    excluded_tail_days=excluded,
                    window_start=_as_date(window.get("start")),
                    window_end=_as_date(window.get("end")),
                    structural_note=cumulative.get("structural_drift_note"),
                ))

        corrections = [
            WeekCorrection(week_ending=week, label=corrected_label,
                           reference=DECISIONS_CORRECTION_REF,
                           **entry)  # type: ignore[arg-type]
            for week, per_label in WEEK_CORRECTIONS.items()
            for corrected_label, entry in per_label.items()
            if corrected_label in wanted
        ]
        return DivergenceResponse(
            label=label, weeks=weeks, corrections=corrections,
            note=None if weeks else _EMPTY_TREE_NOTE,
        )

    # ----------------------------------------------------------------- equity
    @app.get("/api/equity", response_model=EquityResponse)
    def equity(label: str | None = Query(default=None)) -> EquityResponse:
        series: list[EquitySeries] = []
        for acct_label in _labels(label):
            asset_class = account_asset_class(acct_label)
            points: list[EquityPoint] = []
            counts: dict[str, int] = {}
            for ts, value in readers.read_equity_history(p, acct_label):
                prov = classify_mark(ts, asset_class)
                counts[prov] = counts.get(prov, 0) + 1
                points.append(EquityPoint(
                    timestamp=ts, equity=value, provenance=prov,
                    provenance_rationale=PROVENANCE_RATIONALE.get(prov, ""),
                ))
            series.append(EquitySeries(label=acct_label, asset_class=asset_class,
                                       points=points, provenance_counts=counts))
        return EquityResponse(
            label=label, series=series,
            note=None if any(s.points for s in series) else _EMPTY_TREE_NOTE,
        )

    # ------------------------------------------------------------------- risk
    @app.get("/api/risk", response_model=RiskResponse)
    def risk() -> RiskResponse:
        accounts: list[AccountRisk] = []
        for label in APPROVED_STRATEGIES:
            asset_class = account_asset_class(label)
            raw = readers.read_risk_limits(p, asset_class)
            limits = LimitsView(**{k: v for k, v in raw.items()
                                  if k in LimitsView.model_fields})
            source = (p.crypto_risk_yaml if asset_class == "crypto" else p.risk_yaml)
            history = readers.read_equity_history(p, label)

            peak = latest = drawdown = headroom = None
            note = None
            if history:
                values = [v for _, v in history]
                peak = max(values)
                latest = values[-1]
                drawdown = (latest / peak - 1.0) if peak else None
                if drawdown is not None and limits.max_drawdown_kill is not None:
                    headroom = limits.max_drawdown_kill - abs(drawdown)
            else:
                note = "no equity history yet; drawdown and headroom are unknown"

            accounts.append(AccountRisk(
                label=label, asset_class=asset_class, limits=limits,
                limits_source=source.name if source.exists() else f"{source.name} (absent)",
                peak_equity=peak, latest_equity=latest, current_drawdown=drawdown,
                drawdown_kill_limit=limits.max_drawdown_kill,
                drawdown_headroom=headroom,
                kill_switch=RiskStateView(**readers.read_risk_state(p, label)),
                note=note,
            ))
        return RiskResponse(accounts=accounts)

    # --------------------------------------------------------------- timeline
    @app.get("/api/timeline", response_model=TimelineResponse)
    def timeline(limit: int = Query(default=500, ge=1, le=5000)) -> TimelineResponse:
        events: list[TimelineEvent] = []

        for run_id, report in readers.read_runs(p):
            at = readers.parse_timestamp(report.get("timestamp"))
            label = report.get("strategy")
            for order in _as_list(report.get("submitted_orders")):
                if not isinstance(order, dict):
                    continue
                notional = _as_float(order.get("notional"))
                events.append(TimelineEvent(
                    at=readers.parse_timestamp(order.get("submitted_at")) or at,
                    kind="order", label=label,
                    title=(f"{order.get('side', '?')} {order.get('symbol', '?')}"
                           + (f" ${notional:,.2f}" if notional is not None else "")),
                    detail=f"status={order.get('status', 'unknown')} run={run_id}",
                ))

        for record in readers.read_alerts(p):
            events.append(TimelineEvent(
                at=readers.parse_timestamp(record.get("timestamp")),
                kind="alert", label=record.get("strategy"),
                title=str(record.get("title", "alert")),
                detail=record.get("body"), level=record.get("level"),
            ))

        for review in readers.read_weekly_reviews(p):
            at = readers.parse_timestamp(review.get("generated_at"))
            for acct in _as_list(review.get("accounts")):
                if not isinstance(acct, dict) or acct.get("verdict") is None:
                    continue
                bps = _as_float(acct.get("divergence_bps"))
                events.append(TimelineEvent(
                    at=at, kind="weekly_verdict", label=acct.get("label"),
                    title=f"week {review.get('week_ending')}: "
                          f"{acct.get('label')} {acct.get('verdict')}",
                    detail=None if bps is None else f"divergence {bps:+.0f} bps",
                ))

        for entry in read_decisions(p.decisions_path):
            entry_date = entry.get("date")
            events.append(TimelineEvent(
                at=(datetime.combine(entry_date, datetime.min.time(), tzinfo=UTC)
                    if isinstance(entry_date, date) else None),
                kind="decision", title=str(entry.get("title", "decision")),
                detail="docs/decisions.md",
            ))

        # Undated events sort last; ties keep a deterministic order.
        events.sort(key=lambda e: (e.at is not None, e.at or datetime.min.replace(tzinfo=UTC)),
                    reverse=True)
        trimmed = events[:limit]
        return TimelineResponse(count=len(trimmed), events=trimmed,
                                note=None if trimmed else _EMPTY_TREE_NOTE)

    # -------------------------------------------------------------- decisions
    @app.get("/api/decisions", response_model=DecisionsResponse)
    def decisions() -> DecisionsResponse:
        entries = [
            DecisionEntry(date=e.get("date"), title=str(e.get("title", "")),  # type: ignore[arg-type]
                          body=str(e.get("body", "")))
            for e in read_decisions(p.decisions_path)
        ]
        return DecisionsResponse(count=len(entries), entries=entries,
                                 note=None if entries else _EMPTY_TREE_NOTE)

    # --------------------------------------------------------- ignored inputs
    @app.get("/api/ignored-inputs", response_model=IgnoredInputsResponse)
    def ignored_inputs() -> IgnoredInputsResponse:
        return IgnoredInputsResponse(
            statement=_IGNORED_INPUTS_STATEMENT,
            reads=[InputRead(**x) for x in INPUTS_READ],
            ignores=[InputIgnored(**x) for x in INPUTS_IGNORED],
        )

    _mount_frontend(app, p)
    return app


class _SpaStaticFiles(StaticFiles):
    """StaticFiles that serves ``index.html`` for unknown paths.

    Client-side routing needs a deep link like ``/runs`` to survive a page reload.
    Starlette's ``html=True`` only serves ``index.html`` for *directory* requests —
    an unknown path still 404s — so the SPA fallback has to be explicit. A missing
    real asset (``/assets/app.js`` after a stale build) therefore returns the shell
    rather than a 404, which is the standard trade and the reason ``/api/*`` is
    registered before this mount.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _mount_frontend(app: FastAPI, p: GlassboxPaths) -> None:
    """Serve ``frontend/dist`` at ``/`` when it has been built.

    Mounted LAST so it can never shadow ``/api/*``. When the build is absent the
    API stays fully functional and ``/`` explains how to produce it, rather than
    404ing or — worse — failing to start: the API is the product, the frontend is a
    view of it, and a missing view must not take the data down with it.
    """
    if p.frontend_built:
        app.mount("/", _SpaStaticFiles(directory=str(p.frontend_dist), html=True),
                  name="frontend")
        return

    @app.get("/", response_class=PlainTextResponse, include_in_schema=False)
    def frontend_missing() -> str:
        return (
            "quantlab Glass Box — frontend not built.\n\n"
            f"Expected a built SPA at: {p.frontend_dist}\n\n"
            "To build it:\n"
            "    cd frontend\n"
            "    npm install\n"
            "    npm run build\n\n"
            "Then restart `quantlab glassbox serve`.\n\n"
            "The API is unaffected and serving now. Try:\n"
            "    /api/overview   /api/runs   /api/divergence   /api/risk\n"
            "    /api/equity     /api/timeline   /api/decisions\n"
            "    /api/ignored-inputs\n"
            "    /docs           (interactive schema)\n"
        )


def _run_view(run_id: str, report: dict[str, Any]) -> RunView:
    """Project one run report onto its response model, tolerating missing fields."""
    plan = _as_dict(report.get("plan"))
    raw_targets = report.get("target_weights")

    targets: dict[str, float] = {}
    for key, value in _as_dict(raw_targets).items():
        as_float = _as_float(value)
        if as_float is not None:
            targets[str(key)] = as_float

    return RunView(
        run_id=run_id,
        strategy=report.get("strategy"),
        timestamp=readers.parse_timestamp(report.get("timestamp")),
        dry_run=report.get("dry_run"),
        aborted=bool(report.get("aborted")),
        abort_stage=report.get("abort_stage"),
        abort_reason=report.get("abort_reason"),
        equity=_as_float(report.get("equity")),
        target_weights=targets,
        no_trades=report.get("no_trades"),
        est_turnover=_as_float(plan.get("est_turnover")),
        min_trade_frac=_as_float(plan.get("min_trade_frac")),
        stages=[
            StageView(stage=str(s.get("stage", "?")), ok=bool(s.get("ok")),
                      detail=s.get("detail"))
            for s in _as_list(report.get("stages")) if isinstance(s, dict)
        ],
        intents=[
            IntentView(symbol=i.get("symbol"), side=i.get("side"),
                       notional=_as_float(i.get("notional")),
                       current_w=_as_float(i.get("current_w")),
                       target_w=_as_float(i.get("target_w")))
            for i in _as_list(plan.get("intents")) if isinstance(i, dict)
        ],
        submitted_orders=[
            OrderView(symbol=o.get("symbol"), side=o.get("side"),
                      notional=_as_float(o.get("notional")), status=o.get("status"),
                      client_order_id=o.get("client_order_id"),
                      submitted_at=readers.parse_timestamp(o.get("submitted_at")),
                      was_duplicate=bool(o.get("was_duplicate")))
            for o in _as_list(report.get("submitted_orders")) if isinstance(o, dict)
        ],
    )


__all__ = ["create_app"]
