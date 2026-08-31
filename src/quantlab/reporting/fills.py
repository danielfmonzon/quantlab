"""Fill-vs-mark ledger: what every order actually cost, from the fills themselves.

WHY THIS EXISTS. The shadow charges a flat 5 bps one-way, and the 2026-08-10 turnover
entry says exactly what that figure is: *modeled*, never validated against a fill, with
the sign of its error unknown. It queues the validation as day-90 revisit item (b) — "the
5 bps assumption tested against actual paper fill prices versus the marks" — and until
PROP-5 landed there was nothing in the system that could answer it.

Divergence diagnosis #3 needed this number for exactly one order and had to infer it from
the difference between two equity-history marks, then corroborate it by backing an implied
price out of position value and testing it against that session's high-low bar. It worked,
and it worked only because the account happened to hold one asset and to trade once. The
figure it produced — **+172.6 bps in the account's favour on a $70,218.29 sell** — is
recorded as an open live-readiness exposure precisely because a gain that size will not
reproduce live. One order is not a distribution.

READS FILLS, AND NOTHING ELSE. No equity deltas, no implied prices, no reconstruction.
Every row here comes from ``submitted_orders`` in a run report: the notional the run asked
for, and the ``filled_qty`` / ``filled_avg_price`` the broker returned. An order whose
report predates the instrumentation reads **not captured** — never zero, because zero
asserts the order filled exactly at its mark, which is the claim diagnosis #3 had to
disprove by hand.

THE ARITHMETIC. The runner submits notional orders: it names a dollar amount ``N`` and the
broker converts it to a quantity at the price it saw. So the mark the order was sized
against is implied by the fill itself::

    implied_mark = N / filled_qty
    filled_value = filled_qty * filled_avg_price
    deviation    = filled_value / N - 1

``deviation`` is signed by the market, not by whether it helped. A sell that realises more
than its notional is favourable; a buy that costs more than its notional is adverse. The
reported figure flips the buy so that **positive always means favourable to the account**,
because a ledger whose sign convention depends on the side is one every reader has to
re-derive at the point they are trying to draw a conclusion.

Sanity check against the case that motivated it: the 2026-08-22 repair sold $70,218.29 of
notional and realised $71,430.49, giving 71,430.49 / 70,218.29 − 1 = **+172.6 bps
favourable** — the figure diagnosis #3 reached from equity deltas, now read off the report.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from quantlab.config import APPROVED_STRATEGIES
from quantlab.paper.runner import PAPER_REPORTS_DIR

# Reports written before PROP-5 carry no fill fields at all. Their rows say so.
NOT_CAPTURED = "no fill data captured"


class FillRow(BaseModel):
    """One submitted order, and what became of it."""

    label: str
    timestamp: datetime
    symbol: str
    side: str
    submitted_notional: float
    filled_qty: float | None = None
    filled_avg_price: float | None = None

    @property
    def captured(self) -> bool:
        """Whether this order carries the evidence the ledger is built on."""
        return (
            self.filled_qty is not None
            and self.filled_avg_price is not None
            and self.filled_qty > 0.0
            and self.submitted_notional > 0.0
        )

    @property
    def filled_value(self) -> float | None:
        if not self.captured:
            return None
        assert self.filled_qty is not None and self.filled_avg_price is not None
        return self.filled_qty * self.filled_avg_price

    @property
    def implied_mark(self) -> float | None:
        """The price the order was SIZED against: notional / quantity actually filled."""
        if not self.captured:
            return None
        assert self.filled_qty is not None
        return self.submitted_notional / self.filled_qty

    @property
    def fill_vs_mark_bps(self) -> float | None:
        """Signed so POSITIVE IS ALWAYS FAVOURABLE, whichever side the order was.

        A sell realising more than its notional helped; a buy costing more than its
        notional hurt. Both are the same raw deviation with opposite meanings, and
        leaving the reader to apply that flip is how a ledger gets misread.
        """
        value = self.filled_value
        if value is None:
            return None
        deviation = value / self.submitted_notional - 1.0
        if not math.isfinite(deviation):
            return None
        return deviation * 1e4 * (-1.0 if self.side.lower() == "buy" else 1.0)

    def render(self) -> str:
        if not self.captured:
            return (
                f"| {self.timestamp:%Y-%m-%d %H:%M}Z | {self.label} | {self.symbol} "
                f"| {self.side} | {self.submitted_notional:,.2f} | — | — | "
                f"_{NOT_CAPTURED}_ |"
            )
        return (
            f"| {self.timestamp:%Y-%m-%d %H:%M}Z | {self.label} | {self.symbol} "
            f"| {self.side} | {self.submitted_notional:,.2f} "
            f"| {self.filled_value:,.2f} | {self.implied_mark:,.2f} "
            f"| {self.fill_vs_mark_bps:+.1f} |"
        )


class FillDistribution(BaseModel):
    """The shape of the fill-vs-mark population since instrumentation began.

    This is the figure that replaces the 5 bps assumption — or fails to, which is an
    answer too. Orders with no captured fill are EXCLUDED rather than counted as zero:
    including them would drag every statistic toward a value no order was observed to
    have.
    """

    n: int
    mean_bps: float | None = None
    median_bps: float | None = None
    p5_bps: float | None = None
    p95_bps: float | None = None
    n_uncaptured: int = 0

    def render(self) -> list[str]:
        if self.n == 0:
            return [
                "- **distribution: nothing recorded yet** — no order in the window "
                "carries fill evidence.",
                f"- orders without captured fills: {self.n_uncaptured}",
            ]
        return [
            f"- **distribution over {self.n} captured fill(s)** "
            f"(positive = favourable to the account):",
            f"  - mean {self.mean_bps:+.1f} bps  |  median {self.median_bps:+.1f} bps",
            f"  - p5 {self.p5_bps:+.1f} bps  |  p95 {self.p95_bps:+.1f} bps",
            f"- orders without captured fills (pre-instrumentation): {self.n_uncaptured}",
        ]


class FillLedger(BaseModel):
    rows: list[FillRow] = []
    distribution: FillDistribution

    def render(self) -> list[str]:
        lines = ["## Fill-vs-mark ledger", ""]
        if not self.rows:
            lines.append("_No submitted orders on record._")
            lines.append("")
            return lines
        lines.append(
            "| mark | account | symbol | side | submitted | filled value "
            "| implied mark | vs mark (bps) |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|")
        lines.extend(r.render() for r in self.rows)
        lines.append("")
        lines.extend(self.distribution.render())
        lines.append(
            "- _read from recorded fills only — never inferred from account deltas. "
            "The 2026-08-22 +172.6 bps order predates instrumentation and stays "
            "annotated as unexplained in the decision log; it cannot be retrofitted._"
        )
        lines.append("")
        return lines


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile. No numpy dependency for four numbers."""
    if not values:
        raise ValueError("percentile of an empty population")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def summarise(rows: list[FillRow]) -> FillDistribution:
    captured = [r.fill_vs_mark_bps for r in rows if r.fill_vs_mark_bps is not None]
    uncaptured = sum(1 for r in rows if not r.captured)
    if not captured:
        return FillDistribution(n=0, n_uncaptured=uncaptured)
    ordered = sorted(captured)
    mid = len(ordered) // 2
    median = (
        ordered[mid] if len(ordered) % 2
        else (ordered[mid - 1] + ordered[mid]) / 2.0
    )
    return FillDistribution(
        n=len(ordered),
        mean_bps=sum(ordered) / len(ordered),
        median_bps=median,
        p5_bps=_percentile(ordered, 0.05),
        p95_bps=_percentile(ordered, 0.95),
        n_uncaptured=uncaptured,
    )


def _numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def load_fill_rows(
    paper_reports_dir: Path | None = None,
    labels: list[str] | None = None,
) -> list[FillRow]:
    """Every submitted order across every run report, oldest first.

    A malformed report is skipped rather than failing the ledger: this is reporting, and
    one unreadable file must not hide every readable one.
    """
    directory = paper_reports_dir if paper_reports_dir is not None else PAPER_REPORTS_DIR
    wanted = labels if labels is not None else list(APPROVED_STRATEGIES)
    rows: list[FillRow] = []
    if not directory.exists():
        return rows
    for path in sorted(directory.glob("run_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        label = str(payload.get("strategy", ""))
        if label not in wanted:
            continue
        stamp = payload.get("timestamp")
        if not isinstance(stamp, str):
            continue
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        orders = payload.get("submitted_orders")
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, dict):
                continue
            notional = _numeric(order.get("notional"))
            if notional is None:
                continue
            rows.append(FillRow(
                label=label, timestamp=when,
                symbol=str(order.get("symbol", "")),
                side=str(order.get("side", "")),
                submitted_notional=notional,
                filled_qty=_numeric(order.get("filled_qty")),
                filled_avg_price=_numeric(order.get("filled_avg_price")),
            ))
    rows.sort(key=lambda r: (r.timestamp, r.label, r.symbol))
    return rows


def build_fill_ledger(
    paper_reports_dir: Path | None = None,
    labels: list[str] | None = None,
) -> FillLedger:
    rows = load_fill_rows(paper_reports_dir, labels)
    return FillLedger(rows=rows, distribution=summarise(rows))


__all__ = [
    "NOT_CAPTURED",
    "FillDistribution",
    "FillLedger",
    "FillRow",
    "build_fill_ledger",
    "load_fill_rows",
    "summarise",
]
