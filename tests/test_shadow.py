"""Shadow-returns tests: mirror semantics, cost impact, determinism (no network)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.panel import build_price_panel
from quantlab.paper.runner import current_target_weights, make_paper_strategy
from quantlab.reporting.shadow import shadow_returns, shadow_target_path


def _frame(dates: pd.DatetimeIndex, prices: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "adj_close": prices})


class FakeStore:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def load(self, symbol: str, start: object = None, end: object = None) -> pd.DataFrame:
        return self._frames.get(symbol, _frame(pd.DatetimeIndex([]), np.array([])))

    def load_metadata(self, symbol: str) -> None:
        return None


def _trend_store(periods: int = 300) -> FakeStore:
    # SPY steadily rising (risk-on once warmed); IEF flat safe asset.
    dates = pd.bdate_range("2023-01-02", periods=periods)
    spy = 100.0 * (1.0004 ** np.arange(periods))
    ief = np.full(periods, 100.0)
    return FakeStore({"SPY": _frame(dates, spy), "IEF": _frame(dates, ief)})


def _panel(store: FakeStore):
    strat = make_paper_strategy("trend")
    panel = build_price_panel(store, strat.all_symbols)
    usable = panel[strat.required_symbols].dropna()
    return strat, panel.loc[usable.index.min():]


def test_target_path_mirrors_current_target_weights_each_session() -> None:
    store = _trend_store()
    strat, panel = _panel(store)

    path = shadow_target_path(strat, panel)
    # The path must equal current_target_weights on each session's price slice.
    for d in panel.index:
        expected, _ = current_target_weights(strat, panel.loc[:d])
        assert path[d.date()] == expected

    # Sanity: the path is non-trivial -- cash during warmup, SPY once warmed.
    assert any(w == {} for w in path.values())
    assert any(w == {"SPY": 1.0} for w in path.values())


def test_costs_reduce_returns_on_converge_days() -> None:
    store = _trend_store()
    start, end = date(2023, 1, 1), date(2024, 3, 1)

    free = shadow_returns("trend", store, start, end, cost_bps=0.0)
    costly = shadow_returns("trend", store, start, end, cost_bps=50.0)

    assert not free.empty and not costly.empty
    assert list(free.index) == list(costly.index)

    # Up to the first converge day both series are identical (all cash). The two
    # first differ ON the converge day, and there the cost model subtracts exactly
    # rate * turnover from that session's return. The full cash -> SPY converge is
    # a turnover of 1.0, so the drag is exactly 50 bps.
    diff = ~np.isclose(free.to_numpy(), costly.to_numpy())
    first = int(np.argmax(diff))
    assert diff.any()
    assert costly.iloc[first] < free.iloc[first]
    assert free.iloc[first] == pytest.approx(0.0)  # converging out of cash: no drift
    assert costly.iloc[first] == pytest.approx(-50e-4)  # rate(50bps) * turnover(1.0)


def test_pre_warmup_returns_are_cash() -> None:
    store = _trend_store()
    # A window entirely inside the 10-month warmup: shadow holds cash (0 return).
    early = shadow_returns("trend", store, date(2023, 1, 1), date(2023, 6, 1))
    assert not early.empty
    assert np.allclose(early.to_numpy(), 0.0)


def test_shadow_returns_is_deterministic() -> None:
    store = _trend_store()
    start, end = date(2023, 1, 1), date(2024, 3, 1)
    a = shadow_returns("trend", store, start, end)
    b = shadow_returns("trend", store, start, end)
    pd.testing.assert_series_equal(a, b)


def test_window_restricts_to_requested_span() -> None:
    store = _trend_store()
    full = shadow_returns("trend", store, date(2023, 1, 1), date(2024, 3, 1))
    sub = shadow_returns("trend", store, date(2023, 12, 1), date(2024, 3, 1))
    assert sub.index.min() >= pd.Timestamp("2023-12-01")
    assert sub.index.max() <= pd.Timestamp("2024-03-01")
    # The sub-window equals the tail of the full series over the same dates.
    overlap = full[full.index >= pd.Timestamp("2023-12-01")]
    pd.testing.assert_series_equal(sub, overlap)
