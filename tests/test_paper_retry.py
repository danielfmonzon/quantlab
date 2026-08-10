"""Bounded-retry tests: what retries, what must never retry, and what it alerts.

Broker and store are mocked; ``sleep_fn`` is a recorder, so the ten-minute wait is asserted
rather than waited. Nothing here touches the network or submits an order.

The load-bearing assertions are negative. For every non-retryable abort the test proves the
pipeline did NOT run a second time, using the broker FACTORY call count as the observable —
a retry that quietly happened after a KILL, a halt, or a partial submission would be a
trading-safety failure, not a cosmetic one.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from quantlab.broker.alpaca_trading import AccountInfo, OrderInfo, Position, TradingError
from quantlab.config import ConfigError
from quantlab.data import DataError
from quantlab.data.health import HealthReport
from quantlab.data.validate import ValidationReport
from quantlab.paper.runner import RETRY_DELAY_SECONDS, run_paper_with_retry
from quantlab.reporting.alerts import Alert
from quantlab.risk.state import RiskState, save_risk_state

NOW = datetime(2026, 8, 10, 14, 0, 0)


def _frame(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "adj_close": prices})


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
        return self._frames.get(symbol, _frame(pd.DatetimeIndex([]), np.array([])))

    def load_metadata(self, symbol: str) -> None:
        return None


def _store() -> FakeStore:
    dates = pd.bdate_range("2023-01-02", periods=300)
    spy = 100.0 * (1.0004 ** np.arange(300))
    return FakeStore({"SPY": _frame(dates, spy),
                      "IEF": _frame(dates, np.full(300, 100.0))})


def _account(**overrides: object) -> AccountInfo:
    base = dict(equity=100_000.0, cash=0.0, currency="USD",
                account_blocked=False, trading_blocked=False)
    base.update(overrides)
    return AccountInfo(**base)  # type: ignore[arg-type]


def _broker() -> MagicMock:
    b = MagicMock()
    b.get_account.return_value = _account()
    b.get_positions.return_value = [
        Position(symbol="IEF", qty=1000.0, market_value=100_000.0, avg_entry_price=100.0)
    ]
    b.submit_order.side_effect = lambda symbol, side, notional, coid: OrderInfo(
        id=f"oid-{symbol}", client_order_id=coid, symbol=symbol, side=side,
        notional=notional, status="accepted", submitted_at=None,
    )
    b.get_orders.return_value = [
        OrderInfo(id="oid-IEF", client_order_id="c", symbol="IEF", side="sell",
                  notional=100_000.0, status="filled", submitted_at=None)
    ]
    return b


def _health(fresh: bool = True) -> HealthReport:
    return HealthReport(
        generated_at=NOW, market_open=fresh, data_fresh=fresh, symbols=[],
        blocking_reasons=[] if fresh else ["SPY: 4 sessions behind"],
    )


class Harness:
    """Runs the retrying pipeline, recording factory calls, sleeps, and alerts."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.factory_calls = 0
        self.sleeps: list[float] = []
        self.alerts: list[Alert] = []
        self.brokers: list[MagicMock] = []

    def factory(self) -> MagicMock:
        self.factory_calls += 1
        b = _broker()
        self.brokers.append(b)
        return b


def _run(tmp_path: Path, *, h: Harness | None = None, **kw: object):
    """Single-shot run with uniform per-attempt behaviour (the common case)."""
    harness = h or Harness(tmp_path)
    report = run_paper_with_retry(
        "trend", dry_run=kw.pop("dry_run", True),  # type: ignore[arg-type]
        store=_store(),
        broker_factory=harness.factory,
        do_ingest=kw.pop("do_ingest", False),  # type: ignore[arg-type]
        now=NOW,
        risk_state_path=tmp_path / "risk_state.json",
        equity_history_path=tmp_path / "equity.parquet",
        write_report=False,
        sleep_fn=harness.sleeps.append,
        monotonic_fn=lambda: 0.0,
        alert_fn=harness.alerts.append,
        **kw,  # type: ignore[arg-type]
    )
    return report, harness


def _valid() -> list[ValidationReport]:
    return [ValidationReport(symbol=s, passed=True) for s in ("SPY", "IEF")]


# --------------------------------------------------------------------------- #
# Retryable: one retry, ten minutes, then a single WARNING                     #
# --------------------------------------------------------------------------- #


def test_stale_data_retries_once_then_aborts_with_one_warning(tmp_path: Path) -> None:
    """FREEZE_STALE_DATA is the canonical retryable abort: the bar may land late."""
    report, h = _run(tmp_path, validation_override=_valid(), health_override=_health(False))
    assert report.aborted and report.abort_stage == "health"
    assert report.abort_retryable is True
    assert report.attempt == 2                       # the retry ran and also aborted
    # health is stage (d): neither attempt reached stage (e), so no broker was ever built.
    assert h.factory_calls == 0
    assert h.sleeps == [RETRY_DELAY_SECONDS]         # exactly one ten-minute wait
    assert RETRY_DELAY_SECONDS == 600.0
    # One logical failure -> exactly one WARNING (attempt 1's was superseded).
    warnings = [a for a in h.alerts if a.level == "WARNING"]
    assert len(warnings) == 1
    assert "health" in warnings[0].title


def test_transient_ingest_failure_retries_once(tmp_path: Path) -> None:
    def boom(symbols: list[str], store: object) -> None:
        raise TimeoutError("read timed out contacting the vendor")

    report, h = _run(tmp_path, do_ingest=True, ingest_fn=boom,
                     validation_override=_valid(), health_override=_health())
    assert report.abort_stage == "ingest"
    assert report.abort_retryable is True
    assert report.attempt == 2
    assert h.factory_calls == 0   # ingest is stage (b); no broker is built that early
    assert h.sleeps == [RETRY_DELAY_SECONDS]
    assert len([a for a in h.alerts if a.level == "WARNING"]) == 1


def test_sustained_broker_read_failure_retries_once(tmp_path: Path) -> None:
    """A 5xx/timeout on the READ path: the client already exhausted its own retries."""
    h = Harness(tmp_path)
    original = h.factory

    def failing_factory() -> MagicMock:
        b = original()
        b.get_account.side_effect = RuntimeError("transient Alpaca response 503")
        return b

    report = run_paper_with_retry(
        "trend", dry_run=True, store=_store(), broker_factory=failing_factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.abort_stage == "account"
    assert report.abort_retryable is True
    assert report.attempt == 2
    assert h.factory_calls == 2
    assert h.sleeps == [RETRY_DELAY_SECONDS]


def _ingest_that_heals() -> object:
    """Fails the first attempt's ingest, succeeds on every one after."""
    state = {"n": 0}

    def ingest_fn(symbols: list[str], store: object) -> None:
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("vendor connection reset")

    return ingest_fn


def test_a_retry_that_succeeds_yields_one_clean_report_marked_attempt_2(
    tmp_path: Path
) -> None:
    """Recovery: attempt 1's ingest fails transiently, attempt 2 succeeds and completes.

    This is the whole point of the feature — before it, a blip like this cost a full
    session of paper record, and those gaps are what the divergence diagnoses kept tripping
    over.
    """
    report, h = _run(
        tmp_path, do_ingest=True, ingest_fn=_ingest_that_heals(),
        validation_override=_valid(), health_override=_health(),
    )
    assert report.attempt == 2
    assert report.aborted is False            # the retry recovered
    assert report.abort_stage is None
    assert report.equity == 100_000.0         # it got all the way through the pipeline
    assert h.sleeps == [RETRY_DELAY_SECONDS]
    # Attempt 1 aborted at stage (b), so only attempt 2 ever built a broker.
    assert h.factory_calls == 1
    # A recovered run must raise NO warning: there is nothing left wrong to report.
    assert [a.level for a in h.alerts if a.level == "WARNING"] == []


# --------------------------------------------------------------------------- #
# Never retried                                                               #
# --------------------------------------------------------------------------- #


def test_halted_risk_state_never_retries(tmp_path: Path) -> None:
    """A halt is a decision. Retrying it would be pretending it might not be one."""
    save_risk_state(
        RiskState(halted=True, reason="KILL_DRAWDOWN: -12%", triggered_at=NOW,
                  requires_manual_reset=True),
        tmp_path / "risk_state.json",
    )
    report, h = _run(tmp_path, validation_override=_valid(), health_override=_health())
    assert report.abort_stage == "risk_state"
    assert report.abort_retryable is False
    assert report.attempt == 1
    assert h.factory_calls == 0     # never even built a broker
    assert h.sleeps == []           # no ten-minute wait
    assert len([a for a in h.alerts if a.level == "WARNING"]) == 1


def test_validation_error_never_retries(tmp_path: Path) -> None:
    """A data-CONTENT error: the retry would read the same bars and abort identically."""
    bad = [ValidationReport(symbol="SPY", passed=False,
                            errors=["duplicate dates"]),
           ValidationReport(symbol="IEF", passed=True)]
    report, h = _run(tmp_path, validation_override=bad, health_override=_health())
    assert report.abort_stage == "validate"
    assert report.abort_retryable is False
    assert report.attempt == 1
    # validate is stage (c): the broker is built at (e), so a content error costs no
    # credential read and no client at all.
    assert h.factory_calls == 0
    assert h.sleeps == []


def test_blocked_account_never_retries(tmp_path: Path) -> None:
    h = Harness(tmp_path)

    def blocked_factory() -> MagicMock:
        b = h.factory()
        b.get_account.return_value = _account(trading_blocked=True)
        return b

    report = run_paper_with_retry(
        "trend", dry_run=True, store=_store(), broker_factory=blocked_factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.abort_stage == "account"
    assert "trading_blocked" in (report.abort_reason or "")
    assert report.abort_retryable is False
    assert h.factory_calls == 1      # NO second broker-factory call
    assert h.sleeps == []


def test_permanent_broker_fault_never_retries(tmp_path: Path) -> None:
    """TradingError carries a permanent 4xx: the API answered, and the answer was bad."""
    h = Harness(tmp_path)

    def bad_auth_factory() -> MagicMock:
        b = h.factory()
        b.get_account.side_effect = TradingError("HTTP 403: forbidden", status=403)
        return b

    report = run_paper_with_retry(
        "trend", dry_run=True, store=_store(), broker_factory=bad_auth_factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.abort_stage == "account"
    assert report.abort_retryable is False
    assert h.factory_calls == 1
    assert h.sleeps == []


def test_malformed_payload_never_retries(tmp_path: Path) -> None:
    """A bare DataError (unexpected payload shape) is also permanent."""
    h = Harness(tmp_path)

    def bad_payload_factory() -> MagicMock:
        b = h.factory()
        b.get_account.side_effect = DataError("Unexpected account payload: <class 'list'>")
        return b

    report = run_paper_with_retry(
        "trend", dry_run=True, store=_store(), broker_factory=bad_payload_factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.abort_retryable is False
    assert h.factory_calls == 1


def test_config_error_on_ingest_never_retries(tmp_path: Path) -> None:
    """A missing key is not cured by waiting ten minutes."""
    def boom(symbols: list[str], store: object) -> None:
        raise ConfigError("TIINGO_API_KEY is not set")

    report, h = _run(tmp_path, do_ingest=True, ingest_fn=boom,
                     validation_override=_valid(), health_override=_health())
    assert report.abort_stage == "ingest"
    assert report.abort_retryable is False
    assert report.attempt == 1
    assert h.sleeps == []


def test_submission_failure_never_retries_and_alerts(tmp_path: Path) -> None:
    """Orders may already be live. A partial submission must alert, never re-run."""
    h = Harness(tmp_path)

    def submitting_factory() -> MagicMock:
        b = h.factory()
        b.submit_order.side_effect = RuntimeError("connection reset mid-submit")
        return b

    report = run_paper_with_retry(
        "trend", dry_run=False, store=_store(), broker_factory=submitting_factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.abort_stage == "submit"
    assert report.abort_retryable is False
    assert report.attempt == 1
    assert h.factory_calls == 1      # the pipeline did NOT run again
    assert h.sleeps == []
    criticals = [a for a in h.alerts if a.level == "CRITICAL"]
    assert len(criticals) == 1       # it alerts instead of retrying
    assert "submit" in criticals[0].title


def test_kill_switch_never_retries(tmp_path: Path) -> None:
    """evaluate_portfolio has just WRITTEN a halt; a retry must not look like a 2nd chance."""
    h = Harness(tmp_path)
    # Seed an equity history whose latest point is a >20% drawdown.
    pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-08-03", "2026-08-04"]),
        "equity": [200_000.0, 100_000.0],
    }).to_parquet(tmp_path / "eq.parquet", index=False)

    report = run_paper_with_retry(
        "trend", dry_run=True, store=_store(), broker_factory=h.factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet", write_report=False,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.abort_stage == "evaluate_portfolio"
    assert report.abort_retryable is False
    assert h.factory_calls == 1
    assert h.sleeps == []


# --------------------------------------------------------------------------- #
# A clean first attempt does nothing extra                                     #
# --------------------------------------------------------------------------- #


def test_a_clean_run_neither_sleeps_nor_rebuilds_the_broker(tmp_path: Path) -> None:
    report, h = _run(tmp_path, validation_override=_valid(), health_override=_health())
    assert report.aborted is False
    assert report.attempt == 1
    assert h.factory_calls == 1
    assert h.sleeps == []
    assert [a.level for a in h.alerts if a.level == "WARNING"] == []


def test_attempt_is_persisted_to_the_report_file(tmp_path: Path) -> None:
    """The audit reads the FILE, so the retry's attempt number must reach disk."""
    import json

    reports_dir = tmp_path / "paper"
    h = Harness(tmp_path)
    report = run_paper_with_retry(
        "trend", dry_run=True, store=_store(), broker_factory=h.factory,
        do_ingest=False, validation_override=_valid(), health_override=_health(False),
        now=NOW, risk_state_path=tmp_path / "rs.json",
        equity_history_path=tmp_path / "eq.parquet",
        reports_dir=reports_dir, write_report=True,
        sleep_fn=h.sleeps.append, monotonic_fn=lambda: 0.0, alert_fn=h.alerts.append,
    )
    assert report.attempt == 2
    written = sorted(reports_dir.glob("run_trend_*.json"))
    assert written, "the run must have written a report"
    payload = json.loads(written[-1].read_text(encoding="utf-8"))
    assert payload["attempt"] == 2
    assert payload["abort_retryable"] is True
