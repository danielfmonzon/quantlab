"""quantlab command-line interface.

Subcommands:
    quantlab ingest --start 2000-01-01 [--symbols SPY,QQQ]
    quantlab validate [--symbols SPY,QQQ]
    quantlab reconcile [--symbols ...] [--days 400] [--tolerance 0.0075]
    quantlab health
    quantlab backtest --strategy buyhold|sixty40 [--symbol SPY] [--start ...]
                      [--cost-bps 5] [--benchmark SPY]

API keys are read via Settings.require_keys and are never logged.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from quantlab.backtest.engine import BacktestResult, run_backtest
from quantlab.backtest.metrics import Metrics, compute_metrics
from quantlab.backtest.panel import build_price_panel, returns_panel
from quantlab.backtest.strategies import (
    BuyAndHold,
    CryptoTrendBTC,
    CryptoVolTargetBTC,
    DualMomentum,
    FixedWeights,
    Strategy,
    TrendSMA10,
    VolTarget,
)
from quantlab.broker.alpaca_trading import AccountInfo, AlpacaTradingClient, Position
from quantlab.config import (
    APPROVED_STRATEGIES,
    EQUITY_APPROVED_STRATEGIES,
    ConfigError,
    account_asset_class,
    account_for,
    account_label,
    get_settings,
    load_crypto_universe,
    load_env_file,
    load_universe,
)
from quantlab.constants import PROJECT_ROOT
from quantlab.data.alpaca_client import AlpacaDataClient
from quantlab.data.calendar import CryptoCalendar, TradingCalendar
from quantlab.data.coinbase_client import CoinbaseClient
from quantlab.data.health import HealthReport, preflight
from quantlab.data.reconcile import ReconcileReport, reconcile
from quantlab.data.store import ParquetStore
from quantlab.data.tiingo_client import TiingoClient
from quantlab.data.validate import ValidationReport, validate
from quantlab.logging_setup import get_logger
from quantlab.paper.runner import (
    PaperRunReport,
    migrate_legacy_state,
    run_all_strategies,
    run_paper,
)
from quantlab.reporting.alerts import send_test_alert
from quantlab.reporting.digest import build_digest, render_markdown, write_digest
from quantlab.reporting.weekly import (
    build_weekly_review,
    write_weekly_review,
)
from quantlab.reporting.weekly import (
    render_markdown as render_weekly_markdown,
)
from quantlab.risk.engine import RiskEngine
from quantlab.risk.limits import load_risk_limits
from quantlab.risk.state import load_risk_state, reset_risk_state, risk_state_path_for
from quantlab.scheduling import tasks as schedule_tasks
from quantlab.validation import (
    BootstrapReport,
    PerturbReport,
    WalkForwardReport,
    perturb,
    stationary_block_bootstrap,
    walk_forward,
)
from quantlab.version import VERSION, git_short_hash

log = get_logger("quantlab.cli")


def _parse_symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _selected_symbols(explicit: list[str] | None) -> list[str]:
    universe = load_universe()
    all_symbols = universe.symbols
    if explicit is None:
        return all_symbols
    unknown = [s for s in explicit if s not in all_symbols]
    if unknown:
        raise ConfigError(f"Symbols not in universe: {', '.join(unknown)}")
    return explicit


def cmd_ingest(args: argparse.Namespace) -> int:
    start = date.fromisoformat(args.start)
    symbols = _selected_symbols(_parse_symbols(args.symbols))

    settings = get_settings()
    settings.require_keys("TIINGO_API_KEY")
    assert settings.TIINGO_API_KEY is not None  # narrowed by require_keys

    client = TiingoClient(settings.TIINGO_API_KEY)
    store = ParquetStore()

    for symbol in symbols:
        df = client.fetch(symbol, start)
        rows_fetched = len(df)
        store.save_metadata(symbol, df.attrs.get("inception_date"), requested_start=start)
        merged = store.upsert(symbol, df)

        first_date = merged["date"].min()
        last_date = merged["date"].max()
        log.info(
            "ingest_symbol",
            symbol=symbol,
            rows_fetched=rows_fetched,
            rows_total=len(merged),
            first_date=first_date.date().isoformat() if rows_fetched else None,
            last_date=last_date.date().isoformat() if rows_fetched else None,
        )

    return 0


# Coinbase daily history begins in 2015-2016 depending on the product; 2016-01-01
# is a safe full-backfill floor (fetch clamps naturally to available candles).
CRYPTO_BACKFILL_START = "2016-01-01"

# On an incremental top-up, re-fetch a few days of overlap so a boundary day is
# never missed; the store's upsert is idempotent so the overlap is harmless.
_CRYPTO_INCREMENTAL_OVERLAP_DAYS = 3


def _selected_crypto_symbols(explicit: list[str] | None) -> list[str]:
    universe = load_crypto_universe()
    all_symbols = universe.symbols
    if explicit is None:
        return all_symbols
    unknown = [s for s in explicit if s not in all_symbols]
    if unknown:
        raise ConfigError(f"Symbols not in crypto universe: {', '.join(unknown)}")
    return explicit


def cmd_crypto_ingest(args: argparse.Namespace) -> int:
    symbols = _selected_crypto_symbols(_parse_symbols(args.symbols))
    default_start = date.fromisoformat(args.start)

    client = CoinbaseClient()
    store = ParquetStore()
    calendar = CryptoCalendar()
    now = datetime.now(UTC)

    reports: list[ValidationReport] = []
    for symbol in symbols:
        start = default_start
        if args.incremental and store.exists(symbol):
            existing = store.load(symbol)
            if not existing.empty:
                last = pd.to_datetime(existing["date"]).max().date()
                start = max(default_start, last - timedelta(days=_CRYPTO_INCREMENTAL_OVERLAP_DAYS))

        df = client.fetch_candles(symbol, start)
        rows_fetched = len(df)
        merged = store.upsert(symbol, df)

        # Preserve the earliest requested_start across incremental runs so the
        # coverage check is anchored to the original full-backfill request.
        prior = store.load_metadata(symbol)
        requested_start = default_start
        if prior is not None and prior.requested_start is not None:
            requested_start = min(prior.requested_start, default_start)
        inception = merged["date"].min().date() if len(merged) else None
        store.save_metadata(symbol, inception, requested_start=requested_start)

        log.info(
            "crypto_ingest_symbol",
            symbol=symbol,
            rows_fetched=rows_fetched,
            rows_total=len(merged),
            first_date=merged["date"].min().date().isoformat() if len(merged) else None,
            last_date=merged["date"].max().date().isoformat() if len(merged) else None,
        )

        # Crypto validation uses the 24/7 CryptoCalendar so weekends are not
        # flagged as missing sessions; genuinely absent UTC days still fail.
        report = validate(
            store.load(symbol), symbol,
            inception_date=inception, requested_start=requested_start,
            now=now, calendar=calendar,
        )
        reports.append(report)
        log.info("validation_report", **report.model_dump(mode="json"))

    _print_summary(reports)
    return 0 if all(r.passed for r in reports) else 1


def cmd_validate(args: argparse.Namespace) -> int:
    symbols = _selected_symbols(_parse_symbols(args.symbols))
    store = ParquetStore()
    now = datetime.now(UTC)

    reports: list[ValidationReport] = []
    for symbol in symbols:
        df = store.load(symbol)
        meta = store.load_metadata(symbol)
        inception = meta.inception_date if meta else None
        requested_start = meta.requested_start if meta else None
        report = validate(
            df, symbol, inception_date=inception, requested_start=requested_start, now=now
        )
        reports.append(report)
        log.info("validation_report", **report.model_dump(mode="json"))

    _print_summary(reports)
    return 0 if all(r.passed for r in reports) else 1


def _print_summary(reports: list[ValidationReport]) -> None:
    header = f"{'SYMBOL':<8}{'PASS':<6}{'ROWS':>8}  {'FIRST':<12}{'LAST':<12}{'STALE':>6}  {'W':>3}"
    print(header)
    print("-" * len(header))
    for r in reports:
        print(
            f"{r.symbol:<8}"
            f"{'OK' if r.passed else 'FAIL':<6}"
            f"{r.row_count:>8}  "
            f"{(r.first_date.isoformat() if r.first_date else '-'):<12}"
            f"{(r.last_date.isoformat() if r.last_date else '-'):<12}"
            f"{r.staleness_sessions:>6}  "
            f"{len(r.warnings):>3}"
        )
        for err in r.errors:
            print(f"    ERROR: {err}")
    failed = [r.symbol for r in reports if not r.passed]
    print("-" * len(header))
    print(f"{len(reports)} symbol(s), {len(failed)} failed"
          + (f": {', '.join(failed)}" if failed else ""))


def cmd_reconcile(args: argparse.Namespace) -> int:
    symbols = _selected_symbols(_parse_symbols(args.symbols))
    days = int(args.days)
    tolerance = float(args.tolerance)

    settings = get_settings()
    settings.require_keys("ALPACA_API_KEY", "ALPACA_SECRET_KEY")
    assert settings.ALPACA_API_KEY is not None  # narrowed by require_keys
    assert settings.ALPACA_SECRET_KEY is not None

    client = AlpacaDataClient(
        settings.ALPACA_API_KEY,
        settings.ALPACA_SECRET_KEY,
        base_trading_url=settings.ALPACA_BASE_URL,
    )
    store = ParquetStore()

    today = datetime.now(UTC).date()
    window_start = today - timedelta(days=days)

    reports: list[ReconcileReport] = []
    for symbol in symbols:
        tiingo_df = store.load(symbol, start=window_start)
        # Alpaca RAW bars vs Tiingo RAW close (see reconcile module docstring).
        alpaca_df = client.fetch_daily_bars(
            symbol, window_start, today, adjustment="raw", feed="iex"
        )
        report = reconcile(tiingo_df, alpaca_df, symbol, tolerance=tolerance)
        reports.append(report)
        log.info("reconcile_report", **report.model_dump(mode="json"))

    _print_reconcile_summary(reports)
    return 0 if all(r.passed for r in reports) else 1


def _print_reconcile_summary(reports: list[ReconcileReport]) -> None:
    header = (
        f"{'SYMBOL':<8}{'PASS':<6}{'OVERLAP':>9}{'MISM':>6}  "
        f"{'START':<12}{'END':<12}{'oT':>4}{'oA':>4}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        print(
            f"{r.symbol:<8}"
            f"{'OK' if r.passed else 'FAIL':<6}"
            f"{r.n_overlap:>9}"
            f"{r.n_mismatches:>6}  "
            f"{(r.overlap_start.isoformat() if r.overlap_start else '-'):<12}"
            f"{(r.overlap_end.isoformat() if r.overlap_end else '-'):<12}"
            f"{len(r.dates_only_in_tiingo):>4}"
            f"{len(r.dates_only_in_alpaca):>4}"
        )
        for err in r.errors:
            print(f"    ERROR: {err}")
    failed = [r.symbol for r in reports if not r.passed]
    print("-" * len(header))
    print(
        f"{len(reports)} symbol(s), {len(failed)} failed"
        + (f": {', '.join(failed)}" if failed else "")
    )


def cmd_health(args: argparse.Namespace) -> int:
    store = ParquetStore()
    calendar = TradingCalendar()
    now = datetime.now(UTC)

    settings = get_settings()
    clock = None
    if settings.ALPACA_API_KEY and settings.ALPACA_SECRET_KEY:
        client = AlpacaDataClient(
            settings.ALPACA_API_KEY,
            settings.ALPACA_SECRET_KEY,
            base_trading_url=settings.ALPACA_BASE_URL,
        )
        clock = client.fetch_clock()

    symbols = store.symbols()
    report = preflight(symbols, store, calendar, clock, now)
    log.info("health_report", **report.model_dump(mode="json"))

    _print_health(report)
    return 0 if report.data_fresh else 1


def _print_health(report: HealthReport) -> None:
    if report.market_open is None:
        market = "unknown"
    else:
        market = "OPEN" if report.market_open else "closed"
    print(f"Data health @ {report.generated_at.isoformat()}  (market: {market})")
    header = f"{'SYMBOL':<8}{'DATA':<6}{'LAST':<12}{'STALE':>6}"
    print(header)
    print("-" * len(header))
    for sh in report.symbols:
        stale = "n/a" if not sh.has_data else str(sh.staleness_sessions)
        print(
            f"{sh.symbol:<8}"
            f"{'yes' if sh.has_data else 'no':<6}"
            f"{(sh.last_date.isoformat() if sh.last_date else '-'):<12}"
            f"{stale:>6}"
        )
    print("-" * len(header))
    print(f"data_fresh: {report.data_fresh}")
    for reason in report.blocking_reasons:
        print(f"    BLOCKING: {reason}")


def _make_strategy(name: str, symbol: str = "SPY") -> Strategy:
    if name == "buyhold":
        return BuyAndHold(symbol=symbol)
    if name == "sixty40":
        return FixedWeights({"SPY": 0.6, "IEF": 0.4}, name="sixty40")
    if name == "trend":
        return TrendSMA10()
    if name == "dualmom":
        return DualMomentum()
    if name == "voltarget":
        return VolTarget()
    raise ConfigError(f"unknown strategy {name!r}")  # pragma: no cover


def _first_effective_signal(panel: pd.DataFrame, strategy: Strategy) -> pd.Timestamp | None:
    """First session on which the strategy's (warmed-up) signal takes effect."""
    dates = list(panel.index)
    pos = {d: i for i, d in enumerate(dates)}
    for r in strategy.rebalance_dates(dates):
        if strategy.is_warmed_up(panel.loc[:r], r):
            i = pos[r]
            return dates[i + 1] if i + 1 < len(dates) else r
    return None


def cmd_backtest(args: argparse.Namespace) -> int:
    store = ParquetStore()
    strategy = _make_strategy(args.strategy, symbol=args.symbol)
    required = strategy.required_symbols
    benchmark = args.benchmark

    panel_symbols = list(dict.fromkeys(strategy.all_symbols + ([benchmark] if benchmark else [])))
    panel = build_price_panel(store, panel_symbols, start=args.start)

    # First session on which every strategy-required symbol has a price.
    usable = panel[required].dropna()
    if usable.empty:
        raise ConfigError(f"no sessions where all of {required} have prices")
    first_usable = usable.index.min()
    panel = panel.loc[first_usable:]

    risk_engine = RiskEngine(load_risk_limits()) if getattr(args, "risk", False) else None
    # The benchmark column (if any) rides along with weight 0; the engine skips it.
    result = run_backtest(panel, strategy, cost_bps=args.cost_bps, risk_engine=risk_engine)
    first_signal = _first_effective_signal(panel, strategy)

    benchmark_returns = None
    if benchmark:
        benchmark_returns = returns_panel(panel)[benchmark].loc[result.daily_returns.index]

    metrics = compute_metrics(
        result.daily_returns,
        result.equity,
        benchmark_returns=benchmark_returns,
        # Sum over all columns (non-held are 0) for TRUE exposure, including any
        # time spent in the safe asset.
        weights=result.weights_history,
        turnover=result.turnover,
        costs=result.costs_paid,
    )

    log.info("backtest_metrics", strategy=strategy.name, **metrics.model_dump(mode="json"))
    print(f"panel first usable date: {first_usable.date().isoformat()}")
    signal_str = first_signal.date().isoformat() if first_signal is not None else "never"
    print(f"first effective signal date: {signal_str}")
    _print_metrics(strategy.name, metrics, benchmark)
    if risk_engine is not None:
        _print_risk_events(strategy.name, result.risk_events)
    _write_backtest_report(args.strategy, result.config, metrics)
    return 0


def _print_risk_events(name: str, events: list[dict]) -> None:
    print(f"--- RISK EVENTS: {name} ({len(events)}) ---")
    if not events:
        print("  (none)")
        return
    for e in events:
        print(f"  {e['date']}  {e['action']:<18} {e['reason']}")


def _print_metrics(name: str, metrics: Metrics, benchmark: str | None) -> None:
    def fmt(x: float | None, pct: bool = False) -> str:
        if x is None:
            return "n/a"
        return f"{x:.2%}" if pct else f"{x:.3f}"

    print(f"=== backtest: {name} ===")
    print(f"  period            {metrics.start} -> {metrics.end}  ({metrics.n_sessions} sessions)")
    print(f"  CAGR              {fmt(metrics.cagr, pct=True)}")
    print(f"  annualized vol    {fmt(metrics.annualized_vol, pct=True)}")
    print(f"  sharpe            {fmt(metrics.sharpe)}")
    print(f"  sortino           {fmt(metrics.sortino)}")
    print(f"  calmar            {fmt(metrics.calmar)}")
    print(f"  max drawdown      {fmt(metrics.max_drawdown, pct=True)}")
    print(f"  max dd duration   {metrics.max_drawdown_duration_days} sessions")
    print(f"  win rate monthly  {fmt(metrics.win_rate_monthly, pct=True)}")
    best_worst = f"{fmt(metrics.best_month, pct=True)} / {fmt(metrics.worst_month, pct=True)}"
    print(f"  best / worst mo   {best_worst}")
    print(f"  avg exposure      {fmt(metrics.exposure_avg, pct=True)}")
    print(f"  annual turnover   {fmt(metrics.annual_turnover)}")
    print(f"  total costs ($)   {metrics.total_costs:,.2f}")
    if benchmark:
        print(f"  benchmark ({benchmark})")
        print(f"    CAGR            {fmt(metrics.benchmark_cagr, pct=True)}")
        print(f"    max drawdown    {fmt(metrics.benchmark_max_drawdown, pct=True)}")


def _write_backtest_report(strategy_key: str, config: dict, metrics: Metrics) -> None:
    reports_dir = PROJECT_ROOT / "reports" / "backtests"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = reports_dir / f"{strategy_key}_{stamp}.json"
    payload = {
        "config": config,
        "metrics": metrics.model_dump(mode="json"),
        "monthly_returns": metrics.monthly_returns,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"report written: {path}")


# The five strategies compared, and the symbols any of them may reference.
_COMPARE_STRATEGIES = ["buyhold", "sixty40", "trend", "dualmom", "voltarget"]


def cmd_compare(args: argparse.Namespace) -> int:
    store = ParquetStore()
    strategies = [_make_strategy(name) for name in _COMPARE_STRATEGIES]

    # Symbols any strategy references, and those required to establish a start.
    all_symbols = list(dict.fromkeys(s for strat in strategies for s in strat.all_symbols))
    required = list(dict.fromkeys(s for strat in strategies for s in strat.required_symbols))

    panel = build_price_panel(store, all_symbols, start=args.start)
    usable = panel[required].dropna()
    if usable.empty:
        raise ConfigError(f"no common window where all of {required} have prices")
    # IDENTICAL date range for every strategy: the first date all required
    # symbols have prices (>= --start) through the last available session.
    common_start = usable.index.min()
    panel = panel.loc[common_start:]
    common_end = panel.index.max()

    risk_engine = RiskEngine(load_risk_limits()) if getattr(args, "risk", False) else None
    rows: list[tuple[str, Metrics]] = []
    events_by_strategy: list[tuple[str, list[dict]]] = []
    for strat in strategies:
        result = run_backtest(panel, strat, cost_bps=args.cost_bps, risk_engine=risk_engine)
        metrics = compute_metrics(
            result.daily_returns,
            result.equity,
            weights=result.weights_history,  # all columns -> true total exposure
            turnover=result.turnover,
            costs=result.costs_paid,
        )
        rows.append((strat.name, metrics))
        events_by_strategy.append((strat.name, result.risk_events))
        log.info("compare_metrics", strategy=strat.name, **metrics.model_dump(mode="json"))

    def _sharpe_key(row: tuple[str, Metrics]) -> float:
        return row[1].sharpe if row[1].sharpe is not None else float("-inf")

    rows.sort(key=_sharpe_key, reverse=True)

    window = (common_start.date().isoformat(), common_end.date().isoformat())
    print(f"common window (identical for all): {window[0]} -> {window[1]}  "
          f"({panel.shape[0]} sessions), cost_bps={args.cost_bps}")
    _print_compare_table(rows)
    if risk_engine is not None:
        for name, events in events_by_strategy:
            _print_risk_events(name, events)
    _write_compare_report(window, args.cost_bps, rows)
    return 0


def _print_compare_table(rows: list[tuple[str, Metrics]]) -> None:
    def f(x: float | None, pct: bool = False) -> str:
        if x is None:
            return "n/a"
        return f"{x:.1%}" if pct else f"{x:.2f}"

    header = (
        f"{'STRATEGY':<14}{'CAGR':>8}{'VOL':>8}{'SHARPE':>8}{'SORTINO':>9}"
        f"{'MAXDD':>9}{'CALMAR':>8}{'WIN_M':>8}{'ANN_TO':>8}{'COSTS$':>11}"
    )
    print(header)
    print("-" * len(header))
    for name, m in rows:
        print(
            f"{name:<14}"
            f"{f(m.cagr, pct=True):>8}"
            f"{f(m.annualized_vol, pct=True):>8}"
            f"{f(m.sharpe):>8}"
            f"{f(m.sortino):>9}"
            f"{f(m.max_drawdown, pct=True):>9}"
            f"{f(m.calmar):>8}"
            f"{f(m.win_rate_monthly, pct=True):>8}"
            f"{f(m.annual_turnover):>8}"
            f"{m.total_costs:>11,.2f}"
        )
    print("-" * len(header))
    print("(sorted by sharpe desc)")


def _write_compare_report(
    window: tuple[str, str], cost_bps: float, rows: list[tuple[str, Metrics]]
) -> None:
    reports_dir = PROJECT_ROOT / "reports" / "backtests"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = reports_dir / f"compare_{stamp}.json"
    payload = {
        "common_window": {"start": window[0], "end": window[1]},
        "cost_bps": cost_bps,
        "strategies": {name: m.model_dump(mode="json") for name, m in rows},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"report written: {path}")


def cmd_risk_show(args: argparse.Namespace) -> int:
    limits = load_risk_limits()
    print("=== RiskLimits (config/risk.yaml) ===")
    for field_name, value in limits.model_dump().items():
        print(f"  {field_name:<24} {value}")
    # One kill-switch state per account label; isolated from one another.
    for label in APPROVED_STRATEGIES:
        state = load_risk_state(risk_state_path_for(label))
        print(f"=== RiskState [{label}] (data/risk_state_{label}.json) ===")
        for field_name, value in state.model_dump(mode="json").items():
            print(f"  {field_name:<24} {value}")
    return 0


def cmd_risk_reset(args: argparse.Namespace) -> int:
    if args.strategy not in APPROVED_STRATEGIES:
        raise ConfigError(
            f"--strategy must be one of {list(APPROVED_STRATEGIES)}; got {args.strategy!r}"
        )
    if args.confirm != "YES":
        print("Refusing to reset: pass --confirm YES to clear a halted state.", file=sys.stderr)
        return 2
    cleared = reset_risk_state(risk_state_path_for(args.strategy))
    log.info(
        "risk_reset",
        strategy=args.strategy,
        was_halted=cleared.halted,
        reason=cleared.reason,
        required_manual_reset=cleared.requires_manual_reset,
    )
    if cleared.halted:
        print(f"[{args.strategy}] cleared halted state: reason={cleared.reason!r} "
              f"triggered_at={cleared.triggered_at} "
              f"requires_manual_reset={cleared.requires_manual_reset}")
    else:
        print(f"[{args.strategy}] no halted state was set; state is now clean.")
    return 0


_VALIDATE_STRATEGIES = ["trend", "dualmom", "voltarget"]


def _fmt_params(params: dict[str, float]) -> str:
    parts = []
    for key, val in params.items():
        shown = f"{val:g}" if val != int(val) else str(int(val))
        parts.append(f"{key}={shown}")
    return ", ".join(parts)


def _print_walkforward(name: str, wf: WalkForwardReport) -> None:
    def f(x: float | None, pct: bool = False) -> str:
        if x is None:
            return "n/a"
        return f"{x:.1%}" if pct else f"{x:.2f}"

    print(f"\n=== WALK-FORWARD: {name}  (window {wf.window_years}y, {wf.n_segments} segments) ===")
    header = f"{'SEGMENT':<26}{'CAGR':>9}{'SHARPE':>9}{'MAXDD':>9}{'TOTRET':>9}"
    print(header)
    print("-" * len(header))
    for s in wf.segments:
        label = f"{s.start.isoformat()} -> {s.end.isoformat()}"
        print(f"{label:<26}{f(s.cagr, pct=True):>9}{f(s.sharpe):>9}"
              f"{f(s.max_drawdown, pct=True):>9}{f(s.total_return, pct=True):>9}")
    print("-" * len(header))
    print(f"  segments positive return : {f(wf.pct_segments_positive_return, pct=True)}")
    print(f"  segments beat cash (>0)  : {f(wf.pct_segments_beat_cash, pct=True)}")
    print(f"  sharpe min/median/max    : {f(wf.sharpe_min)} / "
          f"{f(wf.sharpe_median)} / {f(wf.sharpe_max)}")


def _print_perturb(name: str, pt: PerturbReport) -> None:
    def f(x: float | None, pct: bool = False) -> str:
        if x is None:
            return "n/a"
        return f"{x:.1%}" if pct else f"{x:.2f}"

    print(f"\n=== PERTURBATION GRID: {name}  (REPORT-ONLY - baseline stands regardless) ===")
    header = f"{'':<2}{'PARAMS':<32}{'CAGR':>9}{'SHARPE':>9}{'MAXDD':>9}"
    print(header)
    print("-" * len(header))
    for g in pt.grid:
        mark = "* " if g.is_baseline else "  "
        print(f"{mark}{_fmt_params(g.params):<32}{f(g.cagr, pct=True):>9}"
              f"{f(g.sharpe):>9}{f(g.max_drawdown, pct=True):>9}")
    print("-" * len(header))
    print("  (* = literature baseline)")
    verdict = "FRAGILE" if pt.fragility_flag else "ROBUST"
    print(f"  fragility verdict: {verdict} - {pt.fragility_reason}")


def _print_bootstrap(name: str, bs: BootstrapReport) -> None:
    print(f"\n=== BLOCK BOOTSTRAP: {name}  (n={bs.n_samples}, block~{bs.avg_block_len}, "
          f"seed={bs.seed}, len={bs.sample_length}) ===")
    header = f"{'METRIC':<16}{'P5':>10}{'P50':>10}{'P95':>10}"
    print(header)
    print("-" * len(header))
    print(f"{'CAGR':<16}{bs.cagr_p5:>10.1%}{bs.cagr_p50:>10.1%}{bs.cagr_p95:>10.1%}")
    print(f"{'Sharpe':<16}{bs.sharpe_p5:>10.2f}{bs.sharpe_p50:>10.2f}{bs.sharpe_p95:>10.2f}")
    print(f"{'MaxDrawdown':<16}{bs.max_drawdown_p5:>10.1%}"
          f"{bs.max_drawdown_p50:>10.1%}{bs.max_drawdown_p95:>10.1%}")
    print("-" * len(header))
    print(f"  P(CAGR < 0)          : {bs.prob_negative_cagr:.1%}")
    print(f"  P(MaxDD worse -30%)  : {bs.prob_drawdown_worse_than_30pct:.1%}")


def _write_validation_report(
    strategy_key: str,
    start: str | None,
    cost_bps: float,
    seed: int,
    wf: WalkForwardReport,
    pt: PerturbReport,
    bs: BootstrapReport,
) -> None:
    reports_dir = PROJECT_ROOT / "reports" / "validation"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = reports_dir / f"{strategy_key}_{stamp}.json"
    payload = {
        "strategy": strategy_key,
        "start": start,
        "cost_bps": cost_bps,
        "seed": seed,
        "walk_forward": wf.model_dump(mode="json"),
        "perturbation": pt.model_dump(mode="json"),
        "bootstrap": bs.model_dump(mode="json"),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nreport written: {path}")


def cmd_validate_strategy(args: argparse.Namespace) -> int:
    if args.strategy not in _VALIDATE_STRATEGIES:
        raise ConfigError(
            f"validate-strategy supports {_VALIDATE_STRATEGIES}; got {args.strategy!r}"
        )
    store = ParquetStore()
    strategy = _make_strategy(args.strategy)
    panel = build_price_panel(store, strategy.all_symbols, start=args.start)
    usable = panel[strategy.required_symbols].dropna()
    if usable.empty:
        raise ConfigError(f"no sessions where all of {strategy.required_symbols} have prices")
    panel = panel.loc[usable.index.min():]

    wf = walk_forward(panel, lambda: _make_strategy(args.strategy), cost_bps=args.cost_bps)
    pt = perturb(args.strategy, panel, cost_bps=args.cost_bps)
    result = run_backtest(panel, strategy, cost_bps=args.cost_bps)
    bs = stationary_block_bootstrap(result.daily_returns, seed=args.seed)

    log.info("walk_forward", strategy=args.strategy, **wf.model_dump(mode="json"))
    log.info("perturbation", **pt.model_dump(mode="json"))  # dump already carries strategy
    log.info("bootstrap", strategy=args.strategy, **bs.model_dump(mode="json"))

    print(f"validation battery for '{strategy.name}'  "
          f"(panel {panel.index.min().date()} -> {panel.index.max().date()}, "
          f"{panel.shape[0]} sessions)")
    _print_walkforward(strategy.name, wf)
    _print_perturb(strategy.name, pt)
    _print_bootstrap(strategy.name, bs)
    _write_validation_report(args.strategy, args.start, args.cost_bps, args.seed, wf, pt, bs)
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    store = ParquetStore()
    calendar = TradingCalendar()
    now = datetime.now(UTC)

    # One broker per approved account; absent keys -> None (rendered as skipped).
    brokers: dict[str, AlpacaTradingClient | None] = {}
    for label in APPROVED_STRATEGIES:
        try:
            brokers[label], _ = _trading_client_for(label)
        except ConfigError:
            brokers[label] = None

    digest = build_digest(brokers, store, calendar, now)
    md_path, json_path = write_digest(digest)
    print(render_markdown(digest))
    print(f"\ndigest written: {md_path}")
    print(f"digest written: {json_path}")

    if args.send_test_alert:
        results = send_test_alert()
        active = [r.channel for r in results if r.ok]
        failed = [f"{r.channel} ({r.error})" for r in results if not r.ok]
        print("\ntest alert dispatched.")
        print("  active channels: " + (", ".join(active) if active else "(none)"))
        if failed:
            print("  failed channels: " + ", ".join(failed))
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    short = git_short_hash()
    provenance = f"git {short}" if short else "git hash unavailable"
    print(f"quantlab {VERSION} ({provenance})")
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    store = ParquetStore()
    calendar = TradingCalendar()
    now = datetime.now(UTC)

    week_ending: date | None = None
    if args.week_ending:
        week_ending = date.fromisoformat(args.week_ending)

    # One broker per approved account; absent keys -> None (rendered as skipped).
    brokers: dict[str, AlpacaTradingClient | None] = {}
    for label in APPROVED_STRATEGIES:
        try:
            brokers[label], _ = _trading_client_for(label)
        except ConfigError:
            brokers[label] = None

    review = build_weekly_review(brokers, store, calendar, now, week_ending)
    md_path, json_path = write_weekly_review(review)
    print(render_weekly_markdown(review))
    print(f"\nweekly review written: {md_path}")
    print(f"weekly review written: {json_path}")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    if args.schedule_command == "install":
        return schedule_tasks.install(args.confirm)
    if args.schedule_command == "uninstall":
        return schedule_tasks.uninstall()
    if args.schedule_command == "show":
        return schedule_tasks.show()
    raise ConfigError(f"unknown schedule command {args.schedule_command!r}")  # pragma: no cover


def _trading_client_for(strategy: str) -> tuple[AlpacaTradingClient, str]:
    """Build the paper broker for ``strategy``'s dedicated account (never falls back)."""
    creds = account_for(strategy)
    client = AlpacaTradingClient(creds.api_key, creds.secret_key, base_url=creds.base_url)
    return client, creds.label


def _clock_for(label: str) -> object | None:
    """Read-only market clock via this account's keys (sharpens health preflight)."""
    creds = account_for(label)
    data_client = AlpacaDataClient(
        creds.api_key, creds.secret_key, base_trading_url=creds.base_url
    )
    return data_client.fetch_clock()


def _paper_ingest_fn(symbols: list[str], store: ParquetStore) -> None:
    """Top up recent bars for ``symbols`` (reuses the Tiingo ingest path)."""
    settings = get_settings()
    settings.require_keys("TIINGO_API_KEY")
    assert settings.TIINGO_API_KEY is not None
    client = TiingoClient(settings.TIINGO_API_KEY)
    today = datetime.now(UTC).date()
    for symbol in symbols:
        existing = store.load(symbol)
        if len(existing):
            start = existing["date"].max().date() - timedelta(days=5)
        else:
            start = today - timedelta(days=400)
        df = client.fetch(symbol, start)
        store.save_metadata(symbol, df.attrs.get("inception_date"), requested_start=start)
        store.upsert(symbol, df)


def _print_paper_report(report: PaperRunReport) -> None:
    mode = "DRY-RUN" if report.dry_run else "SUBMIT"
    print(f"=== PAPER RUN: {report.strategy}  ({mode})  @ {report.timestamp.isoformat()} ===")
    for s in report.stages:
        print(f"  [{'OK' if s.ok else 'XX'}] {s.stage:<18} {s.detail}")
    if report.aborted:
        print(f"\nABORTED at '{report.abort_stage}': {report.abort_reason}")
        return
    if report.equity is not None:
        print(f"\n  account equity : {report.equity:,.2f}")
    print(f"  target weights : {report.target_weights}")
    if report.no_trades:
        print("  result         : in-band, no trades")
        return
    plan = report.plan
    if plan is not None:
        print(f"\n  PLAN (sells first, buy_scale={plan.buy_scale:.4f}, "
              f"turnover={plan.est_turnover:.4f}):")
        for intent in plan.intents:
            print(f"    {intent.side:<4} {intent.symbol:<6} ${intent.notional:>12,.2f}  "
                  f"({intent.current_w:.3f} -> {intent.target_w:.3f})")
        for sk in plan.skipped:
            print(f"    skip {sk.symbol:<6} diff {sk.diff:+.4f} (<= {plan.min_trade_frac})")
    if report.submitted_orders:
        print("\n  SUBMITTED ORDERS:")
        for o in report.submitted_orders:
            dup = "  [DUPLICATE]" if o.was_duplicate else ""
            print(f"    {o.side:<4} {o.symbol:<6} id={o.id} coid={o.client_order_id} "
                  f"status={o.status}{dup}")
    elif not report.dry_run:
        print("\n  (no orders submitted)")


def _run_one_paper(strategy: str, submit: bool) -> int:
    """Run one strategy in ITS OWN account with per-label state isolation."""
    broker, label = _trading_client_for(strategy)
    clock = _clock_for(strategy)
    report = run_paper(
        strategy,
        dry_run=not submit,
        store=ParquetStore(),
        broker=broker,
        ingest_fn=_paper_ingest_fn,
        clock=clock,  # type: ignore[arg-type]
        risk_state_path=risk_state_path_for(label),
        equity_history_path=None,  # runner derives equity_history_{label}.parquet
    )
    _print_paper_report(report)
    return 1 if report.aborted else 0


def cmd_paper_run(args: argparse.Namespace) -> int:
    return _run_one_paper(args.strategy, args.submit)


def cmd_paper_run_all(args: argparse.Namespace) -> int:
    return run_all_strategies(
        list(APPROVED_STRATEGIES),
        lambda strategy: _run_one_paper(strategy, args.submit),
    )


def _print_account_status(label: str, today: date) -> None:
    print(f"\n========== account: {label} ==========")
    try:
        broker, _ = _trading_client_for(label)
    except ConfigError as exc:
        print(f"  (skipped: {exc})")
        return
    account = broker.get_account()
    positions = broker.get_positions()
    orders = broker.get_orders(status="all", after=today)
    state = load_risk_state(risk_state_path_for(label))

    print(f"  equity  : {account.equity:,.2f} {account.currency}")
    print(f"  cash    : {account.cash:,.2f} {account.currency}")
    print(f"  blocked : account={account.account_blocked} trading={account.trading_blocked}")
    print("  positions:")
    if not positions:
        print("    (none)")
    for p in positions:
        print(f"    {p.symbol:<6} qty={p.qty:<12g} mv=${p.market_value:,.2f} "
              f"avg=${p.avg_entry_price:,.2f}")
    print(f"  today's orders ({today.isoformat()}):")
    if not orders:
        print("    (none)")
    for o in orders:
        print(f"    {o.side:<4} {o.symbol:<6} status={o.status:<12} coid={o.client_order_id}")
    print(f"  risk state: halted={state.halted} reason={state.reason!r} "
          f"requires_manual_reset={state.requires_manual_reset}")


def cmd_paper_status(args: argparse.Namespace) -> int:
    today = datetime.now(UTC).date()
    labels = list(APPROVED_STRATEGIES) if args.strategy == "all" else [args.strategy]
    for label in labels:
        _print_account_status(label, today)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantlab", description="quantlab data CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_version = sub.add_parser("version", help="print the quantlab version + git short hash")
    p_version.set_defaults(func=cmd_version)

    p_ingest = sub.add_parser("ingest", help="fetch EOD data from Tiingo into the store")
    p_ingest.add_argument("--start", required=True, help="ISO start date, e.g. 2000-01-01")
    p_ingest.add_argument("--symbols", default=None, help="comma-separated symbols (default: all)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_crypto = sub.add_parser(
        "crypto-ingest", help="fetch daily crypto candles from Coinbase into the store"
    )
    p_crypto.add_argument(
        "--start", default=CRYPTO_BACKFILL_START,
        help=f"ISO start date for a full backfill (default {CRYPTO_BACKFILL_START})",
    )
    p_crypto.add_argument(
        "--symbols", default=None,
        help="comma-separated Coinbase product ids (default: all crypto, e.g. BTC-USD,ETH-USD)",
    )
    p_crypto.add_argument(
        "--incremental", action="store_true",
        help="top up from each symbol's last stored day instead of a full backfill",
    )
    p_crypto.set_defaults(func=cmd_crypto_ingest)

    p_validate = sub.add_parser("validate", help="validate stored EOD data")
    p_validate.add_argument("--symbols", default=None, help="comma-separated symbols (default all)")
    p_validate.set_defaults(func=cmd_validate)

    p_reconcile = sub.add_parser("reconcile", help="reconcile stored data against Alpaca IEX")
    p_reconcile.add_argument("--symbols", default=None, help="comma-separated symbols (all)")
    p_reconcile.add_argument("--days", default=400, type=int, help="lookback window in days")
    p_reconcile.add_argument(
        "--tolerance", default=0.0075, type=float, help="relative close tolerance"
    )
    p_reconcile.set_defaults(func=cmd_reconcile)

    p_health = sub.add_parser("health", help="data-health preflight over stored symbols")
    p_health.set_defaults(func=cmd_health)

    p_bt = sub.add_parser("backtest", help="run a baseline strategy backtest")
    p_bt.add_argument(
        "--strategy",
        required=True,
        choices=["buyhold", "sixty40", "trend", "dualmom", "voltarget"],
    )
    p_bt.add_argument("--symbol", default="SPY", help="symbol for buyhold (default SPY)")
    p_bt.add_argument("--start", default=None, help="ISO start date, e.g. 2000-01-01")
    p_bt.add_argument("--cost-bps", dest="cost_bps", default=5.0, type=float)
    p_bt.add_argument("--benchmark", default=None, help="benchmark symbol (e.g. SPY)")
    p_bt.add_argument("--risk", action="store_true", help="apply the risk overlay")
    p_bt.set_defaults(func=cmd_backtest)

    p_cmp = sub.add_parser("compare", help="compare all baseline+tactical strategies")
    p_cmp.add_argument("--start", default="2003-01-01", help="ISO start date")
    p_cmp.add_argument("--cost-bps", dest="cost_bps", default=5.0, type=float)
    p_cmp.add_argument("--risk", action="store_true", help="apply the risk overlay")
    p_cmp.set_defaults(func=cmd_compare)

    p_val = sub.add_parser(
        "validate-strategy",
        help="report-only validation battery (walk-forward, perturbation, bootstrap)",
    )
    p_val.add_argument("--strategy", required=True, choices=_VALIDATE_STRATEGIES)
    p_val.add_argument("--start", default="2003-01-01", help="ISO start date")
    p_val.add_argument("--cost-bps", dest="cost_bps", default=5.0, type=float)
    p_val.add_argument("--seed", default=42, type=int, help="bootstrap RNG seed")
    p_val.set_defaults(func=cmd_validate_strategy)

    p_digest = sub.add_parser("digest", help="build + write the daily paper digest")
    p_digest.add_argument(
        "--send-test-alert", action="store_true", dest="send_test_alert",
        help="dispatch a test alert through all active channels",
    )
    p_digest.set_defaults(func=cmd_digest)

    p_weekly = sub.add_parser(
        "weekly", help="build + write the weekly paper-vs-shadow review (report-only)"
    )
    p_weekly.add_argument(
        "--week-ending", default=None, dest="week_ending",
        help="week-ending date YYYY-MM-DD (defaults to today)",
    )
    p_weekly.set_defaults(func=cmd_weekly)

    p_sched = sub.add_parser("schedule", help="install/uninstall scheduled paper tasks")
    sched_sub = p_sched.add_subparsers(dest="schedule_command", required=True)
    p_sched_install = sched_sub.add_parser(
        "install",
        help="create the paper-run + digest + weekly tasks (needs --confirm YES)",
    )
    p_sched_install.add_argument("--confirm", default=None, help="must be exactly YES")
    p_sched_install.set_defaults(func=cmd_schedule)
    p_sched_uninstall = sched_sub.add_parser(
        "uninstall", help="remove the scheduled tasks (idempotent)"
    )
    p_sched_uninstall.set_defaults(func=cmd_schedule)
    p_sched_show = sched_sub.add_parser("show", help="query the scheduled tasks")
    p_sched_show.set_defaults(func=cmd_schedule)

    p_paper = sub.add_parser("paper", help="paper-trading (paper-only, risk-gated)")
    paper_sub = p_paper.add_subparsers(dest="paper_command", required=True)
    p_paper_run = paper_sub.add_parser("run", help="run the gated rebalance pipeline")
    p_paper_run.add_argument("--strategy", required=True, choices=["voltarget", "trend"])
    p_paper_run.add_argument(
        "--submit", action="store_true",
        help="submit REAL paper orders (default is dry-run: plan only)",
    )
    p_paper_run.set_defaults(func=cmd_paper_run)
    p_paper_run_all = paper_sub.add_parser(
        "run-all", help="run every approved strategy in its own account, in order"
    )
    p_paper_run_all.add_argument(
        "--submit", action="store_true",
        help="submit REAL paper orders (default is dry-run: plan only)",
    )
    p_paper_run_all.set_defaults(func=cmd_paper_run_all)
    p_paper_status = paper_sub.add_parser("status", help="per-account status (all by default)")
    p_paper_status.add_argument(
        "--strategy", default="all", choices=["all", "voltarget", "trend"],
        help="which account(s) to show (default all)",
    )
    p_paper_status.set_defaults(func=cmd_paper_status)

    p_risk = sub.add_parser("risk", help="risk-engine limits and kill-switch state")
    risk_sub = p_risk.add_subparsers(dest="risk_command", required=True)
    p_risk_show = risk_sub.add_parser("show", help="print RiskLimits and RiskState")
    p_risk_show.set_defaults(func=cmd_risk_show)
    p_risk_reset = risk_sub.add_parser("reset", help="clear a halted state (needs --confirm YES)")
    p_risk_reset.add_argument(
        "--strategy", required=True, choices=list(APPROVED_STRATEGIES),
        help="which account's kill-switch to clear",
    )
    p_risk_reset.add_argument("--confirm", default=None, help="must be exactly YES")
    p_risk_reset.set_defaults(func=cmd_risk_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file()  # make .env visible to os.environ readers (e.g. SMTP alerts)
    migrate_legacy_state()  # one-time rename of Batch-9 single-account state files
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except ConfigError as exc:
        log.error("config_error", error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
