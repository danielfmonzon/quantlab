"""Daily multi-account digest tests (brokers + store mocked; no network)."""

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


def _store() -> FakeStore:
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2026-03-02", periods=80)
    frames = {}
    for sym, drift in (("SPY", 0.0003), ("IEF", 0.0001)):
        frames[sym] = _frame(dates, 100.0 * np.cumprod(1.0 + rng.normal(drift, 0.006, 80)))
    return FakeStore(frames)


def _broker(equity: float, cash: float, symbol: str, mv: float) -> MagicMock:
    broker = MagicMock()
    broker.get_account.return_value = AccountInfo(
        equity=equity, cash=cash, currency="USD",
        account_blocked=False, trading_blocked=False,
    )
    broker.get_positions.return_value = [
        Position(symbol=symbol, qty=80.0, market_value=mv, avg_entry_price=mv / 80.0 - 1.0)
    ]
    broker.get_orders.return_value = [
        OrderInfo(id="o1", client_order_id=f"ql-x-20260710-{symbol}-buy", symbol=symbol,
                  side="buy", notional=mv, status="filled", submitted_at=None)
    ]
    return broker


def _seed_equity(path, values: list[float]) -> None:
    ts = pd.date_range("2026-07-01", periods=len(values), freq="D")
    pd.DataFrame({"timestamp": ts, "equity": values}).to_parquet(path, index=False)


def _build(tmp_path, brokers, seed=True):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    if seed:
        _seed_equity(data_dir / "equity_history_voltarget.parquet", [99_000.0, 100_000.0])
        _seed_equity(data_dir / "equity_history_trend.parquet", [50_000.0])
    return build_digest(
        brokers, _store(), TradingCalendar(), NOW,
        data_dir=data_dir, paper_reports_dir=tmp_path / "paper",
    )


def test_two_accounts_render_two_sections_and_combined(tmp_path) -> None:
    brokers = {
        "voltarget": _broker(101_000.0, 38_000.0, "SPY", 63_000.0),
        "trend": _broker(50_500.0, 20_000.0, "IEF", 30_000.0),
    }
    digest = _build(tmp_path, brokers)
    assert [a.label for a in digest.accounts] == ["voltarget", "trend"]
    assert all(a.available for a in digest.accounts)
    # Combined total sums both accounts.
    assert digest.combined_equity == pytest.approx(101_000.0 + 50_500.0)
    assert digest.combined_cash == pytest.approx(38_000.0 + 20_000.0)

    md = render_markdown(digest)
    assert "## Account: voltarget" in md
    assert "## Account: trend" in md
    assert "## Combined" in md
    assert "151,500.00" in md  # combined equity


def test_digest_header_carries_version_for_traceability(tmp_path) -> None:
    from quantlab import __version__

    brokers = {"voltarget": _broker(101_000.0, 38_000.0, "SPY", 63_000.0), "trend": None}
    digest = _build(tmp_path, brokers)
    md = render_markdown(digest)
    # Every generated report is traceable to a release + commit.
    assert f"quantlab {__version__}" in md
    assert __version__ == "1.0.0"


def test_absent_account_is_skipped_with_note(tmp_path) -> None:
    brokers = {"voltarget": _broker(101_000.0, 38_000.0, "SPY", 63_000.0), "trend": None}
    digest = _build(tmp_path, brokers)
    trend = next(a for a in digest.accounts if a.label == "trend")
    assert trend.available is False
    assert trend.note is not None
    # Combined only counts the available account.
    assert digest.combined_equity == pytest.approx(101_000.0)
    md = render_markdown(digest)
    assert "skipped" in md


def test_day_change_uses_per_label_equity_history(tmp_path) -> None:
    brokers = {
        "voltarget": _broker(101_000.0, 38_000.0, "SPY", 63_000.0),
        "trend": _broker(50_500.0, 20_000.0, "IEF", 30_000.0),
    }
    digest = _build(tmp_path, brokers)
    vt = next(a for a in digest.accounts if a.label == "voltarget")
    tr = next(a for a in digest.accounts if a.label == "trend")
    # voltarget prev snapshot 100000 -> +1%; trend prev 50000 -> +1%.
    assert vt.account.day_change_pct == pytest.approx(101_000.0 / 100_000.0 - 1.0)
    assert tr.account.day_change_pct == pytest.approx(50_500.0 / 50_000.0 - 1.0)
    # Track record spans each label's own first snapshot.
    assert vt.track_record.n_run_days == 2
    assert tr.track_record.n_run_days == 1


def test_positions_carry_unrealized_pnl(tmp_path) -> None:
    brokers = {"voltarget": _broker(101_000.0, 38_000.0, "SPY", 63_000.0), "trend": None}
    digest = _build(tmp_path, brokers)
    pos = digest.accounts[0].positions[0]
    cost = 80.0 * (63_000.0 / 80.0 - 1.0)
    assert pos.unrealized_pl == pytest.approx(63_000.0 - cost)


def test_same_day_rerun_overwrites(tmp_path) -> None:
    digests_dir = tmp_path / "digests"
    brokers = {"voltarget": _broker(101_000.0, 38_000.0, "SPY", 63_000.0), "trend": None}
    d1 = _build(tmp_path, brokers)
    md_path, _ = write_digest(d1, digests_dir=digests_dir)

    brokers2 = {"voltarget": _broker(95_000.0, 1_000.0, "SPY", 60_000.0), "trend": None}
    d2 = _build(tmp_path, brokers2, seed=False)
    md_path2, _ = write_digest(d2, digests_dir=digests_dir)

    assert md_path2 == md_path
    assert len(list(digests_dir.glob("digest_*.md"))) == 1
    assert "95,000.00" in md_path.read_text(encoding="utf-8")
