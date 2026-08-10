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

from quantlab.backtest.panel import build_price_panel, completed_sessions_only
from quantlab.backtest.signals import month_end_sessions
from quantlab.backtest.strategies import (
    CryptoTrendBTC,
    CryptoVolTargetBTC,
    TrendSMA10,
    VolTarget,
)
from quantlab.backtest.strategy import Strategy
from quantlab.broker.alpaca_trading import (
    AccountInfo,
    AlpacaTradingClient,
    OrderInfo,
)
from quantlab.config import ConfigError, account_asset_class
from quantlab.constants import CRYPTO_RISK_YAML, PROJECT_ROOT
from quantlab.data import DataError
from quantlab.data.alpaca_client import ClockInfo
from quantlab.data.calendar import CryptoCalendar, MarketCalendar, TradingCalendar
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
    RiskState,
    load_risk_state,
    risk_state_path_for,
    save_risk_state,
)

log = get_logger("quantlab.paper")

DATA_DIR: Path = PROJECT_ROOT / "data"
DEFAULT_EQUITY_HISTORY: Path = DATA_DIR / "equity_history.parquet"
PAPER_REPORTS_DIR: Path = PROJECT_ROOT / "reports" / "paper"


def equity_history_path_for(label: str, data_dir: Path = DATA_DIR) -> Path:
    """Per-account equity-history path, e.g. ``data/equity_history_trend.parquet``."""
    return data_dir / f"equity_history_{label}.parquet"


def migrate_legacy_state(data_dir: Path = DATA_DIR) -> list[str]:
    """Rename Batch-9 single-account files to voltarget's namespace (idempotent).

    The legacy ``equity_history.parquet`` / ``risk_state.json`` held voltarget's
    state, so they migrate to the ``*_voltarget.*`` names. Returns the files
    created (empty on a no-op). Safe to call every run.
    """
    migrations = [
        (data_dir / "equity_history.parquet", data_dir / "equity_history_voltarget.parquet"),
        (data_dir / "risk_state.json", data_dir / "risk_state_voltarget.json"),
    ]
    migrated: list[str] = []
    for legacy, target in migrations:
        if legacy.exists() and not target.exists():
            legacy.rename(target)
            migrated.append(target.name)
    if migrated:
        log.info("legacy_state_migrated", files=migrated)
    return migrated

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
    # Which attempt of the day produced this report: 1 for the scheduled run, 2 for the
    # single bounded retry (see run_paper_with_retry). A run audit that counts reports
    # without this cannot tell one clean run from a recovery.
    attempt: int = 1
    aborted: bool = False
    abort_stage: str | None = None
    abort_reason: str | None = None
    # Whether this abort's CAUSE could plausibly be cured by simply running again.
    # Decided at the abort site, where the exception and the stage are both in hand,
    # rather than inferred later from the reason string.
    abort_retryable: bool = False
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
    if name == "crypto_trend":
        return CryptoTrendBTC()
    if name == "crypto_voltarget":
        return CryptoVolTargetBTC()
    raise ConfigError(
        "paper run supports 'trend', 'voltarget', 'crypto_trend', 'crypto_voltarget'; "
        f"got {name!r}"
    )


def calendar_for_account(label: str) -> MarketCalendar:
    """The calendar an account's sessions live on: 24/7 UTC for crypto, XNYS otherwise.

    One source of truth, shared by the runner and ``reporting.shadow`` so the
    signal and its shadow reconstruction agree on what "a session" means.
    """
    return CryptoCalendar() if account_asset_class(label) == "crypto" else TradingCalendar()


def current_target_weights(
    strategy: Strategy,
    panel: pd.DataFrame,
    *,
    calendar: MarketCalendar | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, float], date | None]:
    """Target weights from the most recent WARMED month-end <= the last session.

    Scans month-ends newest-first; returns the first warmed-up signal. If none is
    warmed (insufficient history), returns cash ({}).

    When ``calendar`` and ``now`` are both supplied the panel is first truncated to
    ``calendar.last_completed_session(now)``, so a bar for the session still in
    progress can never move the signal (see
    ``backtest.panel.completed_sessions_only``). Omitting them preserves the
    previous unfiltered behavior for callers that have already truncated.
    """
    panel = completed_sessions_only(panel, calendar, now)
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
    # Built lazily at stage (e), never before. Stage (a) exists so a halted account
    # aborts without touching the broker at all -- and "touching" includes reading
    # credentials and constructing a client, so the factory must not be called earlier.
    broker_factory: Callable[[], AlpacaTradingClient] | None = None,
    calendar: MarketCalendar | None = None,
    now: datetime | None = None,
    do_ingest: bool = True,
    ingest_fn: Callable[[list[str], ParquetStore], None] | None = None,
    validation_override: list[ValidationReport] | None = None,
    health_override: HealthReport | None = None,
    clock: ClockInfo | None = None,
    risk_state_path: Path | None = None,
    equity_history_path: Path | None = None,
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
    is_crypto = account_asset_class(strategy_name) == "crypto"
    report = PaperRunReport(strategy=strategy_name, dry_run=dry_run, timestamp=run_now)

    # Per-account state isolation: default each path to this strategy's own label
    # so a KILL/history in one account never touches another's.
    rs_path = risk_state_path if risk_state_path is not None else risk_state_path_for(strategy_name)
    eq_path = (
        equity_history_path if equity_history_path is not None
        else equity_history_path_for(strategy_name)
    )

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

    def _abort(stage: str, reason: str, level: str = "WARNING",
               retryable: bool = False) -> PaperRunReport:
        _stage(stage, False, reason)
        report.aborted = True
        report.abort_stage = stage
        report.abort_reason = reason
        report.abort_retryable = retryable
        _finish(report, reports_dir, write_report)  # state written first ...
        _emit(Alert(  # ... then alert (never before the write)
            level=level, title=f"paper {strategy_name} aborted at '{stage}'",
            body=reason, source="paper.runner", strategy=strategy_name,
        ))
        return report

    # -- (a) risk state: FIRST, before any broker/network touch --------------
    state = load_risk_state(rs_path)
    if state.halted:
        if state.requires_manual_reset:
            reason = f"halted: {state.reason}; quantlab risk reset required"
        else:
            reason = f"halted (auto): {state.reason}"
        # A halt is a decision, not a hiccup. Only `quantlab risk reset` clears it.
        return _abort("risk_state", reason, retryable=False)
    _stage("risk_state", True, "not halted")

    symbols = strategy.all_symbols
    the_store = store if store is not None else ParquetStore()

    # -- (b) ingest latest data ---------------------------------------------
    if do_ingest and ingest_fn is not None:
        try:
            ingest_fn(symbols, the_store)
            _stage("ingest", True, f"ingested {', '.join(symbols)}")
        except ConfigError as exc:
            # A missing key or bad endpoint is not cured by waiting; do not retry.
            return _abort("ingest", f"ingest failed: {exc}", retryable=False)
        except Exception as exc:  # noqa: BLE001 - surfaced as a clean abort
            # Network/API transient. The ingest is idempotent (upsert), so re-running
            # it is safe as well as useful.
            return _abort("ingest", f"ingest failed: {exc}", retryable=True)
    else:
        _stage("ingest", True, "skipped (no ingest function)")

    # -- (c) validate --------------------------------------------------------
    # Crypto accounts measure sessions/staleness on the 24/7 UTC grid; equities
    # keep XNYS. An explicitly injected calendar (tests) always wins.
    default_cal: MarketCalendar = calendar_for_account(strategy_name)
    the_cal = calendar if calendar is not None else default_cal
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
        # Data-CONTENT errors. A re-run reads the same bars and reaches the same
        # verdict, so retrying would only delay the same abort by ten minutes.
        return _abort("validate", f"validation failed for: {', '.join(failed)}",
                      retryable=False)
    _stage("validate", True, f"validated {', '.join(symbols)}")

    # -- (d) health preflight ------------------------------------------------
    if health_override is not None:
        health = health_override
    else:
        health = preflight(symbols, the_store, the_cal, clock, run_now)
    if not health.data_fresh:
        why = "; ".join(health.blocking_reasons) or "data not fresh"
        # Staleness is the one gate a later re-ingest genuinely cures: the vendor may
        # simply not have published the bar yet when the scheduled run fired.
        return _abort("health", f"FREEZE_STALE_DATA: {why}", retryable=True)
    _stage("health", True, "data fresh")

    # -- (e) account ---------------------------------------------------------
    if broker is not None:
        the_broker = broker
    elif broker_factory is not None:
        the_broker = broker_factory()
    else:
        the_broker = _require_broker()
    try:
        account = the_broker.get_account()
    except Exception as exc:  # noqa: BLE001
        # The client has its own tenacity policy for 429/5xx/network and only reraises
        # once it has exhausted it, so reaching here means the condition persisted.
        # DataError (and its subclass TradingError, which carries a permanent 4xx) means
        # the API answered and the answer was bad -- auth, permissions, malformed body --
        # none of which a tenth-minute retry fixes. Anything else is a sustained
        # transport/5xx failure on a READ, which is worth one more attempt.
        transient = not isinstance(exc, DataError)
        return _abort("account", f"account unverifiable: {exc}",
                      level="CRITICAL", retryable=transient)
    bad = _account_problem(account)
    if bad is not None:
        # Blocked account or non-positive equity: a real account state, not a blip.
        return _abort("account", bad, level="CRITICAL", retryable=False)
    report.equity = account.equity
    _stage("account", True, f"equity={account.equity:.2f} cash={account.cash:.2f}")

    # -- (f) current target weights -----------------------------------------
    # Completed sessions ONLY: ingest above may have written a bar for the session
    # still in progress, and a signal read off an in-progress price is not
    # reproducible. Truncating before the usable-history guard keeps that guard's
    # abort reason accurate; current_target_weights re-applies it for direct callers.
    panel = build_price_panel(the_store, symbols)
    panel = completed_sessions_only(panel, the_cal, run_now)
    usable = panel[strategy.required_symbols].dropna()
    if usable.empty:
        return _abort("target_weights", "no sessions where required symbols have prices",
                      retryable=False)
    panel = panel.loc[usable.index.min():]
    targets, signal_date = current_target_weights(
        strategy, panel, calendar=the_cal, now=run_now
    )
    _stage("target_weights", True,
            f"signal@{signal_date} -> {targets}" if signal_date else "cash (not warmed)")

    # -- (g) risk-engine weight containment ---------------------------------
    # Crypto accounts use crypto_risk.yaml (wider limits); equities keep risk.yaml.
    engine = RiskEngine(load_risk_limits(CRYPTO_RISK_YAML) if is_crypto else load_risk_limits())
    decision = engine.check_weights(targets)
    adjusted = decision.adjusted_weights
    report.target_weights = adjusted
    _stage("check_weights", True,
            "; ".join(decision.adjustments) if decision.adjustments else "no adjustment")

    # -- (h) evaluate_portfolio on account equity history -------------------
    equity_series = _append_equity_snapshot(eq_path, run_now, account.equity)
    if len(equity_series) >= 2:
        pdec = engine.evaluate_portfolio(equity_series, len(equity_series) - 1)
        if pdec.action in (KILL_DRAWDOWN, HALT_DAILY_LOSS, HALT_WEEKLY_LOSS):
            save_risk_state(
                RiskState(
                    halted=True, reason=f"{pdec.action}: {pdec.reason}",
                    triggered_at=run_now,
                    requires_manual_reset=(pdec.action == KILL_DRAWDOWN),
                ),
                rs_path,
            )
            return _abort(
                "evaluate_portfolio", f"{pdec.action}: {pdec.reason}",
                level="CRITICAL", retryable=False,
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
            # Submission has BEGUN: some orders may be live at the broker. Re-running
            # the pipeline could double up on them. This alerts and stops, always.
            return _abort("submit", f"order submission failed: {exc}",
                          level="CRITICAL", retryable=False)
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
            source="paper.runner", strategy=strategy_name,
        ))
    return report


# --------------------------------------------------------------------------- #
# Bounded retry                                                               #
# --------------------------------------------------------------------------- #

# One retry, ten minutes later. Bounded on purpose: the point is to survive a vendor
# publishing a bar late or a broker read blipping, not to keep hammering. If ten minutes
# does not cure it, the condition is real and the next scheduled run is soon enough.
RETRY_DELAY_SECONDS = 600.0


def run_paper_with_retry(
    strategy_name: str,
    dry_run: bool = True,
    *,
    retry_delay_seconds: float = RETRY_DELAY_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
    alert_fn: Callable[[Alert], None] | None = None,
    broker_factory: Callable[[], AlpacaTradingClient] | None = None,
    **kwargs: object,
) -> PaperRunReport:
    """Run the gated pipeline, retrying ONCE if the abort's cause was transient.

    Before this, any abort ended the attempt until the next scheduled day: a bar published
    three minutes late cost a whole session of paper record, and those gaps are exactly what
    the divergence diagnoses kept tripping over (a missed run turns two clean 24h mark
    windows into a 70h one and a 7h one).

    WHAT IS RETRIED is decided at each abort site rather than pattern-matched here, so the
    decision is made where the exception and the stage are both in hand:

    * ``ingest``   -- transient network/API failure. The ingest is an upsert, so repeating
                      it is idempotent. A ``ConfigError`` is NOT retried: a missing key is
                      not cured by waiting.
    * ``health``   -- ``FREEZE_STALE_DATA``. The canonical case: the vendor had not
                      published the session's bar when the scheduled run fired.
    * ``account``  -- only a sustained transport/5xx failure on the READ. The client has
                      already exhausted its own tenacity policy by the time this surfaces.

    NEVER RETRIED, each for its own reason:

    * ``risk_state`` halted -- a decision, not a hiccup; only ``risk reset`` clears it.
    * ``validate``          -- a data-CONTENT error; a re-run reads the same bars.
    * ``account`` blocked / non-positive equity -- a real account state.
    * ``account`` permanent API fault (``DataError``/``TradingError``, i.e. 4xx, auth,
      malformed body) -- the API answered and the answer was bad.
    * ``target_weights``    -- no usable history is a content condition.
    * ``evaluate_portfolio``-- a HALT/KILL was just WRITTEN. Retrying must never look like
      a second chance at trading.
    * ``submit``            -- submission has BEGUN and orders may be live at the broker.
      A partial submission must alert, never re-run a pipeline that could double it.

    ALERTING. Attempt 1's abort alert is withheld while a retry is pending and discarded if
    the retry happens, so one logical failure raises exactly one WARNING — the final
    outcome's. A non-retryable abort alerts immediately, unbuffered.

    No equity snapshot can be double-written: every retryable abort occurs at stage (b)-(e),
    strictly before the snapshot is appended at stage (h).

    ``broker_factory`` is called once PER ATTEMPT rather than a client being passed in, so
    the retry gets a fresh session ten minutes later instead of reusing one whose connection
    or token may be exactly what failed. It is also the observable that proves a
    non-retryable abort really stopped: the factory is called once, never twice.
    """
    buffered: list[Alert] = []
    emit = alert_fn if alert_fn is not None else _default_runner_alert

    def _attempt(sink: Callable[[Alert], None]) -> PaperRunReport:
        # The factory is handed through, NOT called here: run_paper builds the client at
        # stage (e), so a halted account still aborts without a broker ever existing.
        return run_paper(
            strategy_name, dry_run,
            alert_fn=sink, sleep_fn=sleep_fn,
            broker_factory=broker_factory, **kwargs,  # type: ignore[arg-type]
        )

    first = _attempt(buffered.append)  # held until we know if a retry supersedes it
    first.attempt = 1

    if not (first.aborted and first.abort_retryable):
        for alert in buffered:  # nothing supersedes these
            emit(alert)
        return first

    log.warning(
        "paper_retry_scheduled", strategy=strategy_name, stage=first.abort_stage,
        reason=first.abort_reason, delay_seconds=retry_delay_seconds,
    )
    sleep_fn(retry_delay_seconds)

    second = _attempt(emit)  # attempt 2 speaks for itself, whatever it decides
    second.attempt = 2
    # Rewrite the report so the persisted record carries attempt=2. `run_paper` wrote it
    # before this function could set the field, and the file is what the audit reads.
    _rewrite_attempt(second, kwargs)
    log.info(
        "paper_retry_outcome", strategy=strategy_name,
        first_stage=first.abort_stage, retried=True,
        recovered=not second.aborted,
        second_stage=second.abort_stage,
    )
    return second


def _rewrite_attempt(report: PaperRunReport, kwargs: dict[str, object]) -> None:
    """Re-persist ``report`` so its file records the attempt number it actually was."""
    if kwargs.get("write_report") is False:
        return
    reports_dir = kwargs.get("reports_dir")
    _finish(
        report,
        reports_dir if isinstance(reports_dir, Path) else PAPER_REPORTS_DIR,
        True,
    )


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


def run_all_strategies(
    strategies: list[str],
    run_one: Callable[[str], int],
    printer: Callable[[str], None] = print,
) -> int:
    """Run each strategy in order, isolating failures; nonzero if ANY failed.

    One strategy raising or aborting must never prevent the next from running —
    each account is independent. Returns 0 only if every strategy returned 0.
    """
    overall = 0
    for strategy in strategies:
        printer(f"\n========== {strategy} ==========")
        try:
            rc = run_one(strategy)
        except Exception as exc:  # noqa: BLE001 - isolate: keep going to the next account
            log.error("run_all_strategy_failed", strategy=strategy, error=str(exc))
            printer(f"[{strategy}] FAILED: {exc}")
            rc = 1
        if rc != 0:
            overall = 1
    return overall


__all__ = [
    "calendar_for_account",
    "run_paper",
    "run_paper_with_retry",
    "RETRY_DELAY_SECONDS",
    "run_all_strategies",
    "PaperRunReport",
    "StageOutcome",
    "make_paper_strategy",
    "current_target_weights",
    "migrate_legacy_state",
    "equity_history_path_for",
    "DATA_DIR",
    "DEFAULT_EQUITY_HISTORY",
    "PAPER_REPORTS_DIR",
]
