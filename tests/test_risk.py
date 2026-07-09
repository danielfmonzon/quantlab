"""Phase 4 risk engine: limits, weight containment, portfolio/data decisions,
kill-switch state persistence, and backtest integration (Batch 6).

The regression guard here is load-bearing: with ``risk_engine=None`` the backtest
must reproduce the pre-risk (Batch 5) equity path to 1e-12.
"""

from __future__ import annotations

import argparse
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from quantlab.backtest.engine import run_backtest
from quantlab.backtest.metrics import drawdown_windows
from quantlab.backtest.strategy import BuyAndHold
from quantlab.data.health import HealthReport, SymbolHealth
from quantlab.risk.engine import (
    ALLOW,
    FREEZE_STALE_DATA,
    HALT_DAILY_LOSS,
    HALT_WEEKLY_LOSS,
    KILL_DRAWDOWN,
    RiskEngine,
)
from quantlab.risk.limits import RiskLimits, load_risk_limits
from quantlab.risk.state import (
    RiskState,
    load_risk_state,
    reset_risk_state,
    save_risk_state,
)

RTOL = 1e-12


# --------------------------------------------------------------------------- #
# RiskLimits: defaults, YAML round-trip, validation                           #
# --------------------------------------------------------------------------- #

def test_default_limits_match_spec() -> None:
    lim = RiskLimits()
    assert lim.max_position_weight == 1.00
    assert lim.max_gross_exposure == 1.00
    assert lim.max_daily_loss == 0.03
    assert lim.max_weekly_loss == 0.08
    assert lim.max_drawdown_kill == 0.25
    assert lim.staleness_max_sessions == 1


def test_config_risk_yaml_loads_and_round_trips(tmp_path) -> None:
    import yaml

    original = RiskLimits(max_daily_loss=0.02, max_weekly_loss=0.06, max_drawdown_kill=0.20)
    path = tmp_path / "risk.yaml"
    path.write_text(yaml.safe_dump(original.model_dump()), encoding="utf-8")
    loaded = load_risk_limits(path)
    assert loaded == original


def test_load_limits_missing_file_returns_defaults(tmp_path) -> None:
    assert load_risk_limits(tmp_path / "nope.yaml") == RiskLimits()


def test_shipped_config_risk_yaml_is_valid() -> None:
    # The real config/risk.yaml must parse and satisfy every constraint.
    assert load_risk_limits() == RiskLimits()


def test_validation_rejects_daily_ge_weekly() -> None:
    with pytest.raises(ValueError, match="max_daily_loss < max_weekly_loss"):
        RiskLimits(max_daily_loss=0.08, max_weekly_loss=0.08)


def test_validation_rejects_weekly_ge_kill() -> None:
    with pytest.raises(ValueError, match="max_weekly_loss < max_drawdown_kill"):
        RiskLimits(max_weekly_loss=0.25, max_drawdown_kill=0.25)


@pytest.mark.parametrize("field", [
    "max_position_weight", "max_gross_exposure", "max_daily_loss",
    "max_weekly_loss", "max_drawdown_kill",
])
def test_validation_rejects_out_of_unit_interval(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        RiskLimits(**{field: 1.5})


@pytest.mark.parametrize("field", [
    "max_position_weight", "max_daily_loss", "max_drawdown_kill",
])
def test_validation_rejects_nonpositive(field: str) -> None:
    with pytest.raises(ValueError):
        RiskLimits(**{field: 0.0})


def test_validation_rejects_negative_staleness() -> None:
    with pytest.raises(ValueError, match="staleness_max_sessions"):
        RiskLimits(staleness_max_sessions=-1)


# --------------------------------------------------------------------------- #
# check_weights: clamp, rescale, no-op                                        #
# --------------------------------------------------------------------------- #

def test_check_weights_clamps_per_symbol() -> None:
    eng = RiskEngine(RiskLimits(max_position_weight=0.5))
    dec = eng.check_weights({"A": 0.8, "B": 0.1})
    assert dec.adjusted_weights["A"] == 0.5
    assert dec.adjusted_weights["B"] == 0.1
    assert any("clamp A" in a for a in dec.adjustments)


def test_check_weights_rescales_gross() -> None:
    eng = RiskEngine(RiskLimits())  # gross cap 1.0
    dec = eng.check_weights({"A": 0.7, "B": 0.7})
    assert dec.adjusted_weights["A"] == pytest.approx(0.5)
    assert dec.adjusted_weights["B"] == pytest.approx(0.5)
    assert sum(dec.adjusted_weights.values()) == pytest.approx(1.0)
    assert any("rescale gross" in a for a in dec.adjustments)


def test_check_weights_noop_records_nothing() -> None:
    eng = RiskEngine(RiskLimits())
    dec = eng.check_weights({"A": 0.5, "B": 0.3})
    assert dec.adjusted_weights == {"A": 0.5, "B": 0.3}
    assert dec.adjustments == []


def test_check_weights_never_raises_on_empty() -> None:
    eng = RiskEngine(RiskLimits())
    dec = eng.check_weights({})
    assert dec.adjusted_weights == {}
    assert dec.adjustments == []


# --------------------------------------------------------------------------- #
# evaluate_portfolio: threshold boundaries (at != beyond), running peak        #
# --------------------------------------------------------------------------- #

def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


def test_daily_exactly_at_threshold_does_not_trigger() -> None:
    eq = _series([100.0, 97.0])
    # Derive the limit from the actual computed return so the boundary is EXACT
    # in float (97/100-1 is not exactly -0.03). Strict `<` must not fire at equality.
    daily = 97.0 / 100.0 - 1.0
    eng = RiskEngine(RiskLimits(max_daily_loss=-daily))
    dec = eng.evaluate_portfolio(eq, 1)
    assert dec.action == ALLOW
    assert dec.daily_return == pytest.approx(daily)


def test_daily_just_beyond_threshold_halts() -> None:
    eng = RiskEngine(RiskLimits())
    eq = _series([100.0, 96.9])  # daily = -0.031
    dec = eng.evaluate_portfolio(eq, 1)
    assert dec.action == HALT_DAILY_LOSS


def test_weekly_exactly_at_threshold_does_not_trigger() -> None:
    eng = RiskEngine(RiskLimits())
    f = 0.92 ** (1 / 5)  # spread the 8% over 5 days so no single day breaches
    eq = _series([100.0 * f**i for i in range(6)])  # weekly = -0.08 exactly
    dec = eng.evaluate_portfolio(eq, 5)
    assert dec.action == ALLOW
    assert dec.weekly_return == pytest.approx(-0.08)


def test_weekly_just_beyond_threshold_halts() -> None:
    eng = RiskEngine(RiskLimits())
    f = 0.92 ** (1 / 5)
    eq = _series([100.0 * f**i for i in range(5)] + [91.9])  # weekly = -0.081
    dec = eng.evaluate_portfolio(eq, 5)
    assert dec.action == HALT_WEEKLY_LOSS


def test_drawdown_exactly_at_threshold_does_not_kill() -> None:
    eng = RiskEngine(RiskLimits())
    eq = _series([100.0, 75.0])  # drawdown = -0.25 exactly (daily also -0.25)
    dec = eng.evaluate_portfolio(eq, 1)
    # At threshold neither KILL nor daily-HALT fires strictly for drawdown; daily
    # -0.25 IS beyond -0.03, so a daily halt is expected, but NOT a kill.
    assert dec.action != KILL_DRAWDOWN
    assert dec.action == HALT_DAILY_LOSS


def test_drawdown_just_beyond_threshold_kills() -> None:
    eng = RiskEngine(RiskLimits())
    eq = _series([100.0, 74.9])  # drawdown = -0.251
    dec = eng.evaluate_portfolio(eq, 1)
    assert dec.action == KILL_DRAWDOWN


def test_drawdown_uses_running_peak_not_global() -> None:
    eng = RiskEngine(RiskLimits())
    # A LATER session (300) is a higher peak, but when evaluating at t=2 only the
    # peak-so-far (200) is visible. drawdown must be 150/200-1 = -0.25, NOT the
    # 150/300-1 = -0.50 that a whole-series (global) peak would give.
    eq = _series([100.0, 200.0, 150.0, 300.0, 210.0])
    at_dip = eng.evaluate_portfolio(eq, 2)
    assert at_dip.drawdown == pytest.approx(150.0 / 200.0 - 1.0)  # running peak 200
    at_later = eng.evaluate_portfolio(eq, 4)
    assert at_later.drawdown == pytest.approx(210.0 / 300.0 - 1.0)  # peak advanced to 300


def test_kill_takes_precedence_over_daily_and_weekly() -> None:
    eng = RiskEngine(RiskLimits())
    eq = _series([100.0, 100.0, 100.0, 100.0, 100.0, 60.0])  # -40% day: all three fire
    dec = eng.evaluate_portfolio(eq, 5)
    assert dec.action == KILL_DRAWDOWN


# --------------------------------------------------------------------------- #
# evaluate_data / combine                                                      #
# --------------------------------------------------------------------------- #

def _health(symbols: list[SymbolHealth], blocking: list[str]) -> HealthReport:
    return HealthReport(
        generated_at=datetime(2024, 1, 2, 12, 0, 0),
        market_open=False,
        data_fresh=not (blocking or any(
            s.has_data and s.staleness_sessions > 1 for s in symbols
        )),
        symbols=symbols,
        blocking_reasons=blocking,
    )


def test_evaluate_data_allows_fresh() -> None:
    eng = RiskEngine(RiskLimits())
    report = _health([SymbolHealth(symbol="SPY", has_data=True, last_date=None,
                                   staleness_sessions=0)], [])
    assert eng.evaluate_data(report).action == ALLOW


def test_evaluate_data_freezes_on_stale() -> None:
    eng = RiskEngine(RiskLimits(staleness_max_sessions=1))
    report = _health([SymbolHealth(symbol="SPY", has_data=True, last_date=None,
                                   staleness_sessions=3)], [])
    dec = eng.evaluate_data(report)
    assert dec.action == FREEZE_STALE_DATA
    assert "SPY" in dec.reason


def test_combine_precedence() -> None:
    eng = RiskEngine(RiskLimits())
    kill = eng.evaluate_portfolio(_series([100.0, 74.9]), 1)
    freeze = eng.evaluate_data(_health(
        [SymbolHealth(symbol="SPY", has_data=True, last_date=None, staleness_sessions=5)], []
    ))
    assert eng.combine(kill, freeze).action == KILL_DRAWDOWN


# --------------------------------------------------------------------------- #
# RiskState: persistence, atomicity, manual-reset semantics                    #
# --------------------------------------------------------------------------- #

def test_state_persists_across_restart(tmp_path) -> None:
    path = tmp_path / "risk_state.json"
    state = RiskState(halted=True, reason="KILL_DRAWDOWN dd -0.30",
                      triggered_at=datetime(2024, 3, 13, 16, 0, 0),
                      requires_manual_reset=True)
    save_risk_state(state, path)
    # Simulate a fresh process: a brand-new load from the same path.
    assert load_risk_state(path) == state


def test_state_missing_file_is_not_halted(tmp_path) -> None:
    assert load_risk_state(tmp_path / "absent.json") == RiskState()


def test_state_write_is_atomic_and_leaves_no_tmp(tmp_path) -> None:
    path = tmp_path / "risk_state.json"
    save_risk_state(RiskState(halted=True, reason="x"), path)
    assert not path.with_name(path.name + ".tmp").exists()


def test_state_survives_garbage_tmp_from_crash(tmp_path) -> None:
    path = tmp_path / "risk_state.json"
    good = RiskState(halted=True, reason="KILL", requires_manual_reset=True)
    save_risk_state(good, path)
    # A prior process crashed mid-write, leaving a truncated temp file behind.
    path.with_name(path.name + ".tmp").write_text("{ this is not json", encoding="utf-8")
    # The live file is untouched, so the state still loads cleanly.
    assert load_risk_state(path) == good


def test_kill_requires_manual_reset_flag() -> None:
    kill = RiskState(halted=True, reason=KILL_DRAWDOWN, requires_manual_reset=True)
    halt = RiskState(halted=True, reason=HALT_DAILY_LOSS, requires_manual_reset=False)
    assert kill.requires_manual_reset is True
    assert halt.requires_manual_reset is False


def test_reset_clears_and_returns_prior(tmp_path) -> None:
    path = tmp_path / "risk_state.json"
    save_risk_state(RiskState(halted=True, reason="KILL", requires_manual_reset=True), path)
    cleared = reset_risk_state(path)
    assert cleared.halted is True and cleared.requires_manual_reset is True
    assert load_risk_state(path) == RiskState()  # now clean


# --------------------------------------------------------------------------- #
# Backtest integration + regression guard                                      #
# --------------------------------------------------------------------------- #

def _crash_panel() -> pd.DataFrame:
    # Rise to a peak (104 on day 4), crash -30% on day 5, then flatten.
    dates = pd.bdate_range("2020-01-02", periods=10)
    a = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 72.8, 73.0, 74.0, 75.0, 76.0])
    return pd.DataFrame({"A": a}, index=dates)


def test_none_risk_engine_is_byte_identical_regression_guard() -> None:
    panel = _crash_panel()
    strat = BuyAndHold("A")
    plain = run_backtest(panel, strat, cost_bps=5.0)
    none_explicit = run_backtest(panel, strat, cost_bps=5.0, risk_engine=None)
    np.testing.assert_allclose(
        none_explicit.equity.to_numpy(), plain.equity.to_numpy(), rtol=RTOL, atol=0.0
    )
    assert none_explicit.risk_events == []
    assert none_explicit.config["risk_overlay"] is False


def test_kill_forces_cash_session_after_breach_and_stays() -> None:
    panel = _crash_panel()
    strat = BuyAndHold("A")
    eng = RiskEngine(RiskLimits())
    result = run_backtest(panel, strat, cost_bps=5.0, risk_engine=eng)

    dates = list(panel.index)
    # Breach happens on day 5 (the -30% crash). The portfolio still HELD A that
    # day (it takes the loss); liquidation lands one session later, on day 6.
    assert result.weights_history.loc[dates[5], "A"] > 0.0  # still invested at breach
    for d in dates[6:]:
        assert result.weights_history.loc[d, "A"] == 0.0  # cash for the remainder (KILL stays)

    # Equity is flat from day 6 onward (fully in cash).
    eq = result.equity.to_numpy()
    np.testing.assert_allclose(eq[6:], eq[6], rtol=RTOL, atol=0.0)

    # A KILL event was recorded on the liquidation session.
    kills = [e for e in result.risk_events if e["action"] == KILL_DRAWDOWN]
    assert kills, "expected a KILL_DRAWDOWN risk event"
    assert kills[0]["date"] == dates[6].date().isoformat()
    assert kills[0]["weights_after"] == {}


def test_risk_overlay_changes_equity_vs_plain() -> None:
    panel = _crash_panel()
    strat = BuyAndHold("A")
    plain = run_backtest(panel, strat, cost_bps=5.0)
    risked = run_backtest(panel, strat, cost_bps=5.0, risk_engine=RiskEngine(RiskLimits()))
    # After liquidation the risked path avoids the post-crash drift, so the final
    # equity must differ from the always-invested plain path.
    assert risked.equity.iloc[-1] != pytest.approx(plain.equity.iloc[-1])


# --------------------------------------------------------------------------- #
# CLI: reset refuses without --confirm YES                                     #
# --------------------------------------------------------------------------- #

def test_cli_reset_refuses_without_confirm(capsys) -> None:
    from quantlab.cli import cmd_risk_reset

    rc = cmd_risk_reset(argparse.Namespace(confirm=None))
    assert rc == 2
    err = capsys.readouterr().err
    assert "--confirm YES" in err


def test_cli_reset_refuses_wrong_confirm(capsys) -> None:
    from quantlab.cli import cmd_risk_reset

    assert cmd_risk_reset(argparse.Namespace(confirm="yes")) == 2
    assert cmd_risk_reset(argparse.Namespace(confirm="Y")) == 2


def test_cli_reset_accepts_exact_confirm(monkeypatch) -> None:
    import quantlab.cli as cli

    called = {}

    def fake_reset() -> RiskState:
        called["hit"] = True
        return RiskState(halted=True, reason="KILL", requires_manual_reset=True)

    monkeypatch.setattr(cli, "reset_risk_state", fake_reset)
    rc = cli.cmd_risk_reset(argparse.Namespace(confirm="YES"))
    assert rc == 0
    assert called.get("hit") is True


# --------------------------------------------------------------------------- #
# Step 0 helper: drawdown_windows                                              #
# --------------------------------------------------------------------------- #

def test_drawdown_windows_finds_episodes_deepest_first() -> None:
    dates = pd.bdate_range("2020-01-02", periods=5)
    eq = pd.Series([100.0, 120.0, 90.0, 130.0, 110.0], index=dates)
    windows = drawdown_windows(eq, top_n=3)
    assert len(windows) == 2
    # Deepest first: 120 -> 90 is -25%; 130 -> 110 (ongoing) is -15.4%.
    assert windows[0].depth == pytest.approx(90.0 / 120.0 - 1.0)
    assert windows[0].peak_date == dates[1].date()
    assert windows[0].trough_date == dates[2].date()
    assert windows[0].recovery_date == dates[3].date()
    assert windows[1].depth == pytest.approx(110.0 / 130.0 - 1.0)
    assert windows[1].recovery_date is None  # still underwater at series end


def test_drawdown_windows_short_series_is_empty() -> None:
    assert drawdown_windows(pd.Series([100.0])) == []
