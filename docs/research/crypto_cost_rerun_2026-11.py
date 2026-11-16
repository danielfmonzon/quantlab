"""Report-only re-run of the crypto backtests at the measured fee rate.

Produces every figure in docs/research/crypto_cost_rerun_2026-11.md. Costs are passed
to run_backtest as arguments here and nowhere else: no default, strategy, risk file or
price store is changed. Results go to the --out JSON path and nothing else is written,
except that --fresh-eod-dir builds a separate price store in the directory it names.

    uv run python docs/research/crypto_cost_rerun_2026-11.py \
        --out results.json --fresh-eod-dir <empty scratch dir>

Inputs: data/eod/BTCUSD.parquet, reports/backtests and reports/validation (local,
gitignored, the 2026-07-11 records), and the committed run snapshot at
frontend/public/snapshot/api-runs--label-crypto_voltarget.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from quantlab.backtest.engine import BacktestResult, run_backtest
from quantlab.backtest.metrics import compute_metrics
from quantlab.backtest.panel import build_price_panel
from quantlab.backtest.strategies.crypto_trend import CryptoTrendBTC
from quantlab.backtest.strategies.crypto_voltarget import CryptoVolTargetBTC
from quantlab.backtest.strategy import Strategy
from quantlab.cli import _first_effective_signal, _make_strategy
from quantlab.data.coinbase_client import CoinbaseClient
from quantlab.data.store import ParquetStore
from quantlab.risk.engine import RiskEngine
from quantlab.risk.limits import load_risk_limits
from quantlab.validation.bootstrap import (
    _resample_indices,
    _sample_metrics,
    stationary_block_bootstrap,
)

REPO = Path(__file__).resolve().parents[2]
SYMBOL = "BTC-USD"
PPY = 365
COSTS = (5.0, 24.1, 30.0)
RECORD_COST = 25.0
RECORD_END = "2026-07-11"
CLOCK_START = "2026-07-22"
LIVE_FEE_BPS = 24.1
MIN_TRADE_FRAC = 0.01  # the live planner's min_trade_frac, used only to count trades
THRESHOLDS = (0.25, 0.30, 0.50)
SEED, N_SAMPLES, BLOCK = 42, 1000, 20  # validate-strategy's bootstrap settings

RECORDS = {
    "ungated": REPO / "reports/backtests/crypto_compare_20260711T231931Z.json",
    "overlay_equity_yaml": REPO / "reports/backtests/crypto_compare_20260711T231901Z.json",
}
BOOTSTRAP_RECORDS = {
    "crypto_trend_btc": REPO / "reports/validation/crypto_trend_btc_20260711T233053Z.json",
    "crypto_voltarget_btc": REPO / "reports/validation/crypto_voltarget_btc_20260711T233120Z.json",
}
SNAPSHOT = REPO / "frontend/public/snapshot/api-runs--label-crypto_voltarget.json"
DUALMOM_RECORD = REPO / "reports/validation/dualmom_20260709T124619Z.json"
DUALMOM_RECORD_END = "2026-07-07"  # 5,914 bars gives the record's 5,913 returns


def strategies() -> list[Strategy]:
    return [CryptoTrendBTC(), CryptoVolTargetBTC()]


def eval_start(panel: pd.DataFrame) -> pd.Timestamp:
    """The crypto-backtest window: the later of the two strategies' first effective signal."""
    return max(_first_effective_signal(panel, strat) for strat in strategies())


def literal_turnover(result: BacktestResult, start: pd.Timestamp, end: pd.Timestamp | None = None):
    """Traded value / average equity / years, and the engine's sum(|dw|) / years."""
    turnover = result.turnover.loc[start:end]
    equity = result.equity.loc[start:end]
    # costs_paid is cost * e_drift; rebuild traded dollars from weight turnover directly
    # so the figure is defined at zero cost too. Equity after cost differs by < 0.1%.
    traded = float((turnover * equity).sum())
    years = len(turnover) / PPY
    return traded / float(equity.mean()) / years, float(turnover.sum()) / years, traded


def row(result: BacktestResult, strat: Strategy, start: pd.Timestamp) -> dict:
    m = compute_metrics(
        result.daily_returns.loc[start:],
        result.equity.loc[start:],
        weights=result.weights_history.loc[start:],
        turnover=result.turnover.loc[start:],
        costs=result.costs_paid.loc[start:],
        periods_per_year=strat.periods_per_year,
    )
    turn = result.turnover.loc[start:]
    literal, engine, _ = literal_turnover(result, start)
    return {
        "start": str(m.start),
        "end": str(m.end),
        "bars": m.n_sessions,
        "trades_any": int((turn > 1e-9).sum()),
        "trades_ge_1pct": int((turn >= MIN_TRADE_FRAC).sum()),
        "annual_turnover_literal": literal,
        "annual_turnover_engine": engine,
        "total_turnover": float(turn.sum()),
        "ann_return": m.cagr,
        "ann_vol": m.annualized_vol,
        "sharpe": m.sharpe,
        "max_drawdown": m.max_drawdown,
        "exposure_avg": m.exposure_avg,
        "risk_events": len(result.risk_events),
        "first_kill": next(
            (e["date"] for e in result.risk_events if e["action"] == "KILL_DRAWDOWN"), None
        ),
    }


def grid(panel: pd.DataFrame, costs, limits=None) -> dict:
    start = eval_start(panel)
    out: dict = {}
    for strat in strategies():
        out[strat.name] = {}
        for cost in costs:
            engine = RiskEngine(limits) if limits is not None else None
            res = run_backtest(panel, strat, cost_bps=cost, risk_engine=engine)
            out[strat.name][str(cost)] = row(res, strat, start)
    return out


def bootstrap(panel: pd.DataFrame, costs) -> dict:
    """Same resampling, seed and sample as validate-strategy; adds the thresholds.

    stationary_block_bootstrap reports only the -30% tail. The loop replays its RNG
    stream to read other thresholds, and is asserted equal to it at -30%.
    """
    out: dict = {}
    for strat in strategies():
        out[strat.name] = {}
        for cost in costs:
            returns = run_backtest(panel, strat, cost_bps=cost).daily_returns
            report = stationary_block_bootstrap(
                returns, seed=SEED, n_samples=N_SAMPLES, avg_block_len=BLOCK,
                periods_per_year=strat.periods_per_year,
            )
            clean = returns.dropna().to_numpy(dtype=float)
            rng = np.random.default_rng(SEED)
            dds = np.empty(N_SAMPLES)
            for i in range(N_SAMPLES):
                idx = _resample_indices(len(clean), 1.0 / BLOCK, rng)
                dds[i] = _sample_metrics(clean[idx], strat.periods_per_year)[2]
            replay = float(np.mean(dds < -0.30))
            assert replay == report.prob_drawdown_worse_than_30pct, (replay, report)
            out[strat.name][str(cost)] = {
                **{f"prob_dd_worse_{int(t * 100)}": float(np.mean(dds < -t)) for t in THRESHOLDS},
                "sample_length": report.sample_length,
                "max_drawdown_p5": report.max_drawdown_p5,
                "max_drawdown_p50": report.max_drawdown_p50,
                "max_drawdown_p95": report.max_drawdown_p95,
                "cagr_p50": report.cagr_p50,
                "sharpe_p50": report.sharpe_p50,
                "prob_negative_cagr": report.prob_negative_cagr,
            }
    return out


def reproduction(panel: pd.DataFrame) -> dict:
    """Re-run the 2026-07-11 records at their own cost and end date; report differences."""
    truncated = panel.loc[:RECORD_END]
    start = eval_start(truncated)
    out: dict = {"backtest": {}, "bootstrap": {}}
    for mode, path in RECORDS.items():
        record = json.loads(path.read_text(encoding="utf-8"))
        out["backtest"][mode] = {"record_file": path.name, "cost_bps": record["cost_bps"]}
        for strat in strategies():
            engine = RiskEngine(load_risk_limits()) if mode != "ungated" else None
            res = run_backtest(truncated, strat, cost_bps=RECORD_COST, risk_engine=engine)
            mine = row(res, strat, start)
            theirs = record["strategies"][strat.name]
            theirs = theirs.get("metrics", theirs)
            pairs = {
                "cagr": (theirs["cagr"], mine["ann_return"]),
                "annualized_vol": (theirs["annualized_vol"], mine["ann_vol"]),
                "sharpe": (theirs["sharpe"], mine["sharpe"]),
                "max_drawdown": (theirs["max_drawdown"], mine["max_drawdown"]),
                "annual_turnover": (theirs["annual_turnover"], mine["annual_turnover_engine"]),
                "n_sessions": (theirs["n_sessions"], mine["bars"]),
            }
            out["backtest"][mode][strat.name] = {
                k: {"record": a, "rerun": b, "diff": b - a} for k, (a, b) in pairs.items()
            }
            months = (1.0 + res.daily_returns.loc[start:]).groupby(
                res.daily_returns.loc[start:].index.to_period("M")
            ).prod() - 1.0
            differing = {
                str(m): (theirs["monthly_returns"][str(m)], float(v))
                for m, v in months.items()
                if abs(theirs["monthly_returns"][str(m)] - v) > 1e-12
            }
            out["backtest"][mode][strat.name]["months_compared"] = len(months)
            out["backtest"][mode][strat.name]["months_differing"] = differing
            out["backtest"][mode][strat.name]["last_bar_weight"] = float(
                res.weights_history.iloc[-2].sum()
            )
    boot = bootstrap(truncated, (RECORD_COST,))
    for strat in strategies():
        record = json.loads(BOOTSTRAP_RECORDS[strat.name].read_text(encoding="utf-8"))
        theirs, mine = record["bootstrap"], boot[strat.name][str(RECORD_COST)]
        out["bootstrap"][strat.name] = {
            "record_file": BOOTSTRAP_RECORDS[strat.name].name,
            "cost_bps": record["cost_bps"],
            "sample_length": (theirs["sample_length"], mine["sample_length"]),
            "prob_dd_worse_30": (
                theirs["prob_drawdown_worse_than_30pct"], mine["prob_dd_worse_30"]
            ),
            "max_drawdown_p50": (theirs["max_drawdown_p50"], mine["max_drawdown_p50"]),
            "cagr_p50": (theirs["cagr_p50"], mine["cagr_p50"]),
            "sharpe_p50": (theirs["sharpe_p50"], mine["sharpe_p50"]),
        }
    out["dualmom"] = dualmom_on_record()
    return out


def dualmom_on_record() -> dict:
    """The one bootstrap figure stated in docs/ (72.2%, Sharpe ~0.60), at its 5.0 bps."""
    record = json.loads(DUALMOM_RECORD.read_text(encoding="utf-8"))
    strat = _make_strategy("dualmom")
    panel = build_price_panel(
        ParquetStore(), strat.all_symbols, start=record["start"], end=DUALMOM_RECORD_END
    )
    panel = panel.loc[panel[strat.required_symbols].dropna().index.min() :]
    returns = run_backtest(panel, strat, cost_bps=record["cost_bps"]).daily_returns
    report = stationary_block_bootstrap(returns, seed=record["seed"])
    theirs = record["bootstrap"]
    return {
        "record_file": DUALMOM_RECORD.name,
        "cost_bps": record["cost_bps"],
        "sample_length": (theirs["sample_length"], report.sample_length),
        "prob_dd_worse_30": (
            theirs["prob_drawdown_worse_than_30pct"], report.prob_drawdown_worse_than_30pct
        ),
        "sharpe_p50": (theirs["sharpe_p50"], report.sharpe_p50),
        "max_drawdown_p50": (theirs["max_drawdown_p50"], report.max_drawdown_p50),
    }


def live_turnover(since: str) -> dict:
    """Annual turnover of the live account from run reports at or after ``since``."""
    runs = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["runs"]
    runs = sorted(
        (r for r in runs if r["timestamp"] >= since and not r["dry_run"]),
        key=lambda r: r["timestamp"],
    )
    orders = [o for r in runs for o in (r.get("submitted_orders") or [])]
    equities = [r["equity"] for r in runs if not r["aborted"] and (r["equity"] or 0) > 0]
    first = datetime.fromisoformat(runs[0]["timestamp"].replace("Z", "+00:00"))
    last = datetime.fromisoformat(runs[-1]["timestamp"].replace("Z", "+00:00"))
    days = (last - first).total_seconds() / 86400
    traded = sum(o["notional"] for o in orders)
    avg_eq = float(np.mean(equities))
    per_order = sum(
        r["est_turnover"] for r in runs if r.get("submitted_orders") and r.get("est_turnover")
    )
    aborted = sum(1 for r in runs if r["aborted"])
    return {
        "first_run": runs[0]["timestamp"],
        "last_run": runs[-1]["timestamp"],
        "days": days,
        "runs": len(runs),
        "aborted_runs": aborted,
        "orders": len(orders),
        "requested_notional": traded,
        "average_equity": avg_eq,
        "equity_marks": len(equities),
        "annual_turnover": traded / avg_eq * 365 / days,
        "annual_turnover_sum_est": per_order * 365 / days,
        "annual_turnover_excl_aborted_days": traded / avg_eq * 365 / (days - aborted),
    }


def build_fresh_store(directory: Path) -> tuple[ParquetStore, str]:
    """A separate store: the local BTC file plus current candles, complete UTC days only."""
    directory.mkdir(parents=True, exist_ok=True)
    src = REPO / "data/eod/BTCUSD.parquet"
    shutil.copy(src, directory / src.name)
    store = ParquetStore(directory)
    existing = store.load(SYMBOL)
    last = pd.to_datetime(existing["date"]).max().date()
    candles = CoinbaseClient().fetch_candles(SYMBOL, last - timedelta(days=3))
    today = datetime.now(UTC).date()
    candles = candles[pd.to_datetime(candles["date"]).dt.date < today]
    store.upsert(SYMBOL, candles)
    end = pd.to_datetime(store.load(SYMBOL)["date"]).max().date()
    return store, end.isoformat()


def same_window_backtest(panel: pd.DataFrame, live: dict) -> dict:
    start = pd.Timestamp(live["first_run"][:10])
    end = pd.Timestamp(live["last_run"][:10])
    res = run_backtest(panel, CryptoVolTargetBTC(), cost_bps=LIVE_FEE_BPS)
    literal, engine, traded = literal_turnover(res, start, end)
    turn = res.turnover.loc[start:end]
    return {
        "start": str(start.date()),
        "end": str(end.date()),
        "trades": int((turn > 1e-9).sum()),
        "annual_turnover_literal": literal,
        "annual_turnover_engine": engine,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fresh-eod-dir", type=Path, default=None)
    args = parser.parse_args()

    store = ParquetStore()
    panel = build_price_panel(store, [SYMBOL]).dropna()
    raw = store.load(SYMBOL)
    equity_limits = load_risk_limits()
    crypto_limits = load_risk_limits(REPO / "config/crypto_risk.yaml")
    live = live_turnover(CLOCK_START)
    since_creation = live_turnover("2026-07-01")

    grid_costs = (*COSTS, RECORD_COST)
    results: dict = {
        "generated": date.today().isoformat(),
        "price_data": {
            "first_bar": str(panel.index.min().date()),
            "last_bar": str(panel.index.max().date()),
            "bars": len(panel),
            "last_bar_volume": float(raw["volume"].iloc[-1]),
            "median_volume_prior_30": float(raw["volume"].iloc[-31:-1].median()),
        },
        "limits": {
            "equity_yaml_kill": equity_limits.max_drawdown_kill,
            "crypto_yaml_kill": crypto_limits.max_drawdown_kill,
        },
        "reproduction": reproduction(panel),
        "ungated": grid(panel, grid_costs),
        "overlay_crypto_yaml": grid(panel, COSTS, crypto_limits),
        "bootstrap": bootstrap(panel, grid_costs),
        "live": live,
        "live_since_creation": since_creation,
    }
    if args.fresh_eod_dir is not None:
        fresh_store, fresh_end = build_fresh_store(args.fresh_eod_dir)
        fresh = build_price_panel(fresh_store, [SYMBOL]).dropna()
        results["fresh"] = {
            "last_bar": fresh_end,
            "bars": len(fresh),
            "ungated": grid(fresh, COSTS),
            "bootstrap": bootstrap(fresh, COSTS),
            "same_window": same_window_backtest(fresh, live),
        }
    args.out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
