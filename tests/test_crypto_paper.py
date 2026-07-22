"""Crypto paper-runner wiring: strategy/calendar/risk-file selection per account,
and a mocked-broker plan cycle. Equity behavior is guarded alongside."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from quantlab.backtest.strategies import CryptoTrendBTC, CryptoVolTargetBTC
from quantlab.broker.alpaca_trading import AccountInfo, OrderInfo, Position
from quantlab.config import account_asset_class
from quantlab.constants import CRYPTO_RISK_YAML
from quantlab.data.calendar import TradingCalendar
from quantlab.data.health import HealthReport
from quantlab.data.validate import ValidationReport
from quantlab.paper.runner import make_paper_strategy, run_paper
from quantlab.risk.limits import load_risk_limits

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _frame(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "adj_close": prices})


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
        return self._frames.get(symbol, _frame(pd.DatetimeIndex([]), np.array([])))

    def load_metadata(self, symbol: str) -> None:
        return None


def _rising_btc_store(periods: int = 400) -> FakeStore:
    # Long, steadily rising -> crypto_trend is warmed and risk-on (100% BTC).
    dates = pd.bdate_range("2024-01-01", periods=periods)
    btc = 100.0 * (1.0006 ** np.arange(periods))
    return FakeStore({"BTC-USD": _frame(dates, btc)})


def _btc_store_ending(last: date, periods: int = 40) -> FakeStore:
    dates = pd.bdate_range(end=pd.Timestamp(last), periods=periods)
    btc = 100.0 * (1.0004 ** np.arange(periods))
    return FakeStore({"BTC-USD": _frame(dates, btc)})


def _account(**overrides: object) -> AccountInfo:
    base = dict(equity=100_000.0, cash=100_000.0, currency="USD",
                account_blocked=False, trading_blocked=False)
    base.update(overrides)
    return AccountInfo(**base)  # type: ignore[arg-type]


def _broker(positions: list[Position] | None = None, **acct: object) -> MagicMock:
    broker = MagicMock()
    broker.get_account.return_value = _account(**acct)
    broker.get_positions.return_value = positions if positions is not None else []
    broker.submit_order.side_effect = lambda symbol, side, notional, coid: OrderInfo(
        id=f"oid-{symbol}", client_order_id=coid, symbol=symbol, side=side,
        notional=notional, status="accepted", submitted_at=None,
    )
    return broker


def _passing(symbols: list[str]) -> list[ValidationReport]:
    return [ValidationReport(symbol=s, passed=True) for s in symbols]


def _seed_equity(path, values: list[float]) -> None:
    ts = pd.date_range("2026-07-01", periods=len(values), freq="D")
    pd.DataFrame({"timestamp": ts, "equity": values}).to_parquet(path, index=False)


NOW = datetime(2026, 7, 9, 13, 0, 0, tzinfo=UTC)


def _fresh_health() -> HealthReport:
    return HealthReport(generated_at=NOW, market_open=True, data_fresh=True,
                        symbols=[], blocking_reasons=[])


# --------------------------------------------------------------------------- #
# Account resolution: strategy, asset class, risk file                        #
# --------------------------------------------------------------------------- #

def test_make_paper_strategy_maps_crypto_accounts() -> None:
    assert isinstance(make_paper_strategy("crypto_trend"), CryptoTrendBTC)
    assert isinstance(make_paper_strategy("crypto_voltarget"), CryptoVolTargetBTC)
    # 365-day annualization travels with the strategy.
    assert make_paper_strategy("crypto_trend").periods_per_year == 365
    assert make_paper_strategy("crypto_voltarget").periods_per_year == 365


def test_account_asset_class_and_risk_file() -> None:
    assert account_asset_class("crypto_trend") == "crypto"
    assert account_asset_class("crypto_voltarget") == "crypto"
    assert account_asset_class("voltarget") == "us_equity"
    assert account_asset_class("trend") == "us_equity"

    crypto = load_risk_limits(CRYPTO_RISK_YAML)
    assert crypto.max_daily_loss == 0.15
    assert crypto.max_weekly_loss == 0.25
    assert crypto.max_drawdown_kill == 0.50
    # Same ordering invariant the model enforces on load.
    assert crypto.max_daily_loss < crypto.max_weekly_loss < crypto.max_drawdown_kill

    equity = load_risk_limits()  # config/risk.yaml, untouched
    assert equity.max_daily_loss == 0.03


# --------------------------------------------------------------------------- #
# Crypto uses the wider crypto_risk.yaml limits                               #
# --------------------------------------------------------------------------- #

def test_crypto_run_uses_wider_risk_limits(tmp_path) -> None:
    # An 8% single-session drop: HALTs an equity account (limit 3%), but is
    # within the crypto limit (15%), so the crypto account does NOT halt.
    eq_path = tmp_path / "eq.parquet"
    _seed_equity(eq_path, [100_000.0])
    report = run_paper(
        "crypto_trend", dry_run=True, store=_rising_btc_store(),
        broker=_broker(equity=92_000.0), do_ingest=False,
        validation_override=_passing(["BTC-USD"]), health_override=_fresh_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json", equity_history_path=eq_path,
        write_report=False, alert_fn=lambda _a: None,
    )
    assert report.abort_stage != "evaluate_portfolio"  # crypto limit not breached


def test_equity_run_would_halt_on_same_drop(tmp_path) -> None:
    eq_path = tmp_path / "eq.parquet"
    _seed_equity(eq_path, [100_000.0])
    # SPY store so voltarget is defined; the same -8% drop trips the 3% equity limit.
    dates = pd.bdate_range("2024-01-01", periods=400)
    store = FakeStore({"SPY": _frame(dates, 100.0 * (1.0004 ** np.arange(400)))})
    report = run_paper(
        "voltarget", dry_run=True, store=store, broker=_broker(equity=92_000.0),
        do_ingest=False, validation_override=_passing(["SPY"]), health_override=_fresh_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json", equity_history_path=eq_path,
        write_report=False, alert_fn=lambda _a: None,
    )
    assert report.aborted and report.abort_stage == "evaluate_portfolio"


# --------------------------------------------------------------------------- #
# Crypto defaults to the 24/7 CryptoCalendar                                  #
# --------------------------------------------------------------------------- #

def test_crypto_defaults_to_crypto_calendar_for_staleness(tmp_path) -> None:
    # Data ends Friday; "now" is the following Monday. Under the 24/7 crypto
    # calendar the weekend counts, so the data is 2 sessions stale -> health
    # aborts. (The XNYS calendar would treat it as fresh -- see the contrast.)
    friday = date(2026, 7, 10)
    assert friday.weekday() == 4
    monday_now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    store = _btc_store_ending(friday)

    report = run_paper(
        "crypto_trend", dry_run=True, store=store, broker=_broker(),
        do_ingest=False, validation_override=_passing(["BTC-USD"]),
        now=monday_now, clock=None,
        risk_state_path=tmp_path / "rs.json", equity_history_path=tmp_path / "eq.parquet",
        write_report=False,
    )
    assert report.aborted and report.abort_stage == "health"
    assert "FREEZE_STALE_DATA" in (report.abort_reason or "")


def test_injecting_nyse_calendar_makes_the_same_data_fresh(tmp_path) -> None:
    # Same store/now, but an explicitly injected XNYS calendar: Friday data is
    # fresh on Monday, so the run does NOT abort at health -> proves the default
    # for a crypto account is the crypto calendar, not XNYS.
    friday = date(2026, 7, 10)
    monday_now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    store = _btc_store_ending(friday)

    report = run_paper(
        "crypto_trend", dry_run=True, store=store, broker=_broker(),
        calendar=TradingCalendar(), do_ingest=False,
        validation_override=_passing(["BTC-USD"]),
        now=monday_now, clock=None,
        risk_state_path=tmp_path / "rs.json", equity_history_path=tmp_path / "eq.parquet",
        write_report=False,
    )
    assert report.abort_stage != "health"


# --------------------------------------------------------------------------- #
# Plan cycles                                                                 #
# --------------------------------------------------------------------------- #

def test_crypto_plan_cycle_produces_a_btc_buy(tmp_path) -> None:
    broker = _broker()  # zero positions, $100k equity
    report = run_paper(
        "crypto_trend", dry_run=True, store=_rising_btc_store(), broker=broker,
        do_ingest=False, validation_override=_passing(["BTC-USD"]),
        health_override=_fresh_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
    )
    assert not report.aborted
    assert report.target_weights == {"BTC-USD": 1.0}
    assert report.plan is not None and len(report.plan.intents) == 1
    intent = report.plan.intents[0]
    assert intent.symbol == "BTC-USD" and intent.side == "buy"
    assert intent.notional == 100_000.0  # full equity into BTC from a flat account
    broker.submit_order.assert_not_called()  # dry run


def test_equity_plan_cycle_unchanged(tmp_path) -> None:
    # trend fully in IEF, target SPY -> sell IEF, buy SPY (identical to before).
    dates = pd.bdate_range("2023-01-02", periods=300)
    store = FakeStore({
        "SPY": _frame(dates, 100.0 * (1.0004 ** np.arange(300))),
        "IEF": _frame(dates, np.full(300, 100.0)),
    })
    broker = _broker(positions=[
        Position(symbol="IEF", qty=1000.0, market_value=100_000.0, avg_entry_price=100.0)
    ])
    report = run_paper(
        "trend", dry_run=True, store=store, broker=broker, do_ingest=False,
        validation_override=_passing(["SPY", "IEF"]), health_override=_fresh_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
    )
    assert not report.aborted
    assert report.target_weights == {"SPY": 1.0}
    assert report.plan is not None and len(report.plan.intents) == 2
