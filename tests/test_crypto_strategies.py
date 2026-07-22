"""Tests for the crypto research strategies (CryptoTrendBTC, CryptoVolTargetBTC)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.strategies import CryptoTrendBTC, CryptoVolTargetBTC

_BTC = "BTC-USD"


def _monthly(values: dict[str, list[float]]) -> pd.DataFrame:
    """Panel indexed by month-end (one row per month), like the equity tests."""
    m = len(next(iter(values.values())))
    idx = pd.date_range("2020-01-31", periods=m, freq="ME")
    return pd.DataFrame(values, index=idx)


def _prices_from_returns(returns: Sequence[float], p0: float = 100.0) -> list[float]:
    px = [p0]
    for r in returns:
        px.append(px[-1] * (1.0 + r))
    return px


def _daily_btc(returns: Sequence[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=len(returns) + 1)
    return pd.DataFrame({_BTC: _prices_from_returns(returns)}, index=idx)


def _last(panel: pd.DataFrame) -> pd.Timestamp:
    return panel.index[-1]


# -- Annualization metadata -------------------------------------------------


def test_crypto_strategies_declare_365() -> None:
    assert CryptoTrendBTC().periods_per_year == 365
    assert CryptoVolTargetBTC().periods_per_year == 365


# -- CryptoTrendBTC ---------------------------------------------------------


def test_crypto_trend_uptrend_goes_risk_on() -> None:
    # 11 rising month-ends: last close (200) > SMA of the last 10 (155) -> BTC.
    panel = _monthly({_BTC: [100 + 10 * i for i in range(11)]})
    w = CryptoTrendBTC().target_weights(panel, _last(panel))
    assert w == {_BTC: 1.0}


def test_crypto_trend_below_sma_goes_cash_not_safe_asset() -> None:
    # Rising 10 months then a crash below the SMA on the current month-end.
    prices = [100 + 10 * i for i in range(10)] + [50.0]  # ..., 190, then 50
    panel = _monthly({_BTC: prices})
    w = CryptoTrendBTC().target_weights(panel, _last(panel))
    assert w == {}  # 50 < SMA -> 100% CASH (no safe-asset substitute)


def test_crypto_trend_warmup_is_cash() -> None:
    panel = _monthly({_BTC: [100.0, 110.0, 120.0]})  # <10 month-ends
    strat = CryptoTrendBTC()
    assert strat.is_warmed_up(panel, _last(panel)) is False
    assert strat.target_weights(panel, _last(panel)) == {}


def test_crypto_trend_warmed_up_at_ten_month_ends() -> None:
    panel = _monthly({_BTC: [100.0 + i for i in range(10)]})  # exactly 10 month-ends
    assert CryptoTrendBTC().is_warmed_up(panel, _last(panel)) is True


# -- CryptoVolTargetBTC -----------------------------------------------------


def test_crypto_voltarget_low_vol_caps_at_one() -> None:
    panel = _daily_btc([0.001, -0.001] * 10)  # 20 returns, tiny vol
    w = CryptoVolTargetBTC().target_weights(panel, _last(panel))
    assert w == {_BTC: 1.0}  # target/realized >> 1 -> capped at max_weight


def test_crypto_voltarget_high_vol_scales_down_with_365_annualization() -> None:
    returns = np.array([0.05, -0.05] * 10)  # 20 returns, high vol
    panel = _daily_btc(returns.tolist())
    w = CryptoVolTargetBTC().target_weights(panel, _last(panel))
    # Realized vol MUST annualize on 365 (not 252); target vol is 0.20.
    realized = float(np.std(returns, ddof=1) * np.sqrt(365))
    expected = min(1.0, 0.20 / realized)
    assert expected < 1.0
    assert w[_BTC] == pytest.approx(expected, rel=1e-12)


def test_crypto_voltarget_uses_365_not_252() -> None:
    returns = np.array([0.05, -0.05] * 10)
    panel = _daily_btc(returns.tolist())
    w = CryptoVolTargetBTC().target_weights(panel, _last(panel))
    wrong_252 = min(1.0, 0.20 / float(np.std(returns, ddof=1) * np.sqrt(252)))
    # The 365 weight is strictly smaller than the (wrong) 252 weight would be.
    assert w[_BTC] < wrong_252


def test_crypto_voltarget_zero_vol_is_cash_no_inf() -> None:
    panel = _daily_btc([0.0] * 20)  # constant price -> zero realized vol
    w = CryptoVolTargetBTC().target_weights(panel, _last(panel))
    assert w == {}


def test_crypto_voltarget_warmup_is_cash() -> None:
    panel = _daily_btc([0.001] * 10)  # only 11 prices (<21) -> warmup
    strat = CryptoVolTargetBTC()
    assert strat.is_warmed_up(panel, _last(panel)) is False
    assert strat.target_weights(panel, _last(panel)) == {}
