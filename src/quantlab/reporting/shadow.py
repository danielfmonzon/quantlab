"""Shadow returns: the daily returns a paper account SHOULD have earned.

The shadow reconstructs the runner's converge-to-target policy as a daily return
series so the weekly review can compare paper equity against expectation. It
mirrors ``paper/runner`` semantics exactly:

* target = ``current_target_weights`` (the signal from the most recent WARMED
  month-end <= the observation session);
* one-session converge (a target observed through session t takes effect at t+1);
* a 1% drift band (``min_trade_frac`` in the runner): a symbol is only re-traded
  when |target_w - drifted_w| > 1%, otherwise it is left to drift;
* adj_close returns and the 5 bps one-way turnover cost model (same as the
  backtest engine).

KNOWN COMPARISON CAVEATS (paper WILL drift from shadow for structural reasons —
the tracker must annotate, not alarm):

  (a) Timing of the equity mark. Paper equity snapshots are taken at ~10:00 ET
      (when the scheduled run fires); the shadow is close-to-close. A single
      day's paper-vs-shadow delta of tens of bps is therefore expected and
      structural, not a bug.
  (b) Entry-day fill price. Paper orders fill at ~10:00 ET while the shadow uses
      that session's close, so the entry day carries extra idiosyncratic noise
      in whichever direction the market moved intraday.
  (c) Dividends. Alpaca paper does NOT credit cash dividends, whereas adj_close
      returns are dividend-adjusted (they include them). Over long windows paper
      will therefore LAG shadow by roughly the portfolio's dividend yield. This
      is expected drift; the weekly review annotates it as dividend drag rather
      than treating it as tracking error.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from quantlab.backtest.panel import build_price_panel
from quantlab.backtest.strategy import Strategy
from quantlab.data.store import ParquetStore
from quantlab.paper.runner import current_target_weights, make_paper_strategy

_DRIFT_BAND = 0.01  # matches the runner's min_trade_frac (1%)
_DEFAULT_COST_BPS = 5.0


def shadow_target_path(strategy: Strategy, panel: pd.DataFrame) -> dict[date, dict[str, float]]:
    """Per-session target weights the runner would pursue on each session.

    For every session ``d`` this is exactly ``current_target_weights`` evaluated on
    the prices observed through ``d`` (the signal from the most recent WARMED
    month-end <= ``d``, where — as in the runner — the current partial month's last
    session counts as a month-end). Computing it via ``current_target_weights`` per
    prefix guarantees the shadow mirrors the runner; the mirror-semantics unit test
    guards this equivalence against future drift.
    """
    out: dict[date, dict[str, float]] = {}
    for d in panel.index:
        weights, _ = current_target_weights(strategy, panel.loc[:d])
        out[d.date()] = weights
    return out


def _weights_vector(weights: dict[str, float], sym_index: dict[str, int], m: int) -> np.ndarray:
    vec = np.zeros(m, dtype=float)
    for sym, w in weights.items():
        idx = sym_index.get(sym)
        if idx is not None:
            vec[idx] = float(w)
    return vec


def shadow_returns(
    strategy_name: str,
    store: ParquetStore,
    start_date: date,
    end_date: date,
    *,
    cost_bps: float = _DEFAULT_COST_BPS,
) -> pd.Series:
    """Daily return series the paper account should have earned over [start, end].

    Deterministic. Uses the full stored history to warm signals, but only returns
    the sessions within ``[start_date, end_date]``.
    """
    strategy = make_paper_strategy(strategy_name)
    panel = build_price_panel(store, strategy.all_symbols)
    usable = panel[strategy.required_symbols].dropna()
    if usable.empty:
        return pd.Series(dtype="float64", name=f"shadow_{strategy_name}")
    panel = panel.loc[usable.index.min():]

    symbols = list(panel.columns)
    dates = list(panel.index)
    m = len(symbols)
    sym_index = {s: i for i, s in enumerate(symbols)}
    ret_vals = panel.pct_change(fill_method=None).to_numpy(dtype=float)

    target_path = shadow_target_path(strategy, panel)
    target_vecs = {
        d: _weights_vector(w, sym_index, m) for d, w in target_path.items()
    }

    rate = cost_bps / 1e4
    w_prev = np.zeros(m, dtype=float)  # start in cash
    e_prev = 1.0
    out_dates: list[pd.Timestamp] = []
    out_returns: list[float] = []

    for k in range(1, len(dates)):
        r_t = np.nan_to_num(ret_vals[k], nan=0.0)  # pre-inception NaNs carry 0 weight
        held = w_prev != 0.0
        contrib = np.where(held, w_prev * r_t, 0.0)
        growth = 1.0 + contrib.sum()
        e_drift = e_prev * growth
        drifted_val = np.where(held, w_prev * (1.0 + r_t), 0.0)
        w_drift = drifted_val / growth if growth != 0.0 else drifted_val

        # One-session converge: the target observed through k-1 takes effect at k.
        target = target_vecs[dates[k - 1].date()]
        # 1% drift band: only re-trade symbols whose gap exceeds the band.
        w_eff = np.where(np.abs(target - w_drift) > _DRIFT_BAND, target, w_drift)

        turnover = float(np.abs(w_eff - w_drift).sum())
        cost = rate * turnover
        e_t = e_drift * (1.0 - cost)

        out_dates.append(dates[k])
        out_returns.append(e_t / e_prev - 1.0)

        w_prev = w_eff / (1.0 - cost) if cost > 0.0 else w_eff
        e_prev = e_t

    series = pd.Series(out_returns, index=pd.DatetimeIndex(out_dates),
                       name=f"shadow_{strategy_name}")
    mask = (series.index >= pd.Timestamp(start_date)) & (series.index <= pd.Timestamp(end_date))
    return series[mask]


__all__ = ["shadow_returns", "shadow_target_path"]
