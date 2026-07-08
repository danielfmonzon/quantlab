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
from datetime import UTC, date, datetime, timedelta

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.metrics import Metrics, compute_metrics
from quantlab.backtest.panel import build_price_panel, returns_panel
from quantlab.backtest.strategy import BuyAndHold, FixedWeights, Strategy
from quantlab.config import ConfigError, get_settings, load_universe
from quantlab.constants import PROJECT_ROOT
from quantlab.data.alpaca_client import AlpacaDataClient
from quantlab.data.calendar import TradingCalendar
from quantlab.data.health import HealthReport, preflight
from quantlab.data.reconcile import ReconcileReport, reconcile
from quantlab.data.store import ParquetStore
from quantlab.data.tiingo_client import TiingoClient
from quantlab.data.validate import ValidationReport, validate
from quantlab.logging_setup import get_logger

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


def cmd_backtest(args: argparse.Namespace) -> int:
    store = ParquetStore()

    if args.strategy == "buyhold":
        strategy: Strategy = BuyAndHold(symbol=args.symbol)
        required = [args.symbol]
    elif args.strategy == "sixty40":
        strategy = FixedWeights({"SPY": 0.6, "IEF": 0.4}, name="sixty40")
        required = ["SPY", "IEF"]
    else:  # pragma: no cover - argparse choices guard this
        raise ConfigError(f"unknown strategy {args.strategy!r}")

    benchmark = args.benchmark
    panel_symbols = list(dict.fromkeys(required + ([benchmark] if benchmark else [])))

    panel = build_price_panel(store, panel_symbols, start=args.start)
    # First session on which every strategy-required symbol has a price.
    usable = panel[required].dropna()
    if usable.empty:
        raise ConfigError(f"no sessions where all of {required} have prices")
    first_usable = usable.index.min()
    panel = panel.loc[first_usable:]

    # The benchmark column (if any) rides along with weight 0; the engine skips it.
    result = run_backtest(panel, strategy, cost_bps=args.cost_bps)

    benchmark_returns = None
    if benchmark:
        benchmark_returns = returns_panel(panel)[benchmark].loc[result.daily_returns.index]

    metrics = compute_metrics(
        result.daily_returns,
        result.equity,
        benchmark_returns=benchmark_returns,
        weights=result.weights_history[required],
        turnover=result.turnover,
        costs=result.costs_paid,
    )

    log.info("backtest_metrics", strategy=strategy.name, **metrics.model_dump(mode="json"))
    print(f"panel first usable date: {first_usable.date().isoformat()}")
    _print_metrics(strategy.name, metrics, benchmark)
    _write_backtest_report(args.strategy, result.config, metrics)
    return 0


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantlab", description="quantlab data CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="fetch EOD data from Tiingo into the store")
    p_ingest.add_argument("--start", required=True, help="ISO start date, e.g. 2000-01-01")
    p_ingest.add_argument("--symbols", default=None, help="comma-separated symbols (default: all)")
    p_ingest.set_defaults(func=cmd_ingest)

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
    p_bt.add_argument("--strategy", required=True, choices=["buyhold", "sixty40"])
    p_bt.add_argument("--symbol", default="SPY", help="symbol for buyhold (default SPY)")
    p_bt.add_argument("--start", default=None, help="ISO start date, e.g. 2000-01-01")
    p_bt.add_argument("--cost-bps", dest="cost_bps", default=5.0, type=float)
    p_bt.add_argument("--benchmark", default=None, help="benchmark symbol (e.g. SPY)")
    p_bt.set_defaults(func=cmd_backtest)

    return parser


def main(argv: list[str] | None = None) -> int:
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
