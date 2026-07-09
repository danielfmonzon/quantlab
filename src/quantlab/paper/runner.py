"""Gated paper-trading runner: an ordered pipeline that aborts on first failure.

The pipeline (each stage logged; first failure aborts with a clear reason):

  a. risk state       -- if halted, abort BEFORE any broker/network call
  b. ingest           -- top up recent bars for the strategy's symbols
  c. validate         -- any ERROR aborts
  d. health preflight -- stale data aborts (FREEZE_STALE_DATA)
  e. account          -- unverifiable/blocked/non-positive equity aborts
  f. target weights   -- the CURRENT signal (see "converge-to-target" below)
  g. check_weights    -- risk-engine weight containment
  h. evaluate_portfolio -- HALT/KILL writes RiskState and aborts BEFORE orders
  i. plan_rebalance   -- no intents => "in-band, no trades", exit clean
  j. submit           -- DRY-RUN by default; real submit is sells-then-buys
  k. report           -- write reports/paper/run_{strategy}_{ts}.json

CONVERGE-TO-TARGET vs the backtest. The backtest only ever trades ON a rebalance
date (month-end): weights emitted at month-end t take effect at t+1 and then
drift untouched until the next month-end. The paper runner instead trades toward
the CURRENT target (the signal from the most recent warmed month-end <= the last
stored session) WHENEVER live drift exceeds ``min_trade_frac`` — not only on the
rebalance day itself. This is deliberate: a paper process may miss its month-end
run (host down, market holiday, a late data feed), and converge-to-target lets
the next successful run still reach the intended allocation. Because the signals
are monthly and only change at month-ends, the two policies differ only in *when*
a given target is reached, never in *what* target is pursued; the min-trade band
keeps the extra reconvergence trades from churning.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from quantlab.backtest.panel import build_price_panel
from quantlab.backtest.signals import month_end_sessions
from quantlab.backtest.strategies import TrendSMA10, VolTarget
from quantlab.backtest.strategy import Strategy
from quantlab.broker.alpaca_trading import (
    AccountInfo,
    AlpacaTradingClient,
    OrderInfo,
)
from quantlab.config import ConfigError
from quantlab.constants import PROJECT_ROOT
from quantlab.data.alpaca_client import ClockInfo
from quantlab.data.calendar import TradingCalendar
from quantlab.data.health import HealthReport, preflight
from quantlab.data.store import ParquetStore
from quantlab.data.validate import ValidationReport, validate
from quantlab.logging_setup import get_logger
from quantlab.paper.rebalance import RebalancePlan, plan_rebalance
from quantlab.reporting.alerts import Alert, dispatch
from quantlab.risk.engine import (
    HALT_DAILY_LOSS,
    HALT_WEEKLY_LOSS,
    KILL_DRAWDOWN,
    RiskEngine,
)
from quantlab.risk.limits import load_risk_limits
from quantlab.risk.state import (
    DEFAULT_STATE_PATH,
    RiskState,
    load_risk_state,
    save_risk_state,
)

log = get_logger("quantlab.paper")

DEFAULT_EQUITY_HISTORY: Path = PROJECT_ROOT / "data" / "equity_history.parquet"
PAPER_REPORTS_DIR: Path = PROJECT_ROOT / "reports" / "paper"

# Order statuses that will never change again (Alpaca lifecycle).
_TERMINAL_STATUSES = frozenset({
    "filled", "canceled", "cancelled", "expired", "rejected",
    "done_for_day", "replaced", "closed", "stopped", "suspended",
})


class StageOutcome(BaseModel):
    """Result of one pipeline stage."""

    stage: str
    ok: bool
    detail: str


class PaperRunReport(BaseModel):
    """Full record of one paper run (written to reports/paper/)."""

    strategy: str
    dry_run: bool
    timestamp: datetime
    aborted: bool = False
    abort_stage: str | None = None
    abort_reason: str | None = None
    equity: float | None = None
    target_weights: dict[str, float] = {}
    plan: RebalancePlan | None = None
    submitted_orders: list[OrderInfo] = []
    no_trades: bool = False
    stages: list[StageOutcome] = []


def make_paper_strategy(name: str) -> Strategy:
    """The paper-supported strategies (a deliberately small, cash-only set)."""
    if name == "trend":
        return TrendSMA10()
    if name == "voltarget":
        return VolTarget()
    raise ConfigError(f"paper run supports 'trend' or 'voltarget'; got {name!r}")


def current_target_weights(
    strategy: Strategy, panel: pd.DataFrame
) -> tuple[dict[str, float], date | None]:
    """Target weights from the most recent WARMED month-end <= the last session.

    Scans month-ends newest-first; returns the first warmed-up signal. If none is
    warmed (insufficient history), returns cash ({}).
    """
    dates = list(panel.index)
    for reb in reversed(month_end_sessions(dates)):
        window = panel.loc[:reb]
        if strategy.is_warmed_up(window, reb):
            return strategy.target_weights(window, reb), reb.date()
    return {}, None


def run_paper(
    strategy_name: str,
    dry_run: bool = True,
    *,
    store: ParquetStore | None = None,
    broker: AlpacaTradingClient | None = None,
    calendar: TradingCalendar | None = None,
    now: datetime | None = None,
    do_ingest: bool = True,
    ingest_fn: Callable[[list[str], ParquetStore], None] | None = None,
    validation_override: list[ValidationReport] | None = None,
    health_override: HealthReport | None = None,
    clock: ClockInfo | None = None,
    risk_state_path: Path = DEFAULT_STATE_PATH,
    equity_history_path: Path = DEFAULT_EQUITY_HISTORY,
    reports_dir: Path = PAPER_REPORTS_DIR,
    min_trade_frac: float = 0.01,
    poll_timeout: float = 120.0,
    poll_interval: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
    write_report: bool = True,
    alert_fn: Callable[[Alert], None] | None = None,
) -> PaperRunReport:
    """Execute the gated paper pipeline. Returns a report; never submits on dry run.

    Collaborators (store/broker/…) are injectable so the default test suite runs
    fully mocked. In production the CLI supplies the real store, paper broker, and
    ingest function.
    """
    run_now = now if now is not None else datetime.now(UTC)
    strategy = make_paper_strategy(strategy_name)
    report = PaperRunReport(strategy=strategy_name, dry_run=dry_run, timestamp=run_now)

    def _stage(stage: str, ok: bool, detail: str) -> None:
        report.stages.append(StageOutcome(stage=stage, ok=ok, detail=detail))
        log.info("paper_stage", strategy=strategy_name, stage=stage, ok=ok, detail=detail)

    def _emit(alert: Alert) -> None:
        # Alerting must NEVER break a run or prevent a state write.
        fn = alert_fn if alert_fn is not None else _default_runner_alert
        try:
            fn(alert)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert_dispatch_failed", error=str(exc))

    def _abort(stage: str, reason: str, level: str = "WARNING") -> PaperRunReport:
        _stage(stage, False, reason)
        report.aborted = True
        report.abort_stage = stage
        report.abort_reason = reason
        _finish(report, reports_dir, write_report)  # state written first ...
        _emit(Alert(  # ... then alert (never before the write)
            level=level, title=f"paper {strategy_name} aborted at '{stage}'",
            body=reason, source="paper.runner",
        ))
        return report

    # -- (a) risk state: FIRST, before any broker/network touch --------------
    state = load_risk_state(risk_state_path)
    if state.halted:
        if state.requires_manual_reset:
            reason = f"halted: {state.reason}; quantlab risk reset required"
        else:
            reason = f"halted (auto): {state.reason}"
        return _abort("risk_state", reason)
    _stage("risk_state", True, "not halted")

    symbols = strategy.all_symbols
    the_store = store if store is not None else ParquetStore()

    # -- (b) ingest latest data ---------------------------------------------
    if do_ingest and ingest_fn is not None:
        try:
            ingest_fn(symbols, the_store)
            _stage("ingest", True, f"ingested {', '.join(symbols)}")
        except Exception as exc:  # noqa: BLE001 - surfaced as a clean abort
            return _abort("ingest", f"ingest failed: {exc}")
    else:
        _stage("ingest", True, "skipped (no ingest function)")

    # -- (c) validate --------------------------------------------------------
    the_cal = calendar if calendar is not None else TradingCalendar()
    if validation_override is not None:
        reports = validation_override
    else:
        reports = []
        for sym in symbols:
            meta = the_store.load_metadata(sym)
            reports.append(validate(
                the_store.load(sym), sym,
                inception_date=meta.inception_date if meta else None,
                requested_start=meta.requested_start if meta else None,
                now=run_now, calendar=the_cal,
            ))
    failed = [r.symbol for r in reports if not r.passed]
    if failed:
        return _abort("validate", f"validation failed for: {', '.join(failed)}")
    _stage("validate", True, f"validated {', '.join(symbols)}")

    # -- (d) health preflight ------------------------------------------------
    if health_override is not None:
        health = health_override
    else:
        health = preflight(symbols, the_store, the_cal, clock, run_now)
    if not health.data_fresh:
        why = "; ".join(health.blocking_reasons) or "data not fresh"
        return _abort("health", f"FREEZE_STALE_DATA: {why}")
    _stage("health", True, "data fresh")

    # -- (e) account ---------------------------------------------------------
    the_broker = broker if broker is not None else _require_broker()
    try:
        account = the_broker.get_account()
    except Exception as exc:  # noqa: BLE001
        return _abort("account", f"account unverifiable: {exc}", level="CRITICAL")
    bad = _account_problem(account)
    if bad is not None:
        return _abort("account", bad, level="CRITICAL")
    report.equity = account.equity
    _stage("account", True, f"equity={account.equity:.2f} cash={account.cash:.2f}")

    # -- (f) current target weights -----------------------------------------
    panel = build_price_panel(the_store, symbols)
    usable = panel[strategy.required_symbols].dropna()
    if usable.empty:
        return _abort("target_weights", "no sessions where required symbols have prices")
    panel = panel.loc[usable.index.min():]
    targets, signal_date = current_target_weights(strategy, panel)
    _stage("target_weights", True,
            f"signal@{signal_date} -> {targets}" if signal_date else "cash (not warmed)")

    # -- (g) risk-engine weight containment ---------------------------------
    engine = RiskEngine(load_risk_limits())
    decision = engine.check_weights(targets)
    adjusted = decision.adjusted_weights
    report.target_weights = adjusted
    _stage("check_weights", True,
            "; ".join(decision.adjustments) if decision.adjustments else "no adjustment")

    # -- (h) evaluate_portfolio on account equity history -------------------
    equity_series = _append_equity_snapshot(equity_history_path, run_now, account.equity)
    if len(equity_series) >= 2:
        pdec = engine.evaluate_portfolio(equity_series, len(equity_series) - 1)
        if pdec.action in (KILL_DRAWDOWN, HALT_DAILY_LOSS, HALT_WEEKLY_LOSS):
            save_risk_state(
                RiskState(
                    halted=True, reason=f"{pdec.action}: {pdec.reason}",
                    triggered_at=run_now,
                    requires_manual_reset=(pdec.action == KILL_DRAWDOWN),
                ),
                risk_state_path,
            )
            return _abort(
                "evaluate_portfolio", f"{pdec.action}: {pdec.reason}", level="CRITICAL"
            )
        _stage("evaluate_portfolio", True, f"{pdec.action} (dd={pdec.drawdown})")
    else:
        _stage("evaluate_portfolio", True, "insufficient history (<2 snapshots)")

    # -- (i) plan ------------------------------------------------------------
    positions = the_broker.get_positions()
    plan = plan_rebalance(adjusted, account.equity, positions, min_trade_frac=min_trade_frac)
    report.plan = plan
    if not plan.intents:
        report.no_trades = True
        _stage("plan", True, "in-band, no trades")
        _finish(report, reports_dir, write_report)
        return report
    _stage("plan", True,
            f"{len(plan.intents)} intent(s), buy_scale={plan.buy_scale:.4f}, "
            f"turnover={plan.est_turnover:.4f}")

    # -- (j) submit (or not) -------------------------------------------------
    if dry_run:
        _stage("submit", True, "DRY-RUN: no orders submitted")
    else:
        try:
            submitted = _submit_plan(
                the_broker, strategy_name, plan, run_now.date(),
                poll_timeout, poll_interval, sleep_fn, monotonic_fn,
            )
        except Exception as exc:  # noqa: BLE001
            return _abort("submit", f"order submission failed: {exc}", level="CRITICAL")
        report.submitted_orders = submitted
        dupes = sum(1 for o in submitted if o.was_duplicate)
        _stage("submit", True, f"submitted {len(submitted)} order(s), {dupes} duplicate(s)")

    # -- (k) report ----------------------------------------------------------
    _finish(report, reports_dir, write_report)
    if not dry_run and report.submitted_orders:
        total = sum(i.notional for i in plan.intents)
        _emit(Alert(
            level="INFO",
            title=(f"paper {strategy_name}: {len(report.submitted_orders)} order(s) "
                   f"submitted, ${total:,.2f} notional"),
            body=f"weights={report.target_weights}; turnover={plan.est_turnover:.4f}",
            source="paper.runner",
        ))
    return report


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _default_runner_alert(alert: Alert) -> None:
    """Dispatch to the default channels (console + file + email if configured)."""
    dispatch(alert)


def _require_broker() -> AlpacaTradingClient:  # pragma: no cover - exercised via CLI
    raise ConfigError("run_paper needs a broker; construct one from Settings in the CLI")


def _account_problem(account: AccountInfo) -> str | None:
    if account.account_blocked:
        return "account_blocked is set"
    if account.trading_blocked:
        return "trading_blocked is set"
    if account.equity <= 0.0:
        return f"non-positive equity ({account.equity})"
    return None


def _append_equity_snapshot(path: Path, ts: datetime, equity: float) -> pd.Series:
    if path.exists():
        hist = pd.read_parquet(path)
    else:
        hist = pd.DataFrame({"timestamp": pd.Series(dtype="datetime64[ns]"),
                             "equity": pd.Series(dtype="float64")})
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    row = pd.DataFrame({"timestamp": [t], "equity": [float(equity)]})
    hist = pd.concat([hist, row], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    hist.to_parquet(path, index=False)
    return pd.Series(hist["equity"].to_numpy(dtype=float), name="equity")


def _coid(strategy: str, day: date, symbol: str, side: str) -> str:
    return f"ql-{strategy}-{day.strftime('%Y%m%d')}-{symbol}-{side}"


def _submit_plan(
    broker: AlpacaTradingClient,
    strategy: str,
    plan: RebalancePlan,
    day: date,
    poll_timeout: float,
    poll_interval: float,
    sleep_fn: Callable[[float], None],
    monotonic_fn: Callable[[], float],
) -> list[OrderInfo]:
    """Submit sells, wait for them to reach a terminal state, then submit buys."""
    sells = [i for i in plan.intents if i.side == "sell"]
    buys = [i for i in plan.intents if i.side == "buy"]
    submitted: list[OrderInfo] = []

    sell_ids: list[str] = []
    for intent in sells:
        order = broker.submit_order(
            intent.symbol, intent.side, intent.notional,
            _coid(strategy, day, intent.symbol, intent.side),
        )
        submitted.append(order)
        sell_ids.append(order.id)

    if sell_ids:
        _await_terminal(broker, sell_ids, day, poll_timeout, poll_interval, sleep_fn, monotonic_fn)

    for intent in buys:
        order = broker.submit_order(
            intent.symbol, intent.side, intent.notional,
            _coid(strategy, day, intent.symbol, intent.side),
        )
        submitted.append(order)

    return submitted


def _await_terminal(
    broker: AlpacaTradingClient,
    order_ids: list[str],
    day: date,
    timeout: float,
    interval: float,
    sleep_fn: Callable[[float], None],
    monotonic_fn: Callable[[], float],
) -> dict[str, str]:
    """Poll until every order id is terminal or the timeout elapses."""
    deadline = monotonic_fn() + timeout
    wanted = set(order_ids)
    while True:
        by_id = {o.id: o.status for o in broker.get_orders(status="all", after=day)}
        statuses = {oid: by_id.get(oid, "unknown") for oid in wanted}
        if all(s in _TERMINAL_STATUSES for s in statuses.values()):
            return statuses
        if monotonic_fn() >= deadline:
            return statuses  # market likely closed; caller proceeds and reports status
        sleep_fn(interval)


def _finish(report: PaperRunReport, reports_dir: Path, write_report: bool) -> None:
    log.info("paper_run", **report.model_dump(mode="json"))
    if not write_report:
        return
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.timestamp.strftime("%Y%m%dT%H%M%SZ")
    path = reports_dir / f"run_{report.strategy}_{stamp}.json"
    path.write_text(json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8")


__all__ = [
    "run_paper",
    "PaperRunReport",
    "StageOutcome",
    "make_paper_strategy",
    "current_target_weights",
    "DEFAULT_EQUITY_HISTORY",
    "PAPER_REPORTS_DIR",
]
