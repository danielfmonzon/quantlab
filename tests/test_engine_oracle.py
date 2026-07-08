"""Engine-vs-oracle equivalence — the correctness core of Batch 4."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.strategy import BuyAndHold, FixedWeights, Strategy
from quantlab.data import DataError
from tests.oracle import run_backtest_oracle

RTOL = 1e-9


def _prices(returns: np.ndarray, p0: float) -> np.ndarray:
    px = np.empty(len(returns) + 1, dtype=float)
    px[0] = p0
    px[1:] = p0 * np.cumprod(1.0 + returns)
    return px


def _two_asset_panel() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2020-01-02", periods=30)
    a = _prices(rng.normal(0.0006, 0.012, len(dates) - 1), 100.0)
    b = _prices(rng.normal(0.0002, 0.008, len(dates) - 1), 50.0)
    return pd.DataFrame({"A": a, "B": b}, index=dates)


def _three_asset_late_inception_panel() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2020-01-02", periods=90)
    a = _prices(rng.normal(0.0005, 0.011, len(dates) - 1), 100.0)
    b = _prices(rng.normal(0.0003, 0.006, len(dates) - 1), 80.0)
    # C is born on day 40 (leading NaNs before that).
    c = np.full(len(dates), np.nan)
    born = 40
    c[born:] = _prices(rng.normal(0.0004, 0.02, len(dates) - born - 1), 25.0)
    return pd.DataFrame({"A": a, "B": b, "C": c}, index=dates)


@pytest.mark.parametrize("cost_bps", [0.0, 25.0])
def test_buyhold_matches_oracle(cost_bps: float) -> None:
    panel = _two_asset_panel()
    strat = BuyAndHold("A")
    engine = run_backtest(panel, strat, cost_bps=cost_bps, initial_capital=100_000.0)
    oracle = run_backtest_oracle(panel, strat, cost_bps, initial_capital=100_000.0)
    np.testing.assert_allclose(engine.equity.to_numpy(), oracle.to_numpy(), rtol=RTOL)


@pytest.mark.parametrize("cost_bps", [0.0, 25.0])
def test_sixty40_matches_oracle_with_late_inception(cost_bps: float) -> None:
    panel = _three_asset_late_inception_panel()
    strat = FixedWeights({"A": 0.6, "B": 0.4}, name="sixty40")
    engine = run_backtest(panel, strat, cost_bps=cost_bps, initial_capital=100_000.0)
    oracle = run_backtest_oracle(panel, strat, cost_bps, initial_capital=100_000.0)
    np.testing.assert_allclose(engine.equity.to_numpy(), oracle.to_numpy(), rtol=RTOL)


def test_costs_strictly_reduce_equity_when_trading() -> None:
    panel = _three_asset_late_inception_panel()
    strat = FixedWeights({"A": 0.6, "B": 0.4}, name="sixty40")
    free = run_backtest(panel, strat, cost_bps=0.0)
    costly = run_backtest(panel, strat, cost_bps=25.0)
    assert costly.turnover.sum() > 1.0  # trades on many month ends
    assert costly.equity.iloc[-1] < free.equity.iloc[-1]


def test_drift_moves_weights_off_target() -> None:
    panel = _three_asset_late_inception_panel()
    strat = FixedWeights({"A": 0.6, "B": 0.4}, name="sixty40")
    result = run_backtest(panel, strat, cost_bps=0.0)
    # Find a non-trading (drift-only) day after the first investment.
    zero_turn = result.turnover[result.turnover == 0.0].index
    drift_day = zero_turn[5]
    w_a = result.weights_history.at[drift_day, "A"]
    assert abs(w_a - 0.6) > 1e-6  # unequal A/B moves pulled the weight off target
    assert result.weights_history.at[drift_day, "C"] == 0.0  # late asset stays 0


def test_no_lookahead_window_is_sliced() -> None:
    panel = _two_asset_panel()
    seen: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    class PeekStrategy(Strategy):
        @property
        def name(self) -> str:
            return "peek"

        def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
            return list(dates[:-1])  # try to rebalance every day

        def target_weights(self, window: pd.DataFrame, current_date: pd.Timestamp):
            # The engine must only ever hand us rows through current_date.
            seen.append((window.index.max(), current_date))
            assert window.index.max() <= current_date
            return {"A": 1.0}

    run_backtest(panel, PeekStrategy(), cost_bps=0.0)
    assert seen  # strategy was actually consulted
    assert all(mx <= cur for mx, cur in seen)


def test_empty_panel_raises() -> None:
    with pytest.raises(DataError, match="empty panel"):
        run_backtest(pd.DataFrame(), BuyAndHold("A"))


def test_out_of_bounds_weight_raises() -> None:
    panel = _two_asset_panel()

    class BadStrategy(Strategy):
        @property
        def name(self) -> str:
            return "bad"

        def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
            return [dates[0]]

        def target_weights(self, window: pd.DataFrame, current_date: pd.Timestamp):
            return {"A": 1.5}  # out of [0, 1]

    with pytest.raises(DataError, match="out of bounds"):
        run_backtest(panel, BadStrategy())


def test_weight_sum_over_one_raises() -> None:
    panel = _two_asset_panel()

    class OverStrategy(Strategy):
        @property
        def name(self) -> str:
            return "over"

        def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
            return [dates[0]]

        def target_weights(self, window: pd.DataFrame, current_date: pd.Timestamp):
            return {"A": 0.6, "B": 0.6}  # sums to 1.2

    with pytest.raises(DataError, match="sum"):
        run_backtest(panel, OverStrategy())


def test_nonzero_weight_on_nan_price_raises() -> None:
    panel = _three_asset_late_inception_panel()

    class HoldCEarly(Strategy):
        @property
        def name(self) -> str:
            return "hold_c_early"

        def rebalance_dates(self, dates: list[pd.Timestamp]) -> list[pd.Timestamp]:
            return [dates[0]]  # effective on dates[1], where C is still NaN

        def target_weights(self, window: pd.DataFrame, current_date: pd.Timestamp):
            return {"C": 1.0}

    with pytest.raises(DataError, match="NaN price"):
        run_backtest(panel, HoldCEarly())
