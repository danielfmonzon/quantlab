"""Daily digest tests (broker + store mocked; no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantlab.broker.alpaca_trading import AccountInfo, OrderInfo, Position
from quantlab.data.calendar import TradingCalendar
from quantlab.reporting.digest import build_digest, render_markdown, write_digest

NOW = datetime(2026, 7, 10, 20, 0, 0, tzinfo=UTC)


def _frame(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "adj_close": prices})


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
        return self._frames.get(symbol, _frame(pd.DatetimeIndex([]), np.array([])))

    def load_metadata(self, symbol: str) -> None:
        return None


def _spy_store() -> FakeStore:
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2026-03-02", periods=80)
    prices = 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.008, 80))
    return FakeStore({"SPY": _frame(dates, prices)})


def _broker() -> MagicMock:
    broker = MagicMock()
    broker.get_account.return_value = AccountInfo(
        equity=101_000.0, cash=38_000.0, currency="USD",
        account_blocked=False, trading_blocked=False,
    )
    broker.get_positions.return_value = [
        Position(symbol="SPY", qty=84.0, market_value=63_000.0, avg_entry_price=740.0)
    ]
    broker.get_orders.return_value = [
        OrderInfo(id="o1", client_order_id="ql-voltarget-20260710-SPY-buy", symbol="SPY",
                  side="buy", notional=63_000.0, status="filled", submitted_at=None)
    ]
    return broker


def _seed_equity(path, values: list[float]) -> None:
    ts = pd.date_range("2026-07-01", periods=len(values), freq="D")
    pd.DataFrame({"timestamp": ts, "equity": values}).to_parquet(path, index=False)


def _build(tmp_path, equity_values: list[float]):
    eq_path = tmp_path / "equity_history.parquet"
    _seed_equity(eq_path, equity_values)
    return build_digest(
        _broker(), _spy_store(), TradingCalendar(), NOW,
        equity_history_path=eq_path,
        paper_reports_dir=tmp_path / "paper",
        risk_state_path=tmp_path / "risk_state.json",
    )


def test_day_change_computed_vs_previous_snapshot(tmp_path) -> None:
    # prev snapshot 100000; current equity 101000 -> +1%.
    digest = _build(tmp_path, [99_000.0, 100_000.0])
    assert digest.account.day_change_pct == pytest.approx(101_000.0 / 100_000.0 - 1.0)
    # track record spans from the first snapshot (99000).
    assert digest.track_record.n_run_days == 2
    assert digest.track_record.total_return_since_start == pytest.approx(
        101_000.0 / 99_000.0 - 1.0
    )


def test_positions_carry_unrealized_pnl(tmp_path) -> None:
    digest = _build(tmp_path, [100_000.0])
    pos = digest.positions[0]
    # cost = 84 * 740 = 62160; mv 63000 -> +840.
    assert pos.unrealized_pl == pytest.approx(63_000.0 - 84.0 * 740.0)


def test_markdown_contains_equity_positions_and_risk_state(tmp_path) -> None:
    digest = _build(tmp_path, [100_000.0])
    md = render_markdown(digest)
    assert "101,000.00" in md
    assert "SPY" in md
    assert "## Risk state" in md
    assert "halted: **False**" in md
    assert "voltarget:" in md  # target weights section


def test_same_day_rerun_overwrites(tmp_path) -> None:
    digests_dir = tmp_path / "digests"
    d1 = _build(tmp_path, [100_000.0])
    md_path, json_path = write_digest(d1, digests_dir=digests_dir)

    # A second digest the same day (different equity) overwrites the same files.
    broker2 = _broker()
    broker2.get_account.return_value = AccountInfo(
        equity=95_000.0, cash=1_000.0, currency="USD",
        account_blocked=False, trading_blocked=False,
    )
    eq_path = tmp_path / "equity_history.parquet"
    d2 = build_digest(broker2, _spy_store(), TradingCalendar(), NOW,
                      equity_history_path=eq_path, paper_reports_dir=tmp_path / "paper",
                      risk_state_path=tmp_path / "risk_state.json")
    md_path2, _ = write_digest(d2, digests_dir=digests_dir)

    assert md_path2 == md_path  # same filename (same day)
    assert len(list(digests_dir.glob("digest_*.md"))) == 1
    assert "95,000.00" in md_path.read_text(encoding="utf-8")

