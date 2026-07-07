"""quantlab command-line interface.

Subcommands:
    quantlab ingest --start 2000-01-01 [--symbols SPY,QQQ]
    quantlab validate [--symbols SPY,QQQ]

The Tiingo API key is read via Settings.require_keys and is never logged.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

from quantlab.config import ConfigError, get_settings, load_universe
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
