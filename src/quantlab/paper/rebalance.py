"""Turn target weights + current positions into a safe, ordered order plan.

Design points:

* SELLS FIRST, then buys — selling frees cash before any buy spends it.
* A symbol held but absent from ``targets`` gets target 0 (liquidated if the gap
  exceeds ``min_trade_frac``).
* Cash is the implicit remainder and is never allowed to go negative: total buy
  notional may not exceed available cash + proceeds of the planned sells. If it
  would, every buy is scaled down proportionally and the scale factor is recorded.
* Diffs at or below ``min_trade_frac`` are skipped (no churn on tiny drift).
* FULL EXITS ARE SIZED IN QUANTITY (2026-11-16 ruling). A sell to target 0, or one
  that would leave less than ``min_trade_frac`` of equity behind, carries ``qty`` =
  the held ``Position.qty`` and sells the whole position. A dollar-sized exit is
  converted at the broker's execution price, and when that price is below the
  price the position is valued at, the order asks for more than is held and is rejected.
  Buys and every other sell keep the notional path unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel

_SIDE_BUY = "buy"
_SIDE_SELL = "sell"


class OrderIntent(BaseModel):
    """A single intended trade toward the target weight."""

    symbol: str
    side: str
    notional: float
    current_w: float
    target_w: float
    # Set only on a full exit: sell exactly this held quantity instead of ``notional``
    # dollars. ``notional`` then stays as the position's value, for reporting and the
    # cash-feasibility arithmetic.
    qty: float | None = None


class SkippedDiff(BaseModel):
    """A below-threshold weight gap that was intentionally not traded."""

    symbol: str
    current_w: float
    target_w: float
    diff: float


class RebalancePlan(BaseModel):
    """An ordered, cash-feasible set of order intents (sells before buys)."""

    equity: float
    cash: float
    current_weights: dict[str, float]
    target_weights: dict[str, float]
    intents: list[OrderIntent]
    skipped: list[SkippedDiff]
    est_turnover: float
    buy_scale: float
    min_trade_frac: float


def plan_rebalance(
    targets: dict[str, float],
    equity: float,
    positions: list,  # list[Position]; typed loosely to avoid a broker import
    min_trade_frac: float = 0.01,
) -> RebalancePlan:
    """Build a :class:`RebalancePlan` converging current holdings toward ``targets``."""
    if equity <= 0.0:
        raise ValueError("plan_rebalance requires positive equity")

    current_mv = {p.symbol: float(p.market_value) for p in positions}
    held_qty = {p.symbol: float(p.qty) for p in positions}
    invested = sum(current_mv.values())
    cash = equity - invested

    current_weights = {sym: mv / equity for sym, mv in current_mv.items()}
    # Symbols held but not targeted are liquidation candidates (target 0).
    universe = sorted(set(targets) | set(current_mv))
    target_weights = {sym: float(targets.get(sym, 0.0)) for sym in universe}

    sells: list[OrderIntent] = []
    buys: list[OrderIntent] = []
    skipped: list[SkippedDiff] = []
    est_turnover = 0.0

    for sym in universe:
        cur = current_weights.get(sym, 0.0)
        tgt = target_weights[sym]
        diff = tgt - cur
        if abs(diff) <= min_trade_frac:
            if abs(diff) > 0.0:
                skipped.append(
                    SkippedDiff(symbol=sym, current_w=cur, target_w=tgt, diff=diff)
                )
            continue
        qty = held_qty.get(sym, 0.0)
        # A sell whose remainder would fall below the existing trade threshold is a
        # full exit: the leftover could never be traded away on its own.
        full_exit = diff < 0 and (tgt <= 0.0 or tgt < min_trade_frac) and qty > 0.0
        traded_w = cur if full_exit else abs(diff)
        est_turnover += traded_w
        notional = traded_w * equity
        intent = OrderIntent(
            symbol=sym, side=_SIDE_BUY if diff > 0 else _SIDE_SELL,
            notional=notional, current_w=cur, target_w=tgt,
            qty=qty if full_exit else None,
        )
        (buys if diff > 0 else sells).append(intent)

    # Cash feasibility: buys may spend at most cash + proceeds of the sells.
    total_sell = sum(i.notional for i in sells)
    total_buy = sum(i.notional for i in buys)
    available = cash + total_sell
    buy_scale = 1.0
    if total_buy > available and total_buy > 0.0:
        buy_scale = max(0.0, available) / total_buy
        buys = [i.model_copy(update={"notional": i.notional * buy_scale}) for i in buys]

    return RebalancePlan(
        equity=equity,
        cash=cash,
        current_weights=current_weights,
        target_weights=target_weights,
        intents=[*sells, *buys],  # sells first, then (possibly scaled) buys
        skipped=skipped,
        est_turnover=est_turnover,
        buy_scale=buy_scale,
        min_trade_frac=min_trade_frac,
    )


__all__ = ["plan_rebalance", "RebalancePlan", "OrderIntent", "SkippedDiff"]
