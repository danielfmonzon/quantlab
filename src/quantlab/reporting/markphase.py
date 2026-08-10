"""Mark-phase decomposition: how much of a week's divergence is measurement geometry.

Report-only. Paper equity is marked when the scheduled run fires; the shadow is
close-to-close. For a position held across a mark window, the paper "daily" return
prices the asset from mark to mark while the shadow prices it from close to close,
so the two differ by the *remainder* of each session between the mark and the close.
That difference is arithmetic, not tracking error, and this module quantifies it so
the verdict can be taken on what is left over.

METHOD (2026-08-10 divergence diagnosis #2, docs/decisions.md). For a single-asset
holding the paper mark price is implied directly by the account: the non-cash value
``V = equity - cash`` is that one position, so ``V / qty`` is its price at the mark
instant. Diagnosis #2 verified this against ``trend``'s constant 133.028241898 SPY —
every implied price landed inside its session's low-high range — and used it to
predict each daily gap to within 0.1-2.8 bps.

``qty`` never appears below, because only price RATIOS are needed. Between two marks
``a`` and ``b``, with ``N`` the signed notional traded at ``a`` (buys positive), the
share count is constant across the window, so::

    r_mark = V_b / (V_a + N)  - 1        the held asset's move over the mark window
    w_post = (V_a + N) / equity_a       the weight actually carried into the window

and cash earns nothing in the paper account, so ``paper_return = w_post * r_mark``
exactly. Against the shadow's ``w * r_session`` the per-session contribution is::

    contribution = w_post * (r_mark - r_session)

Summing those contributions over the window is the telescoped form of the endpoint
remainders ``w * (close/implied - 1)`` that diagnosis #2 evaluated at the window
edges. The two agree to 0.11 bps on ``trend``'s static week (a test pins <0.5 bps),
and the summed form is what is implemented here for two reasons: it needs no absolute
share count, and it carries a distinct ``w_post`` per session, so a week with daily
weight changes decomposes correctly rather than assuming one weight throughout.

``r_session`` is read on the session the interval is PAIRED with, per
``weekly.session_for_mark`` — the crypto LAG-1 offset applies here too, so the
decomposition and the divergence it explains always speak about the same sessions.

UNAVAILABLE INPUTS. The decomposition needs a run report for every mark in the
window. When one is missing, or when the account was not holding exactly one symbol,
the week's prediction is ``None`` and the weekly review falls back to thresholding
the raw divergence, flagged so a reader can tell a fallback from a clean pass.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd

from quantlab.data.store import ParquetStore

# The shadow compounds adj_close returns (reporting.shadow), so the session leg of
# every contribution must be read off the same column.
_PRICE_COLUMN = "adj_close"


class MarkPhaseInputs:
    """One mark's decomposition inputs, read from that run's report.

    ``position_value`` is the non-cash value at the mark (``equity - cash``) and
    ``traded_notional`` is signed (buys positive), so ``position_value +
    traded_notional`` is the value carried into the next mark window.
    """

    __slots__ = ("mark_date", "equity", "position_value", "traded_notional", "symbol")

    def __init__(self, mark_date: date, equity: float, position_value: float,
                 traded_notional: float, symbol: str) -> None:
        self.mark_date = mark_date
        self.equity = equity
        self.position_value = position_value
        self.traded_notional = traded_notional
        self.symbol = symbol


def _held_symbol(payload: dict[str, object]) -> str | None:
    """The single symbol this run was holding, or None when that is not well defined.

    Reads ``plan.current_weights`` — the weights observed at the mark, before the
    run's own orders. A zero weight is not a holding; two or more non-zero weights
    mean the implied-price identity does not apply, because ``equity - cash`` is then
    a basket and no single price can be backed out of it.
    """
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return None
    weights = plan.get("current_weights")
    if not isinstance(weights, dict):
        return None
    held = [str(s) for s, w in weights.items() if isinstance(w, (int, float)) and w != 0.0]
    if len(held) != 1:
        return None
    return held[0]


def _signed_notional(payload: dict[str, object]) -> float:
    """Net notional submitted by this run, buys positive.

    Submitted rather than filled: the runner's orders are notional market orders and
    diagnosis #2 confirmed submitted notional reproduces ``plan.est_turnover`` exactly
    on every run in the studied period. Fill-vs-mark slippage is deliberately left in
    the residual instead of being modelled away here.
    """
    orders = payload.get("submitted_orders")
    if not isinstance(orders, list):
        return 0.0
    total = 0.0
    for order in orders:
        if not isinstance(order, dict):
            continue
        notional = order.get("notional")
        if not isinstance(notional, (int, float)):
            continue
        sign = -1.0 if str(order.get("side", "")).lower() == "sell" else 1.0
        total += sign * float(notional)
    return total


def load_mark_inputs(
    label: str, paper_reports_dir: Path, mark_dates: list[date]
) -> dict[date, MarkPhaseInputs] | None:
    """Decomposition inputs for each of ``mark_dates``, or None if any is missing.

    Keyed by mark date because the weekly review has already collapsed the history to
    one mark per day; when a day carries several run reports the LAST one is used, to
    match ``weekly._last_snapshot_per_day`` keeping the last mark of each day.
    """
    if not paper_reports_dir.exists():
        return None
    wanted = set(mark_dates)
    found: dict[date, MarkPhaseInputs] = {}
    for path in sorted(paper_reports_dir.glob(f"run_{label}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        ts = payload.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            run_date = pd.Timestamp(ts).date()
        except ValueError:
            continue
        if run_date not in wanted or payload.get("aborted"):
            continue
        plan = payload.get("plan")
        equity = payload.get("equity")
        if not isinstance(plan, dict) or not isinstance(equity, (int, float)):
            continue
        cash = plan.get("cash")
        symbol = _held_symbol(payload)
        if not isinstance(cash, (int, float)) or symbol is None:
            continue
        found[run_date] = MarkPhaseInputs(
            mark_date=run_date, equity=float(equity),
            position_value=float(equity) - float(cash),
            traded_notional=_signed_notional(payload), symbol=symbol,
        )
    missing = wanted - set(found)
    if missing:
        return None
    return found


def _session_prices(store: ParquetStore, symbol: str) -> pd.Series | None:
    """``symbol``'s adj_close series indexed by session date, or None if absent.

    ``store.load`` already returns an empty frame for a symbol it has never seen, and
    it maps dashed crypto symbols onto their stored stem (``BTC-USD`` -> ``BTCUSD``),
    so no separate existence check or symbol rewriting is needed here.
    """
    frame = store.load(symbol)
    if frame.empty or _PRICE_COLUMN not in frame.columns:
        return None
    series = pd.Series(
        frame[_PRICE_COLUMN].to_numpy(dtype=float),
        index=[pd.Timestamp(d).date() for d in frame["date"]],
    )
    return series[~series.index.duplicated(keep="last")]


def predicted_mark_phase_bps(
    label: str,
    asset_class: str,
    mark_dates: list[date],
    store: ParquetStore,
    paper_reports_dir: Path,
    session_for_mark: Callable[[date, str], date],
) -> float | None:
    """Mark-phase bps predicted for the window spanned by ``mark_dates``.

    ``mark_dates`` must be the window's marks in order, oldest first; the first opens
    the window rather than closing an interval. Returns None when any input is
    missing (see module docstring) so the caller can fall back rather than report a
    decomposition built on a hole.
    """
    if len(mark_dates) < 2:
        return None
    inputs = load_mark_inputs(label, paper_reports_dir, mark_dates)
    if inputs is None:
        return None

    prices_by_symbol: dict[str, pd.Series | None] = {}
    total = 0.0
    for previous_date, current_date in zip(mark_dates[:-1], mark_dates[1:], strict=True):
        before, after = inputs[previous_date], inputs[current_date]
        carried = before.position_value + before.traded_notional
        if carried == 0.0 or before.equity == 0.0:
            # Flat into this window: no held asset, so no mark-phase effect to price.
            continue
        symbol = before.symbol
        if symbol not in prices_by_symbol:
            prices_by_symbol[symbol] = _session_prices(store, symbol)
        prices = prices_by_symbol[symbol]
        if prices is None:
            return None
        session_before = session_for_mark(previous_date, asset_class)
        session_after = session_for_mark(current_date, asset_class)
        if session_before not in prices.index or session_after not in prices.index:
            return None
        r_mark = after.position_value / carried - 1.0
        r_session = float(prices[session_after]) / float(prices[session_before]) - 1.0
        w_post = carried / before.equity
        total += w_post * (r_mark - r_session)
    return total * 1e4


__all__ = [
    "MarkPhaseInputs",
    "load_mark_inputs",
    "predicted_mark_phase_bps",
]
