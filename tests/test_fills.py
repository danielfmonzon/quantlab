"""Fill-vs-mark ledger tests (PROP-10).

Every figure here is hand-checkable. The anchor case is three synthetic orders whose
recorded fills land 1% above, exactly at, and 1% below the price their notional implied,
because that is the shape the day-90 cost question needs answered: not one number, a
distribution.

Nothing reads a real report directory and nothing infers from account deltas -- the whole
point of the module under test is that it reads recorded fills and only recorded fills.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantlab.reporting.fills import (
    NOT_CAPTURED,
    FillRow,
    build_fill_ledger,
    load_fill_rows,
    summarise,
)

MARK = 100.0
QTY = 10.0
NOTIONAL = MARK * QTY          # 1,000 -- so implied_mark == MARK exactly


def _seed(
    reports: Path, label: str, ts: str, side: str, notional: float,
    *, filled_qty: float | None = None, filled_avg_price: float | None = None,
) -> None:
    reports.mkdir(parents=True, exist_ok=True)
    order: dict[str, object] = {
        "symbol": "SPY", "side": side, "notional": notional,
    }
    if filled_qty is not None:
        order["filled_qty"] = filled_qty
    if filled_avg_price is not None:
        order["filled_avg_price"] = filled_avg_price
    payload = {
        "strategy": label, "timestamp": ts, "aborted": False,
        "submitted_orders": [order],
    }
    stamp = ts.replace(":", "").replace("-", "").replace("T", "").replace("Z", "")
    (reports / f"run_{label}_{stamp}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _three_fills(tmp_path: Path) -> Path:
    """Sells filling +1%, 0% and -1% away from the mark their notional implied."""
    reports = tmp_path / "paper"
    for day, price in (("03", MARK * 1.01), ("04", MARK), ("05", MARK * 0.99)):
        _seed(reports, "trend", f"2026-09-{day}T14:00:00Z", "sell", NOTIONAL,
              filled_qty=QTY, filled_avg_price=price)
    return reports


# --------------------------------------------------------------------------
# The acceptance case
# --------------------------------------------------------------------------

def test_three_fills_at_plus_one_zero_and_minus_one_percent(tmp_path: Path) -> None:
    """+100, 0, -100 bps -- the deviation is the fill price against the implied mark."""
    ledger = build_fill_ledger(_three_fills(tmp_path), labels=["trend"])

    assert [r.side for r in ledger.rows] == ["sell", "sell", "sell"]
    measured = [r.fill_vs_mark_bps for r in ledger.rows]
    assert measured[0] == pytest.approx(100.0, abs=0.01)
    assert measured[1] == pytest.approx(0.0, abs=1e-9)
    assert measured[2] == pytest.approx(-100.0, abs=0.01)

    # The implied mark is recovered from notional / filled_qty, not supplied.
    for row in ledger.rows:
        assert row.implied_mark == pytest.approx(MARK)
        assert row.filled_value == pytest.approx(row.filled_qty * row.filled_avg_price)


def test_the_distribution_over_those_three(tmp_path: Path) -> None:
    """n, mean, median and the outer percentiles, all hand-checkable."""
    dist = build_fill_ledger(_three_fills(tmp_path), labels=["trend"]).distribution

    assert dist.n == 3
    assert dist.n_uncaptured == 0
    assert dist.mean_bps == pytest.approx(0.0, abs=1e-9)
    assert dist.median_bps == pytest.approx(0.0, abs=1e-9)
    # Linear interpolation over [-100, 0, +100]: p5 and p95 sit 5% in from each end.
    assert dist.p5_bps == pytest.approx(-90.0, abs=0.01)
    assert dist.p95_bps == pytest.approx(90.0, abs=0.01)

    rendered = "\n".join(dist.render())
    assert "distribution over 3 captured fill(s)" in rendered
    assert "positive = favourable" in rendered


# --------------------------------------------------------------------------
# Sign convention: positive is favourable, whichever side
# --------------------------------------------------------------------------

def test_a_sell_above_its_mark_is_favourable_and_a_buy_above_it_is_adverse() -> None:
    """The same raw deviation means opposite things, and the ledger applies the flip.

    Leaving the reader to do it is how a ledger gets misread at exactly the moment
    someone is trying to draw a cost conclusion from it.
    """
    sell = FillRow(label="x", timestamp="2026-09-03T14:00:00Z", symbol="SPY",
                   side="sell", submitted_notional=NOTIONAL,
                   filled_qty=QTY, filled_avg_price=MARK * 1.01)
    buy = FillRow(label="x", timestamp="2026-09-03T14:00:00Z", symbol="SPY",
                  side="buy", submitted_notional=NOTIONAL,
                  filled_qty=QTY, filled_avg_price=MARK * 1.01)

    assert sell.fill_vs_mark_bps == pytest.approx(100.0, abs=0.01)     # realised more
    assert buy.fill_vs_mark_bps == pytest.approx(-100.0, abs=0.01)     # paid more


def test_it_reproduces_the_2026_08_22_figure() -> None:
    """The order diagnosis #3 had to infer, now read straight off a report.

    +172.6 bps favourable on a $70,218.29 sell that realised $71,430.49. That order's
    real report predates the instrumentation and stays unexplained; this asserts the
    arithmetic, not a retrofit.
    """
    row = FillRow(
        label="crypto_voltarget", timestamp="2026-08-22T16:24:21Z", symbol="BTC-USD",
        side="sell", submitted_notional=70_218.29,
        filled_qty=0.921208, filled_avg_price=77_540.06,
    )
    assert row.filled_value == pytest.approx(71_430.49, abs=0.5)
    assert row.fill_vs_mark_bps == pytest.approx(172.6, abs=0.5)


# --------------------------------------------------------------------------
# Absence is not zero
# --------------------------------------------------------------------------

def test_an_order_without_fill_evidence_reads_not_captured(tmp_path: Path) -> None:
    """Zero would assert it filled exactly at its mark -- the claim #3 disproved."""
    reports = tmp_path / "paper"
    _seed(reports, "trend", "2026-09-03T14:00:00Z", "sell", NOTIONAL)

    ledger = build_fill_ledger(reports, labels=["trend"])
    assert len(ledger.rows) == 1
    row = ledger.rows[0]
    assert row.captured is False
    assert row.fill_vs_mark_bps is None
    assert row.filled_value is None
    assert row.implied_mark is None
    assert NOT_CAPTURED in row.render()


def test_uncaptured_orders_are_excluded_from_the_distribution(tmp_path: Path) -> None:
    """Counting them as zero would drag every statistic toward a value none had."""
    reports = _three_fills(tmp_path)
    _seed(reports, "trend", "2026-09-06T14:00:00Z", "sell", NOTIONAL)

    dist = build_fill_ledger(reports, labels=["trend"]).distribution
    assert dist.n == 3                    # not 4
    assert dist.n_uncaptured == 1
    assert dist.mean_bps == pytest.approx(0.0, abs=1e-9)


def test_an_empty_population_renders_an_explicit_nothing_line(tmp_path: Path) -> None:
    """A section that vanishes when empty is one nobody notices has stopped working."""
    reports = tmp_path / "paper"
    _seed(reports, "trend", "2026-09-03T14:00:00Z", "sell", NOTIONAL)

    rendered = "\n".join(build_fill_ledger(reports, labels=["trend"]).render())
    assert "distribution: nothing recorded yet" in rendered
    assert "orders without captured fills: 1" in rendered


def test_no_reports_at_all_still_renders_a_section(tmp_path: Path) -> None:
    rendered = "\n".join(build_fill_ledger(tmp_path / "nope", labels=["trend"]).render())
    assert "Fill-vs-mark ledger" in rendered
    assert "No submitted orders on record." in rendered


# --------------------------------------------------------------------------
# Robustness: reporting must not be able to break on a bad file
# --------------------------------------------------------------------------

def test_a_malformed_report_is_skipped_not_fatal(tmp_path: Path) -> None:
    """One unreadable file must not hide every readable one."""
    reports = _three_fills(tmp_path)
    (reports / "run_trend_99999999T000000.json").write_text("{ not json", encoding="utf-8")

    assert len(load_fill_rows(reports, labels=["trend"])) == 3


def test_a_non_finite_fill_is_treated_as_uncaptured(tmp_path: Path) -> None:
    """nan and inf are the PROP-5 amendment's concern, honoured here too."""
    reports = tmp_path / "paper"
    reports.mkdir(parents=True)
    (reports / "run_trend_20260903T140000.json").write_text(json.dumps({
        "strategy": "trend", "timestamp": "2026-09-03T14:00:00Z", "aborted": False,
        "submitted_orders": [{
            "symbol": "SPY", "side": "sell", "notional": NOTIONAL,
            "filled_qty": "nan", "filled_avg_price": "inf",
        }],
    }), encoding="utf-8")

    rows = load_fill_rows(reports, labels=["trend"])
    assert len(rows) == 1
    assert rows[0].captured is False


def test_rows_are_ordered_oldest_first(tmp_path: Path) -> None:
    rows = load_fill_rows(_three_fills(tmp_path), labels=["trend"])
    assert [r.timestamp.day for r in rows] == [3, 4, 5]


def test_a_single_captured_fill_summarises_without_dividing_by_zero() -> None:
    """One observation is a legitimate population; the percentiles collapse onto it."""
    row = FillRow(label="x", timestamp="2026-09-03T14:00:00Z", symbol="SPY",
                  side="sell", submitted_notional=NOTIONAL,
                  filled_qty=QTY, filled_avg_price=MARK * 1.01)
    dist = summarise([row])
    assert dist.n == 1
    assert dist.mean_bps == pytest.approx(100.0, abs=0.01)
    assert dist.median_bps == pytest.approx(100.0, abs=0.01)
    assert dist.p5_bps == pytest.approx(100.0, abs=0.01)
    assert dist.p95_bps == pytest.approx(100.0, abs=0.01)
