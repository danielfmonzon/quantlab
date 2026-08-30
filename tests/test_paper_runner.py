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
from quantlab.risk.state import RiskState, load_risk_state, save_risk_state

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


# --------------------------------------------------------------------------- #
# Alert wiring                                                                #
# --------------------------------------------------------------------------- #

def _seed_equity(path, values: list[float]) -> None:
    ts = pd.date_range("2026-07-01", periods=len(values), freq="D")
    pd.DataFrame({"timestamp": ts, "equity": values}).to_parquet(path, index=False)


def _kill_run(tmp_path, alert_fn):
    # Prior peak 100000; this run's equity is 70000 -> -30% drawdown -> KILL.
    eq_path = tmp_path / "equity_history.parquet"
    _seed_equity(eq_path, [100_000.0])
    state_path = tmp_path / "risk_state.json"
    broker = _happy_broker()
    broker.get_account.return_value = _account(equity=70_000.0)
    report = run_paper(
        "trend", dry_run=False, store=_trend_store(), broker=broker, do_ingest=False,
        validation_override=_passing_validation(["SPY", "IEF"]),
        health_override=_fresh_health(), now=NOW, risk_state_path=state_path,
        equity_history_path=eq_path, write_report=False,
        sleep_fn=lambda _s: None, monotonic_fn=lambda: 0.0, alert_fn=alert_fn,
    )
    return report, state_path, broker


def test_kill_fires_critical_alert_after_state_written(tmp_path) -> None:
    seen: dict[str, object] = {}
    state_path = tmp_path / "risk_state.json"

    def alert_fn(alert) -> None:
        # At alert time the kill-switch state must ALREADY be persisted & halted.
        seen["halted_at_alert"] = load_risk_state(state_path).halted
        seen["alert"] = alert

    _seed_equity(tmp_path / "equity_history.parquet", [100_000.0])
    broker = _happy_broker()
    broker.get_account.return_value = _account(equity=70_000.0)
    report = run_paper(
        "trend", dry_run=False, store=_trend_store(), broker=broker, do_ingest=False,
        validation_override=_passing_validation(["SPY", "IEF"]),
        health_override=_fresh_health(), now=NOW, risk_state_path=state_path,
        equity_history_path=tmp_path / "equity_history.parquet", write_report=False,
        sleep_fn=lambda _s: None, monotonic_fn=lambda: 0.0, alert_fn=alert_fn,
    )
    assert report.aborted and report.abort_stage == "evaluate_portfolio"
    assert seen["halted_at_alert"] is True  # state written BEFORE the alert fired
    assert seen["alert"].level == "CRITICAL"  # type: ignore[attr-defined]
    assert "trend" in seen["alert"].title  # type: ignore[attr-defined]  carries the label
    assert load_risk_state(state_path).requires_manual_reset is True  # KILL
    broker.submit_order.assert_not_called()  # aborted before any order


def test_alert_failure_does_not_prevent_state_write(tmp_path) -> None:
    def boom(_alert) -> None:
        raise RuntimeError("alerting is down")

    report, state_path, _ = _kill_run(tmp_path, boom)
    assert report.aborted and report.abort_stage == "evaluate_portfolio"
    # The RiskState write happened despite the alert raising.
    assert load_risk_state(state_path).halted is True
    assert load_risk_state(state_path).requires_manual_reset is True


def test_successful_submit_fires_info_alert(tmp_path) -> None:
    alerts: list[object] = []
    broker = _happy_broker()
    report = _run("trend", False, broker, _trend_store(), tmp_path, alert_fn=alerts.append)
    assert not report.aborted
    info = [a for a in alerts if a.level == "INFO"]  # type: ignore[attr-defined]
    assert len(info) == 1
    assert "order(s) submitted" in info[0].title  # type: ignore[attr-defined]
    assert "trend" in info[0].title  # alert carries the strategy label


def test_kill_in_one_account_does_not_halt_the_other(tmp_path) -> None:
    # --- trend: a -30% drawdown KILLs and writes ONLY trend's state ---
    trend_rs = tmp_path / "risk_state_trend.json"
    trend_eq = tmp_path / "equity_history_trend.parquet"
    _seed_equity(trend_eq, [100_000.0])
    tbroker = _happy_broker()
    tbroker.get_account.return_value = _account(equity=70_000.0)
    trend_report = run_paper(
        "trend", dry_run=False, store=_trend_store(), broker=tbroker, do_ingest=False,
        validation_override=_passing_validation(["SPY", "IEF"]),
        health_override=_fresh_health(), now=NOW, risk_state_path=trend_rs,
        equity_history_path=trend_eq, write_report=False, alert_fn=lambda _a: None,
        sleep_fn=lambda _s: None, monotonic_fn=lambda: 0.0,
    )
    assert trend_report.aborted and trend_report.abort_stage == "evaluate_portfolio"
    assert load_risk_state(trend_rs).halted is True

    # --- voltarget: its OWN clean state -> proceeds; trend's KILL is invisible ---
    vt_rs = tmp_path / "risk_state_voltarget.json"
    vt_eq = tmp_path / "equity_history_voltarget.parquet"
    vt_report = run_paper(
        "voltarget", dry_run=True, store=_trend_store(), broker=_happy_broker(), do_ingest=False,
        validation_override=_passing_validation(["SPY", "IEF"]),
        health_override=_fresh_health(), now=NOW, risk_state_path=vt_rs,
        equity_history_path=vt_eq, write_report=False, alert_fn=lambda _a: None,
        sleep_fn=lambda _s: None, monotonic_fn=lambda: 0.0,
    )
    assert vt_report.abort_stage != "risk_state"  # NOT halted by trend's KILL
    assert load_risk_state(vt_rs).halted is False  # voltarget's state stayed clean


# --------------------------------------------------------------------------- #
# Fill evidence in the run report (PROP-5)                                    #
# --------------------------------------------------------------------------- #

def _filled_broker() -> MagicMock:
    """`_happy_broker`, but the poll resolves BOTH orders with real fill evidence.

    The default double resolves only the sell, because before PROP-5 only the sell was
    ever polled. A broker that answers for every order it was given is the honest model
    now that every order is read back.
    """
    broker = _happy_broker()
    broker.get_orders.return_value = [
        OrderInfo(id="oid-IEF", client_order_id="c", symbol="IEF", side="sell",
                  notional=100_000.0, status="filled", submitted_at=None,
                  filled_qty=1_000.0, filled_avg_price=101.0,
                  filled_at=datetime(2026, 7, 9, 14, 0, 5)),
        OrderInfo(id="oid-SPY", client_order_id="c", symbol="SPY", side="buy",
                  notional=100_000.0, status="filled", submitted_at=None,
                  filled_qty=200.0, filled_avg_price=500.0,
                  filled_at=datetime(2026, 7, 9, 14, 0, 7)),
    ]
    return broker


def test_run_report_records_fill_evidence_for_every_order(tmp_path) -> None:
    """The gap diagnosis #3 hit: a report must say what filled, not just what was asked.

    Every order carries its terminal status, filled quantity, average fill price and fill
    timestamp, read back from the broker rather than left at the `pending_new` a freshly
    submitted order always shows.
    """
    broker = _filled_broker()
    report = _run("trend", False, broker, _trend_store(), tmp_path)
    assert not report.aborted

    by_symbol = {o.symbol: o for o in report.submitted_orders}
    assert set(by_symbol) == {"IEF", "SPY"}

    sell = by_symbol["IEF"]
    assert sell.status == "filled"
    assert sell.filled_qty == 1_000.0
    assert sell.filled_avg_price == 101.0
    assert sell.filled_at == datetime(2026, 7, 9, 14, 0, 5)

    buy = by_symbol["SPY"]
    assert buy.status == "filled"
    assert buy.filled_qty == 200.0
    assert buy.filled_avg_price == 500.0


def test_fill_evidence_does_not_disturb_what_the_run_asked_for(tmp_path) -> None:
    """The submitted record stays authoritative for the ORDER; the poll only adds to it.

    Notional, side, symbol and the client_order_id are what this run decided, and the
    read-back must not be able to overwrite any of them -- the polled record is a
    different view of the same order, not a replacement for the decision behind it.
    """
    broker = _filled_broker()
    report = _run("trend", False, broker, _trend_store(), tmp_path)

    by_symbol = {o.symbol: o for o in report.submitted_orders}
    assert by_symbol["IEF"].side == "sell"
    assert by_symbol["SPY"].side == "buy"
    assert by_symbol["IEF"].client_order_id == "ql-trend-20260709-IEF-sell"
    assert by_symbol["SPY"].client_order_id == "ql-trend-20260709-SPY-buy"
    # The notionals are the plan's, not the poll's view of them.
    submitted = {c.args[0]: c.args[2] for c in broker.submit_order.call_args_list}
    assert by_symbol["IEF"].notional == submitted["IEF"]
    assert by_symbol["SPY"].notional == submitted["SPY"]


def test_a_poll_that_never_resolves_leaves_fill_fields_null(tmp_path) -> None:
    """A timed-out poll reports UNKNOWN, never zero.

    Writing 0.0 would tell a later reader the order filled nothing, and the residual
    attribution built on these fields would price a real fill as none at all. The run
    itself must still complete -- fill evidence is reporting, and its absence is never
    allowed to fail a run that placed its orders.
    """
    broker = _happy_broker()
    broker.get_orders.return_value = []          # the broker never resolves anything
    report = _run("trend", False, broker, _trend_store(), tmp_path)

    assert not report.aborted
    assert len(report.submitted_orders) == 2
    for order in report.submitted_orders:
        assert order.filled_qty is None
        assert order.filled_avg_price is None
        assert order.filled_at is None
        assert order.status == "accepted"        # the submit-time status, unchanged


def test_the_poll_is_bounded_when_the_clock_never_advances(tmp_path) -> None:
    """Termination does not depend on the clock moving.

    `_run` freezes `monotonic_fn` at 0.0, so the deadline can never fire. The poll-count
    bound is what returns; without it this sits forever inside the trading path.
    """
    broker = _happy_broker()
    broker.get_orders.return_value = []
    report = _run("trend", False, broker, _trend_store(), tmp_path)
    assert not report.aborted
    # 120s / 2s + 1 per await, and the sells are awaited before the evidence poll.
    assert broker.get_orders.call_count <= 2 * 61
