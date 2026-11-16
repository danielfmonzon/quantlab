"""Full exits are sized in quantity, not dollars (2026-11-16 ruling, PROP-20).

From 2026-11-12, crypto_trend aborted at submit every night with HTTP 403 "insufficient
balance for BTC (requested: 1.318638299, available: 1.290730834)". The exit had been
sent as the position's dollar value, and the broker converted it to BTC at a price about
2.2% below the one it valued the position at. These tests pin the replacement: a full
exit sells exactly ``Position.qty``, and every other order keeps the notional path.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from quantlab.broker.alpaca_trading import OrderInfo, Position
from quantlab.paper.rebalance import plan_rebalance
from quantlab.paper.runner import _submit_plan
from tests.test_paper_runner import FakeStore, _account, _frame, _run
from tests.test_trading_client import FakeResponse, FakeSession, _client

HELD_BTC = 1.290730834            # the 'available' figure in every 403, 11-12..11-15
BTC_MARK = 77_500.0
DAY = date(2026, 11, 16)


def _btc(qty: float = HELD_BTC, mark: float = BTC_MARK) -> Position:
    return Position(symbol="BTC-USD", qty=qty, market_value=qty * mark,
                    avg_entry_price=70_000.0)


def _broker() -> MagicMock:
    broker = MagicMock()
    broker.submit_order.side_effect = lambda symbol, side, notional, coid, qty=None: (
        OrderInfo(id=f"oid-{symbol}-{side}", client_order_id=coid, symbol=symbol,
                  side=side, notional=notional, status="accepted", submitted_at=None)
    )
    broker.get_orders.return_value = []
    return broker


def _submit(broker: MagicMock, plan) -> list[OrderInfo]:
    return _submit_plan(broker, "crypto_trend", plan, DAY, poll_timeout=0.0,
                        poll_interval=0.0, sleep_fn=lambda _s: None,
                        monotonic_fn=lambda: 0.0)


# --------------------------------------------------------------------------- #
# (a) the 2026-11-12 case                                                     #
# --------------------------------------------------------------------------- #

def test_a_crypto_full_exit_sells_exactly_the_held_quantity() -> None:
    """Held 1.290730834 BTC, target 0 -> one qty order for exactly 1.290730834."""
    pos = _btc()
    plan = plan_rebalance({}, equity=pos.market_value + 500.0, positions=[pos])

    assert len(plan.intents) == 1
    intent = plan.intents[0]
    assert intent.side == "sell" and intent.qty == HELD_BTC

    broker = _broker()
    orders = _submit(broker, plan)
    call = broker.submit_order.call_args
    assert call.args == ("BTC-USD", "sell", None, "ql-crypto_trend-20261116-BTC-USD-sell")
    assert call.kwargs == {"qty": HELD_BTC}
    # The recorded order keeps the plan's dollar figure for attribution and the ledger.
    assert orders[0].notional == pytest.approx(pos.market_value)


def test_a_the_wire_body_carries_the_held_quantity_and_no_notional() -> None:
    """At the broker: the POST body says qty "1.290730834", not a dollar amount."""
    session = FakeSession([FakeResponse(200, {
        "id": "o1", "client_order_id": "ql-x", "symbol": "BTC/USD", "side": "sell",
        "notional": None, "status": "accepted", "submitted_at": None,
    })])
    _client(session).submit_order("BTC-USD", "sell", None, "ql-x", qty=HELD_BTC)
    body = session.calls[0]["json"]
    assert body["qty"] == "1.290730834"
    assert "notional" not in body
    assert body["symbol"] == "BTC/USD" and body["time_in_force"] == "gtc"


# --------------------------------------------------------------------------- #
# (b) a remainder below min_trade_frac is a full exit                         #
# --------------------------------------------------------------------------- #

def test_b_a_sell_leaving_less_than_min_trade_frac_is_a_full_qty_exit() -> None:
    pos = Position(symbol="A", qty=12.5, market_value=5_000.0, avg_entry_price=1.0)
    plan = plan_rebalance({"A": 0.005}, equity=10_000.0, positions=[pos],
                          min_trade_frac=0.01)
    (intent,) = plan.intents
    assert intent.side == "sell"
    assert intent.qty == 12.5
    assert intent.notional == pytest.approx(5_000.0)    # the whole position, not 4,950
    assert plan.est_turnover == pytest.approx(0.5)


def test_b_a_remainder_exactly_at_min_trade_frac_stays_partial() -> None:
    """The boundary is the existing one: 'below' the threshold, not 'at'."""
    pos = Position(symbol="A", qty=12.5, market_value=5_000.0, avg_entry_price=1.0)
    plan = plan_rebalance({"A": 0.01}, equity=10_000.0, positions=[pos],
                          min_trade_frac=0.01)
    (intent,) = plan.intents
    assert intent.qty is None
    assert intent.notional == pytest.approx(4_900.0)


# --------------------------------------------------------------------------- #
# (c) an ordinary partial sell is unchanged                                   #
# --------------------------------------------------------------------------- #

def test_c_a_normal_partial_sell_stays_on_the_notional_path() -> None:
    pos = Position(symbol="A", qty=12.5, market_value=5_000.0, avg_entry_price=1.0)
    plan = plan_rebalance({"A": 0.2}, equity=10_000.0, positions=[pos])
    (intent,) = plan.intents
    assert intent.qty is None
    assert intent.notional == pytest.approx(3_000.0)

    broker = _broker()
    _submit(broker, plan)
    call = broker.submit_order.call_args
    assert call.args == ("A", "sell", pytest.approx(3_000.0), "ql-crypto_trend-20261116-A-sell")
    assert call.kwargs == {}                             # exactly the pre-ruling call


# --------------------------------------------------------------------------- #
# (d) the equity trend account takes the same path                            #
# --------------------------------------------------------------------------- #

def test_d_equity_trend_full_exit_sells_the_exact_fractional_spy_quantity(tmp_path) -> None:
    """trend below its SMA rotates SPY -> IEF. The SPY exit is by quantity, the IEF buy
    by notional, through the real runner."""
    dates = pd.bdate_range("2023-01-02", periods=300)
    falling = 100.0 * (0.9995 ** np.arange(300))
    store = FakeStore({"SPY": _frame(dates, falling), "IEF": _frame(dates, np.full(300, 100.0))})
    spy_qty = 123.456789012
    broker = _broker()
    broker.get_account.return_value = _account(equity=100_000.0, cash=0.0)
    broker.get_positions.return_value = [
        Position(symbol="SPY", qty=spy_qty, market_value=100_000.0, avg_entry_price=700.0)
    ]

    report = _run("trend", False, broker, store, tmp_path)

    assert not report.aborted, report.abort_reason
    calls = {c.args[0]: c for c in broker.submit_order.call_args_list}
    assert calls["SPY"].args[1:3] == ("sell", None)
    assert calls["SPY"].kwargs == {"qty": spy_qty}
    assert calls["IEF"].args[1] == "buy" and calls["IEF"].kwargs == {}
    assert calls["IEF"].args[2] == pytest.approx(100_000.0)


# --------------------------------------------------------------------------- #
# (e) duplicate-order recovery on a qty order                                 #
# --------------------------------------------------------------------------- #

def test_e_duplicate_client_order_id_recovery_works_on_a_qty_order() -> None:
    existing = {
        "id": "order-btc", "client_order_id": "ql-crypto_trend-20261116-BTC-USD-sell",
        "symbol": "BTC/USD", "side": "sell", "notional": None, "status": "filled",
        "submitted_at": "2026-11-17T01:30:05Z",
    }
    session = FakeSession([
        FakeResponse(422, {"message": "client_order_id must be unique"}),
        FakeResponse(200, [existing]),
    ])
    order = _client(session).submit_order(
        "BTC-USD", "sell", None, existing["client_order_id"], qty=HELD_BTC,
    )
    assert order.was_duplicate is True
    assert order.id == "order-btc"
    assert session.calls[0]["method"] == "POST"
    assert session.calls[0]["json"]["qty"] == "1.290730834"
    assert session.calls[1]["method"] == "GET"


# --------------------------------------------------------------------------- #
# The broker contract                                                         #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("notional, qty", [(None, None), (500.0, 1.0)])
def test_submit_order_takes_exactly_one_of_notional_or_qty(notional, qty) -> None:
    session = FakeSession([])
    with pytest.raises(ValueError, match="exactly one"):
        _client(session).submit_order("SPY", "sell", notional, "ql-x", qty=qty)
    assert session.calls == []                      # nothing reached the broker


@pytest.mark.parametrize("qty", [0.0, -1.0, float("nan"), float("inf")])
def test_submit_order_rejects_a_non_positive_or_non_finite_qty(qty) -> None:
    session = FakeSession([])
    with pytest.raises(ValueError, match="positive and finite"):
        _client(session).submit_order("SPY", "sell", None, "ql-x", qty=qty)
    assert session.calls == []


def test_a_tiny_qty_is_sent_in_plain_notation() -> None:
    session = FakeSession([FakeResponse(200, {"id": "o", "status": "accepted"})])
    _client(session).submit_order("BTC-USD", "sell", None, "ql-x", qty=0.00001)
    assert session.calls[0]["json"]["qty"] == "0.00001"
