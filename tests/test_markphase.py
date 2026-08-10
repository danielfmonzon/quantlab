"""Mark-phase decomposition tests (measurement batch #3, DEFECT B).

No network, no market data: a real ``ParquetStore`` is seeded with synthetic bars and
run reports are hand-written, so every predicted figure is checkable by hand.

The anchor case is the one diagnosis #2 proved analytically: a position held with no
trading, where the week's mark-phase is exactly the difference of the two endpoint
remainders ``close/implied - 1``. The implementation sums per-session contributions
instead, which needs no share count and generalises to weight changes; these tests
pin the two forms to each other on the static case and then exercise the general one.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from quantlab.data import CANONICAL_COLUMNS
from quantlab.data.store import ParquetStore
from quantlab.reporting.markphase import load_mark_inputs, predicted_mark_phase_bps
from quantlab.reporting.weekly import session_for_mark

# A held share count, used only to turn implied prices into an independent
# endpoint-remainder cross-check. The implementation never sees it.
QTY = 100.0


def _seed_bars(store: ParquetStore, symbol: str, closes: dict[str, float]) -> None:
    frame = pd.DataFrame({
        "date": pd.to_datetime(list(closes)),
        **{c: list(closes.values()) for c in CANONICAL_COLUMNS if c != "date"},
    })
    store.upsert(symbol, frame[list(CANONICAL_COLUMNS)])


def _seed_run(
    reports_dir: Path, label: str, ts: str, *, equity: float, cash: float,
    symbol: str, sell: float = 0.0, buy: float = 0.0, aborted: bool = False,
    weights: dict[str, float] | None = None,
) -> None:
    """One run report carrying just the fields the decomposition reads."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    orders = []
    if buy:
        orders.append({"symbol": symbol, "side": "buy", "notional": buy})
    if sell:
        orders.append({"symbol": symbol, "side": "sell", "notional": sell})
    if weights is None:
        weights = {symbol: (equity - cash) / equity}
    payload = {
        "strategy": label, "timestamp": ts, "aborted": aborted, "equity": equity,
        "plan": {"cash": cash, "current_weights": weights},
        "submitted_orders": orders,
    }
    stamp = ts.replace(":", "").replace("-", "").replace("T", "").replace(".", "")
    (reports_dir / f"run_{label}_{stamp}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# The static-position anchor: summed contributions == endpoint remainders
# --------------------------------------------------------------------------

# A fully invested, never-trading week shaped like `trend`'s 2026-07-31..08-06:
# implied 10:00 marks and session closes that disagree, so mark-phase is non-zero.
_STATIC_MARKS: dict[str, float] = {   # mark date -> implied price at the mark
    "2026-07-31": 741.97,
    "2026-08-03": 753.2344,
    "2026-08-04": 763.225,
    "2026-08-05": 771.61,
    "2026-08-06": 770.99,
}
_STATIC_CLOSES: dict[str, float] = {  # session date -> that session's close
    "2026-07-30": 741.69,
    "2026-07-31": 747.03,
    "2026-08-03": 757.67,
    "2026-08-04": 771.33,
    "2026-08-05": 769.79,
    "2026-08-06": 768.56,
}


def _static_fixture(tmp_path: Path) -> tuple[ParquetStore, Path, list[date]]:
    store = ParquetStore(tmp_path / "eod")
    _seed_bars(store, "SPY", _STATIC_CLOSES)
    reports = tmp_path / "paper"
    for day, implied in _STATIC_MARKS.items():
        # Fully invested at the mark: cash 0, so equity - cash == qty * implied.
        _seed_run(reports, "trend", f"{day}T14:00:10", equity=QTY * implied,
                  cash=0.0, symbol="SPY")
    return store, reports, [date.fromisoformat(d) for d in _STATIC_MARKS]


def test_static_position_reproduces_the_endpoint_identity(tmp_path: Path) -> None:
    """A held-and-untraded week: summed contributions == rem[first] - rem[last].

    Diagnosis #2's exact identity for a static position. rem[t] = close[t]/implied[t]
    - 1, and every interior mark cancels, so the week depends only on its two edges.
    """
    store, reports, marks = _static_fixture(tmp_path)
    predicted = predicted_mark_phase_bps(
        "trend", "us_equity", marks, store, reports, session_for_mark
    )
    assert predicted is not None

    first, last = marks[0], marks[-1]
    rem_first = _STATIC_CLOSES[first.isoformat()] / _STATIC_MARKS[first.isoformat()] - 1
    rem_last = _STATIC_CLOSES[last.isoformat()] / _STATIC_MARKS[last.isoformat()] - 1
    endpoint_identity_bps = (rem_first - rem_last) * 1e4

    # The batch's acceptance bound. Observed agreement is ~0.1 bps; the two forms
    # differ only by the compounding the summed form does not carry.
    assert predicted == pytest.approx(endpoint_identity_bps, abs=0.5)
    # Teeth: the effect is real and large, so "agrees" cannot pass vacuously.
    assert abs(predicted) > 90.0


def test_static_position_matches_the_diagnosis_figure(tmp_path: Path) -> None:
    """The fixture is `trend`'s published week, so it must land on its measured value.

    Diagnosis #2 decomposed week 2026-08-07 as rem[07-31] +68.20 bps less rem[08-06]
    -31.52 bps = +99.71 bps predicted against a published +101.39 bps raw divergence.
    """
    store, reports, marks = _static_fixture(tmp_path)
    predicted = predicted_mark_phase_bps(
        "trend", "us_equity", marks, store, reports, session_for_mark
    )
    assert predicted == pytest.approx(99.71, abs=0.5)


def test_a_flat_mark_window_predicts_no_mark_phase(tmp_path: Path) -> None:
    """When the mark price and the close move identically, there is nothing to explain."""
    store = ParquetStore(tmp_path / "eod")
    closes = {"2026-08-02": 100.0, "2026-08-03": 110.0, "2026-08-04": 121.0}
    _seed_bars(store, "SPY", closes)
    reports = tmp_path / "paper"
    # Implied marks tracking the closes exactly (same +10% per session).
    for day, implied in [("2026-08-03", 100.0), ("2026-08-04", 110.0)]:
        _seed_run(reports, "trend", f"{day}T14:00:10", equity=QTY * implied,
                  cash=0.0, symbol="SPY")
    predicted = predicted_mark_phase_bps(
        "trend", "us_equity", [date(2026, 8, 3), date(2026, 8, 4)],
        store, reports, session_for_mark,
    )
    assert predicted == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------
# Weight changes: a distinct w_post per session
# --------------------------------------------------------------------------


def test_weight_change_scales_each_session_by_its_own_post_trade_weight(tmp_path: Path) -> None:
    """A voltarget-shaped week: two sessions, different weights, one rebalance.

    Session 1 is carried at ~60% and session 2 at ~30%, so a decomposition using one
    weight for the week cannot reproduce this; the per-session form must.
    """
    store = ParquetStore(tmp_path / "eod")
    # Close doubles on session 08-04; the mark window only sees a +50% move.
    _seed_bars(store, "SPY", {"2026-08-03": 100.0, "2026-08-04": 200.0,
                              "2026-08-05": 300.0})
    reports = tmp_path / "paper"
    # Mark A: equity 1000, position 600 (w=0.60), then sells 300 -> carries 300 (0.30).
    _seed_run(reports, "voltarget", "2026-08-03T14:00:10",
              equity=1000.0, cash=400.0, symbol="SPY", sell=300.0)
    # Mark B: the carried 300 became 450 -- a +50% mark-window move.
    _seed_run(reports, "voltarget", "2026-08-04T14:00:10",
              equity=1150.0, cash=700.0, symbol="SPY", sell=150.0)
    # Mark C: the carried 300 became 375 -- a +25% mark-window move.
    _seed_run(reports, "voltarget", "2026-08-05T14:00:10",
              equity=1225.0, cash=850.0, symbol="SPY")

    predicted = predicted_mark_phase_bps(
        "voltarget", "us_equity",
        [date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5)],
        store, reports, session_for_mark,
    )
    # Session 08-04: w_post 300/1000 = 0.30, mark +50%, close +100% -> 0.30*(-0.50).
    # Session 08-05: w_post 300/1150,       mark +25%, close  +50% -> w*(-0.25).
    expected = (0.30 * (0.50 - 1.00) + (300.0 / 1150.0) * (0.25 - 0.50)) * 1e4
    assert predicted == pytest.approx(expected, rel=1e-9)
    # And it is NOT what a single-weight-for-the-week shortcut would give.
    assert predicted != pytest.approx(0.30 * (0.50 - 1.00) * 2 * 1e4, rel=1e-6)


# --------------------------------------------------------------------------
# Crypto pairing flows through the decomposition too
# --------------------------------------------------------------------------


def test_crypto_prices_the_lagged_session(tmp_path: Path) -> None:
    """The session leg is read on the PAIRED session, so crypto reads day d-1.

    Otherwise the decomposition would explain a different session than the divergence
    it is subtracted from, and the residual would be meaningless.
    """
    store = ParquetStore(tmp_path / "eod")
    # Dashed symbol on purpose: the store maps BTC-USD onto the BTCUSD stem.
    _seed_bars(store, "BTC-USD", {"2026-08-03": 100.0, "2026-08-04": 110.0,
                                  "2026-08-05": 200.0})
    reports = tmp_path / "paper"
    _seed_run(reports, "crypto_voltarget", "2026-08-04T00:30:10",
              equity=1000.0, cash=0.0, symbol="BTC-USD")
    _seed_run(reports, "crypto_voltarget", "2026-08-05T00:30:10",
              equity=1100.0, cash=0.0, symbol="BTC-USD")
    predicted = predicted_mark_phase_bps(
        "crypto_voltarget", "crypto", [date(2026, 8, 4), date(2026, 8, 5)],
        store, reports, session_for_mark,
    )
    # Paired sessions are 08-03 -> 08-04: close +10%, and the mark window is +10% too.
    assert predicted == pytest.approx(0.0, abs=1e-6)
    # Under the pre-fix pairing (08-04 -> 08-05, close +81.8%) it would be far off.
    assert predicted != pytest.approx((0.10 - 0.818) * 1e4, rel=1e-3)


# --------------------------------------------------------------------------
# Unavailable inputs
# --------------------------------------------------------------------------


def test_missing_run_report_makes_the_prediction_unavailable(tmp_path: Path) -> None:
    store, reports, marks = _static_fixture(tmp_path)
    # Drop the middle mark's report; the others stay.
    for path in reports.glob("run_trend_20260804*.json"):
        path.unlink()
    assert load_mark_inputs("trend", reports, marks) is None
    assert predicted_mark_phase_bps(
        "trend", "us_equity", marks, store, reports, session_for_mark
    ) is None


def test_aborted_run_does_not_supply_a_mark(tmp_path: Path) -> None:
    """An aborted run wrote no equity mark, so its report must not stand in for one."""
    store, reports, marks = _static_fixture(tmp_path)
    for path in reports.glob("run_trend_20260804*.json"):
        path.unlink()
    _seed_run(reports, "trend", "2026-08-04T14:00:10", equity=1.0, cash=0.0,
              symbol="SPY", aborted=True)
    assert predicted_mark_phase_bps(
        "trend", "us_equity", marks, store, reports, session_for_mark
    ) is None


def test_multi_asset_holding_is_not_decomposable(tmp_path: Path) -> None:
    """Two non-zero weights: ``equity - cash`` is a basket, so no implied price exists."""
    store = ParquetStore(tmp_path / "eod")
    _seed_bars(store, "SPY", {"2026-08-03": 100.0, "2026-08-04": 110.0})
    reports = tmp_path / "paper"
    for day in ("2026-08-03", "2026-08-04"):
        _seed_run(reports, "trend", f"{day}T14:00:10", equity=1000.0, cash=0.0,
                  symbol="SPY", weights={"SPY": 0.6, "IEF": 0.4})
    assert predicted_mark_phase_bps(
        "trend", "us_equity", [date(2026, 8, 3), date(2026, 8, 4)],
        store, reports, session_for_mark,
    ) is None


def test_absent_price_history_makes_the_prediction_unavailable(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "eod")  # no bars seeded at all
    reports = tmp_path / "paper"
    for day in ("2026-08-03", "2026-08-04"):
        _seed_run(reports, "trend", f"{day}T14:00:10", equity=1000.0, cash=0.0,
                  symbol="SPY")
    assert predicted_mark_phase_bps(
        "trend", "us_equity", [date(2026, 8, 3), date(2026, 8, 4)],
        store, reports, session_for_mark,
    ) is None


def test_a_single_mark_cannot_be_decomposed(tmp_path: Path) -> None:
    store, reports, marks = _static_fixture(tmp_path)
    assert predicted_mark_phase_bps(
        "trend", "us_equity", marks[:1], store, reports, session_for_mark
    ) is None


def test_flat_into_a_window_contributes_nothing(tmp_path: Path) -> None:
    """Holding nothing across a window has no mark-phase, and must not divide by zero."""
    store = ParquetStore(tmp_path / "eod")
    _seed_bars(store, "SPY", {"2026-08-03": 100.0, "2026-08-04": 110.0})
    reports = tmp_path / "paper"
    # All cash at the first mark, and it sells nothing: carried value is 0.
    _seed_run(reports, "trend", "2026-08-03T14:00:10", equity=1000.0, cash=1000.0,
              symbol="SPY", weights={"SPY": 0.0})
    _seed_run(reports, "trend", "2026-08-04T14:00:10", equity=1000.0, cash=1000.0,
              symbol="SPY", weights={"SPY": 0.0})
    # A zero weight is not a holding, so the symbol is not well defined -> unavailable.
    assert predicted_mark_phase_bps(
        "trend", "us_equity", [date(2026, 8, 3), date(2026, 8, 4)],
        store, reports, session_for_mark,
    ) is None


def test_last_report_of_a_day_supplies_that_day_s_mark(tmp_path: Path) -> None:
    """The review keeps a day's LAST mark, so the decomposition must use its report."""
    store = ParquetStore(tmp_path / "eod")
    _seed_bars(store, "SPY", {"2026-08-03": 100.0, "2026-08-04": 100.0})
    reports = tmp_path / "paper"
    _seed_run(reports, "trend", "2026-08-03T14:00:10", equity=1000.0, cash=0.0,
              symbol="SPY")
    # Two reports on 08-04; the later one carries the equity the review marked.
    _seed_run(reports, "trend", "2026-08-04T05:00:10", equity=1111.0, cash=0.0,
              symbol="SPY")
    _seed_run(reports, "trend", "2026-08-04T14:00:10", equity=2000.0, cash=0.0,
              symbol="SPY")
    inputs = load_mark_inputs("trend", reports, [date(2026, 8, 3), date(2026, 8, 4)])
    assert inputs is not None
    assert inputs[date(2026, 8, 4)].equity == 2000.0
