"""Gated paper runner tests (broker + store mocked; no network, no real orders)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from quantlab.broker.alpaca_trading import AccountInfo, OrderInfo, Position
from quantlab.data.health import HealthReport
from quantlab.data.validate import ValidationReport
from quantlab.paper.runner import run_paper
from quantlab.risk.state import RiskState, save_risk_state

NOW = datetime(2026, 7, 9, 13, 0, 0)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

def _frame(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "adj_close": prices})


class FakeStore:
    """Minimal store exposing just what the runner touches (load/metadata)."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
        return self._frames.get(symbol, _frame(pd.DatetimeIndex([]), np.array([])))

    def load_metadata(self, symbol: str) -> None:
        return None


def _trend_store() -> FakeStore:
    # 300 business days: SPY rising (risk-on above its 10-mo SMA), IEF flat.
    dates = pd.bdate_range("2023-01-02", periods=300)
    spy = 100.0 * (1.0004 ** np.arange(300))
    ief = np.full(300, 100.0)
    return FakeStore({"SPY": _frame(dates, spy), "IEF": _frame(dates, ief)})


def _fresh_health() -> HealthReport:
    return HealthReport(generated_at=NOW, market_open=True, data_fresh=True,
                        symbols=[], blocking_reasons=[])


def _stale_health() -> HealthReport:
    return HealthReport(generated_at=NOW, market_open=False, data_fresh=False,
                        symbols=[], blocking_reasons=["SPY: 4 sessions behind"])


def _passing_validation(symbols: list[str]) -> list[ValidationReport]:
    return [ValidationReport(symbol=s, passed=True) for s in symbols]


def _account(**overrides: object) -> AccountInfo:
    base = dict(equity=100_000.0, cash=0.0, currency="USD",
                account_blocked=False, trading_blocked=False)
    base.update(overrides)
    return AccountInfo(**base)  # type: ignore[arg-type]


def _happy_broker() -> MagicMock:
    """Broker fully in IEF; trend targets SPY -> plan sells IEF, buys SPY."""
    broker = MagicMock()
    broker.get_account.return_value = _account()
    broker.get_positions.return_value = [
        Position(symbol="IEF", qty=1000.0, market_value=100_000.0, avg_entry_price=100.0)
    ]
    broker.submit_order.side_effect = lambda symbol, side, notional, coid: OrderInfo(
        id=f"oid-{symbol}", client_order_id=coid, symbol=symbol, side=side,
        notional=notional, status="accepted", submitted_at=None,
    )
    # Polling sees the sell already filled.
    broker.get_orders.return_value = [
        OrderInfo(id="oid-IEF", client_order_id="c", symbol="IEF", side="sell",
                  notional=100_000.0, status="filled", submitted_at=None)
    ]
    return broker


def _run(strategy: str, dry_run: bool, broker: MagicMock, store: object,
         tmp_path: object, **kw: object):
    return run_paper(
        strategy, dry_run=dry_run, store=store, broker=broker,  # type: ignore[arg-type]
        do_ingest=False,
        validation_override=_passing_validation(["SPY", "IEF"]),
        health_override=_fresh_health(),
        now=NOW,
        risk_state_path=tmp_path / "risk_state.json",  # type: ignore[operator]
        equity_history_path=tmp_path / "equity_history.parquet",  # type: ignore[operator]
        write_report=False,
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: 0.0,
        **kw,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Safety gates abort before touching the broker                              #
# --------------------------------------------------------------------------- #

def test_halted_state_aborts_before_any_broker_call(tmp_path) -> None:
    state_path = tmp_path / "risk_state.json"
    save_risk_state(
        RiskState(halted=True, reason="KILL_DRAWDOWN dd -0.30", requires_manual_reset=True),
        state_path,
    )
    broker = MagicMock()
    report = run_paper(
        "voltarget", dry_run=True, store=MagicMock(), broker=broker,
        do_ingest=False, now=NOW, risk_state_path=state_path,
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
    )
    assert report.aborted and report.abort_stage == "risk_state"
    assert "quantlab risk reset required" in (report.abort_reason or "")
    assert broker.mock_calls == []  # broker never touched


def test_stale_data_aborts_at_health(tmp_path) -> None:
    broker = MagicMock()
    report = run_paper(
        "trend", dry_run=True, store=_trend_store(), broker=broker, do_ingest=False,
        validation_override=_passing_validation(["SPY", "IEF"]),
        health_override=_stale_health(), now=NOW,
        risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
    )
    assert report.aborted and report.abort_stage == "health"
    assert "FREEZE_STALE_DATA" in (report.abort_reason or "")
    broker.get_account.assert_not_called()


def test_blocked_account_aborts(tmp_path) -> None:
    broker = _happy_broker()
    broker.get_account.return_value = _account(trading_blocked=True)
    report = _run("trend", True, broker, _trend_store(), tmp_path)
    assert report.aborted and report.abort_stage == "account"
    broker.get_positions.assert_not_called()


# --------------------------------------------------------------------------- #
# Happy paths                                                                 #
# --------------------------------------------------------------------------- #

def test_dry_run_plans_but_submits_nothing(tmp_path) -> None:
    broker = _happy_broker()
    report = _run("trend", True, broker, _trend_store(), tmp_path)
    assert not report.aborted
    assert report.plan is not None and len(report.plan.intents) == 2
    assert report.target_weights == {"SPY": 1.0}
    assert report.submitted_orders == []
    broker.submit_order.assert_not_called()


def test_submit_sends_sells_then_buys_in_order(tmp_path) -> None:
    broker = _happy_broker()
    report = _run("trend", False, broker, _trend_store(), tmp_path)
    assert not report.aborted
    calls = broker.submit_order.call_args_list
    assert [c.args[0] for c in calls] == ["IEF", "SPY"]  # symbols
    assert [c.args[1] for c in calls] == ["sell", "buy"]  # sell before buy
    broker.get_orders.assert_called()  # polled the sell to terminal


def test_second_same_day_run_reuses_client_order_ids(tmp_path) -> None:
    store = _trend_store()
    broker1 = _happy_broker()
    _run("trend", False, broker1, store, tmp_path)
    coids1 = [c.args[3] for c in broker1.submit_order.call_args_list]

    broker2 = _happy_broker()
    _run("trend", False, broker2, store, tmp_path)  # same NOW, same equity history
    coids2 = [c.args[3] for c in broker2.submit_order.call_args_list]

    assert coids1 == coids2  # deterministic, idempotent client_order_ids
    assert coids1 == [
        "ql-trend-20260709-IEF-sell",
        "ql-trend-20260709-SPY-buy",
    ]


def test_in_band_no_trades_exits_clean(tmp_path) -> None:
    # Already fully in SPY at the target -> zero drift -> no intents.
    broker = _happy_broker()
    broker.get_positions.return_value = [
        Position(symbol="SPY", qty=200.0, market_value=100_000.0, avg_entry_price=500.0)
    ]
    report = _run("trend", False, broker, _trend_store(), tmp_path)
    assert not report.aborted and report.no_trades
    broker.submit_order.assert_not_called()
