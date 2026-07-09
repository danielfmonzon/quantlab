"""Rebalance planner tests: ordering, thresholds, liquidation, cash feasibility."""

from __future__ import annotations

import pytest

from quantlab.broker.alpaca_trading import Position
from quantlab.paper.rebalance import plan_rebalance


def _pos(symbol: str, market_value: float) -> Position:
    return Position(symbol=symbol, qty=1.0, market_value=market_value, avg_entry_price=1.0)


def test_sells_come_before_buys() -> None:
    plan = plan_rebalance(
        {"A": 0.2, "C": 0.3},  # B absent -> liquidate
        equity=10_000.0,
        positions=[_pos("A", 5_000.0), _pos("B", 5_000.0)],
    )
    sides = [i.side for i in plan.intents]
    assert sides == ["sell", "sell", "buy"]
    # A trims (.5->.2), B liquidates (.5->0), C is the only buy.
    assert {i.symbol for i in plan.intents if i.side == "sell"} == {"A", "B"}
    assert [i.symbol for i in plan.intents if i.side == "buy"] == ["C"]


def test_subthreshold_diff_is_skipped_not_traded() -> None:
    plan = plan_rebalance(
        {"A": 0.505},  # diff 0.005 <= min_trade_frac
        equity=10_000.0,
        positions=[_pos("A", 5_000.0)],
        min_trade_frac=0.01,
    )
    assert plan.intents == []
    assert len(plan.skipped) == 1
    assert plan.skipped[0].symbol == "A"
    assert plan.skipped[0].diff == pytest.approx(0.005)


def test_symbol_missing_from_targets_is_liquidated() -> None:
    plan = plan_rebalance(
        {},  # no targets at all
        equity=10_000.0,
        positions=[_pos("X", 3_000.0)],
    )
    assert len(plan.intents) == 1
    intent = plan.intents[0]
    assert intent.side == "sell" and intent.symbol == "X"
    assert intent.notional == pytest.approx(3_000.0)
    assert intent.target_w == 0.0


def test_buys_scale_down_when_cash_would_go_negative() -> None:
    # Fully invested in A (cash 0). Targets over-allocate (sum 1.5) so buys must
    # be scaled to what selling A frees. Sell A .5 -> $5000; buys want $10000.
    plan = plan_rebalance(
        {"A": 0.5, "B": 0.5, "C": 0.5},
        equity=10_000.0,
        positions=[_pos("A", 10_000.0)],
    )
    assert plan.buy_scale == pytest.approx(0.5)
    buys = [i for i in plan.intents if i.side == "buy"]
    assert all(i.notional == pytest.approx(2_500.0) for i in buys)
    # Buys never exceed cash + sell proceeds (no negative cash).
    total_buy = sum(i.notional for i in buys)
    total_sell = sum(i.notional for i in plan.intents if i.side == "sell")
    assert total_buy <= plan.cash + total_sell + 1e-9


def test_zero_diff_yields_empty_plan() -> None:
    plan = plan_rebalance(
        {"A": 0.6, "B": 0.4},
        equity=10_000.0,
        positions=[_pos("A", 6_000.0), _pos("B", 4_000.0)],
    )
    assert plan.intents == []
    assert plan.skipped == []
    assert plan.buy_scale == 1.0


def test_positive_equity_required() -> None:
    with pytest.raises(ValueError):
        plan_rebalance({"A": 1.0}, equity=0.0, positions=[])
