"""The narration hard rule, enforced.

A run narration may contain only tokens derivable from three declared sources:

1. the run report's own structured fields,
2. the account's pre-registered rule parameters, and
3. the run id being narrated (a caller-supplied identifier that makes no claim
   about the world).

Nothing else — no market commentary, no news, no invented reasoning. These tests
verify that mechanically rather than by reading the prose:

* ``test_every_number_in_the_narration_is_derivable`` extracts every numeric token
  from the narration and checks membership in an allowed set built INDEPENDENTLY
  here from the raw report JSON plus the declared rule constants. The transform
  list below is the whole contract; a narrator that invented a figure, or applied
  an undeclared transform, fails.
* the canary tests plant fields and values the templates do not reference and
  assert they never surface.
* ``test_rule_constants_match_the_live_strategy_objects`` grounds source (2) in
  code, so the "pre-registered parameters" cannot themselves be fiction.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from quantlab.backtest.strategies import (
    CryptoTrendBTC,
    CryptoVolTargetBTC,
    TrendSMA10,
    VolTarget,
)
from quantlab.glassbox.narrate import narrate_run, rule_constants

# A numeric token: optional sign, digits with optional thousands separators, optional
# decimals. Currency/percent symbols are stripped by the split, so "$7,897.07" and
# "8.15%" both yield their bare number.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _numbers_in(text: str) -> list[str]:
    return [m.group(0) for m in _NUMBER.finditer(text)]


def _normalise(token: str) -> str:
    """Strip thousands separators and any trailing zero padding for comparison."""
    cleaned = token.replace(",", "")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"


def _representations(value: float) -> set[str]:
    """Every rendering of ``value`` the narrator is DECLARED to be able to emit.

    This mirrors ``narrate._Facts``: raw, 4-decimal ratio, 2-decimal money,
    2-decimal percent, 0-decimal percent, and the plain integer form. Adding a
    formatter to the narrator without adding it here makes this test fail, which is
    the point — the transform list is part of the contract.
    """
    out = {
        _normalise(f"{value}"),
        _normalise(f"{value:.4f}"),
        _normalise(f"{value:,.2f}"),
        _normalise(f"{value * 100:.2f}"),
        _normalise(f"{value * 100:.0f}"),
    }
    if float(value).is_integer():
        out.add(_normalise(str(int(value))))
    return out


def _collect_values(node: Any, out: list[float]) -> None:
    """Every numeric leaf anywhere in the report, plus timestamp digit groups."""
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        out.append(float(node))
    elif isinstance(node, dict):
        for value in node.values():
            _collect_values(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_values(value, out)


def allowed_tokens(report: dict[str, Any], label: str, run_id: str) -> set[str]:
    """The complete set of numeric tokens a narration of ``report`` may contain.

    Three declared sources, and only three: the report's structured fields, the
    account's rule constants, and the ``run_id`` of the run being narrated (an
    identifier supplied by the caller, echoed as the narration's subject — it makes
    no claim about the world).
    """
    values: list[float] = []
    _collect_values(report, values)

    # Declared derivation: absolute weight drift per intent, and per skipped diff.
    plan = report.get("plan") or {}
    for intent in plan.get("intents") or []:
        cur, tgt = intent.get("current_w"), intent.get("target_w")
        if isinstance(cur, (int, float)) and isinstance(tgt, (int, float)):
            values.append(abs(float(tgt) - float(cur)))
    # Declared derivation: the count of passing stages.
    stages = report.get("stages") or []
    values.append(float(sum(1 for s in stages if isinstance(s, dict) and s.get("ok"))))
    # Source (2): the account's pre-registered rule parameters.
    values.extend(float(v) for v in rule_constants(label).values())

    allowed: set[str] = set()
    for value in values:
        allowed |= _representations(value)
    # Any digit group appearing verbatim in the raw JSON text (timestamps, ids, and
    # abort reasons are echoed verbatim, so their digits are by definition sourced).
    raw = json.dumps(report)
    allowed |= {_normalise(tok) for tok in _numbers_in(raw)}
    # Source (3): digit groups of the run id being narrated.
    allowed |= {_normalise(tok) for tok in _numbers_in(run_id)}
    return allowed


# --------------------------------------------------------------------------- #
# Fixture reports                                                             #
# --------------------------------------------------------------------------- #

VOLTARGET_RUN: dict[str, Any] = {
    "strategy": "voltarget",
    "dry_run": False,
    "timestamp": "2026-07-24T14:00:07.519467Z",
    "aborted": False,
    "equity": 98821.82,
    "target_weights": {"SPY": 0.85715659109397},
    "plan": {
        "equity": 98821.82, "cash": 14116.04,
        "current_weights": {"SPY": 0.9371},
        "target_weights": {"SPY": 0.85715659109397},
        "intents": [{"symbol": "SPY", "side": "sell", "notional": 7897.07,
                     "current_w": 0.9371, "target_w": 0.85715659109397}],
        "skipped": [{"symbol": "IEF", "current_w": 0.004, "target_w": 0.0,
                     "diff": 0.004}],
        "est_turnover": 0.0799, "buy_scale": 1.0, "min_trade_frac": 0.01,
    },
    "submitted_orders": [{"id": "oid-SPY", "client_order_id": "ql-voltarget-SPY-sell",
                          "symbol": "SPY", "side": "sell", "notional": 7897.07,
                          "status": "filled", "submitted_at": "2026-07-24T14:00:08Z",
                          "was_duplicate": False}],
    "no_trades": False,
    "stages": [{"stage": "risk_state", "ok": True, "detail": "not halted"},
               {"stage": "submit", "ok": True, "detail": "submitted 1 order(s)"}],
}

TREND_RUN: dict[str, Any] = {
    "strategy": "trend",
    "dry_run": True,
    "timestamp": "2026-07-23T14:00:16.183102Z",
    "aborted": False,
    "equity": 98467.50,
    "target_weights": {"SPY": 1.0},
    "plan": {"equity": 98467.50, "cash": 3.98, "current_weights": {"SPY": 0.99996},
             "target_weights": {"SPY": 1.0}, "intents": [], "skipped": [],
             "est_turnover": 0.0, "buy_scale": 1.0, "min_trade_frac": 0.01},
    "submitted_orders": [], "no_trades": True,
    "stages": [{"stage": "plan", "ok": True, "detail": "in-band, no trades"}],
}

ABORTED_RUN: dict[str, Any] = {
    "strategy": "crypto_voltarget",
    "dry_run": False,
    "timestamp": "2026-07-22T00:30:13.815500Z",
    "aborted": True,
    "abort_stage": "health",
    "abort_reason": "FREEZE_STALE_DATA: BTC-USD is 2 sessions stale",
    "equity": None, "target_weights": {}, "plan": None,
    "submitted_orders": [], "no_trades": False,
    "stages": [{"stage": "health", "ok": False, "detail": "stale"}],
}

ALL_RUNS = [
    ("run_voltarget_20260724T140007Z", VOLTARGET_RUN),
    ("run_trend_20260723T140016Z", TREND_RUN),
    ("run_crypto_voltarget_20260722T003013Z", ABORTED_RUN),
]


# --------------------------------------------------------------------------- #
# The hard rule                                                               #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(("run_id", "report"), ALL_RUNS, ids=[r[0] for r in ALL_RUNS])
def test_every_number_in_the_narration_is_derivable(
    run_id: str, report: dict[str, Any]
) -> None:
    narration = narrate_run(run_id, report)
    allowed = allowed_tokens(report, str(report["strategy"]), run_id)

    emitted = {_normalise(t) for t in _numbers_in(narration.narration)}
    undeclared = sorted(emitted - allowed)
    assert not undeclared, (
        f"narration emitted numbers not derivable from the report or its rule "
        f"constants: {undeclared}\nnarration: {narration.narration}"
    )


@pytest.mark.parametrize(("run_id", "report"), ALL_RUNS, ids=[r[0] for r in ALL_RUNS])
def test_every_fact_is_sourced_and_present_in_the_prose(
    run_id: str, report: dict[str, Any]
) -> None:
    """The stronger claim: each figure is traceable, and the trace is not decorative."""
    narration = narrate_run(run_id, report)
    for fact in narration.facts:
        assert fact.rendered in narration.narration, (
            f"fact {fact.rendered!r} is recorded but does not appear in the prose"
        )
        assert fact.source.startswith(("report.", "rule_constant.", "derived.")), (
            f"fact {fact.rendered!r} has an unrecognised source {fact.source!r}"
        )


def test_a_canary_field_never_leaks_into_the_narration() -> None:
    """A field no template references must not surface, however suggestive."""
    report = dict(VOLTARGET_RUN)
    report["analyst_note"] = "SPY fell because of the Fed announcement"
    report["news_headline"] = "Markets tumble on rate fears"
    report["model_confidence"] = 0.93
    report["canary_secret"] = "NEVER_EMIT_THIS"
    report["canary_number"] = 123456.789

    narration = narrate_run("run_voltarget_canary", report).narration
    for leak in ("NEVER_EMIT_THIS", "Fed", "announcement", "Markets tumble",
                 "rate fears", "confidence", "123456", "123,456"):
        assert leak not in narration, f"canary {leak!r} leaked into the narration"


def test_narration_contains_no_causal_or_market_commentary_vocabulary() -> None:
    """No narration may explain WHY the market moved — it has no such input."""
    forbidden = (
        " because the market", "investor", "sentiment", "rally", "sell-off",
        "selloff", "bullish", "bearish", "outlook", "forecast", "we expect",
        "likely to", "fed", "inflation", "earnings", "news", "analyst",
        "volatility spike", "fear",
    )
    for run_id, report in ALL_RUNS:
        narration = narrate_run(run_id, report).narration.lower()
        for phrase in forbidden:
            assert phrase not in narration, (
                f"{run_id} narration contains market commentary: {phrase!r}"
            )


# --------------------------------------------------------------------------- #
# Rule sentences and counterfactuals                                          #
# --------------------------------------------------------------------------- #

def test_voltarget_rule_sentence_is_the_vol_ratio_template() -> None:
    narration = narrate_run("run_voltarget_20260724T140007Z", VOLTARGET_RUN)
    assert len(narration.rule_sentences) == 1
    rule = narration.rule_sentences[0]
    assert "target volatility" in rule
    assert "realized volatility" in rule
    assert "20-day" in rule          # VolTarget.lookback_days
    assert "10%" in rule             # VolTarget.target_vol
    assert "252-day year" in rule    # equity annualization


def test_trend_rule_sentence_is_the_sma_template() -> None:
    narration = narrate_run("run_trend_20260723T140016Z", TREND_RUN)
    rule = narration.rule_sentences[0]
    assert "10-month simple moving average" in rule
    assert "above" in rule and "rotates" in rule
    assert "volatility" not in rule  # the wrong strategy's rule must not appear


def test_order_narration_carries_weight_turnover_and_notional() -> None:
    narration = narrate_run("run_voltarget_20260724T140007Z", VOLTARGET_RUN).narration
    assert "$7,897.07" in narration          # notional
    assert "93.71%" in narration             # current weight
    assert "85.72%" in narration             # target weight
    assert "0.0799" in narration             # est_turnover
    assert "SELL SPY" in narration


def test_counterfactual_states_the_branch_the_rule_did_not_take() -> None:
    narration = narrate_run("run_voltarget_20260724T140007Z", VOLTARGET_RUN)
    traded = next(c for c in narration.counterfactuals if c.startswith("SPY"))
    # drift = |0.85715659109397 - 0.9371| = 0.0799434...  -> 7.99%
    assert "7.99%" in traded
    assert "1.00%" in traded                 # the min_trade_frac band
    assert "would have left the position to drift untouched" in traded

    # The skipped symbol carries the OPPOSITE counterfactual.
    held = next(c for c in narration.counterfactuals if c.startswith("IEF"))
    assert "NOT traded" in held
    assert "0.40%" in held                   # its sub-band drift
    assert "would have re-traded it back to target" in held


def test_no_trade_run_says_so_without_inventing_orders() -> None:
    narration = narrate_run("run_trend_20260723T140016Z", TREND_RUN)
    assert "No orders were planned" in narration.narration
    assert "minimum-trade band" in narration.narration
    assert narration.counterfactuals == []
    assert "SELL" not in narration.narration and "BUY" not in narration.narration


def test_aborted_run_narrates_the_abort_and_claims_no_orders() -> None:
    narration = narrate_run("run_crypto_voltarget_20260722T003013Z", ABORTED_RUN)
    assert "ABORTED at stage 'health'" in narration.narration
    assert "placed no orders" in narration.narration
    assert "FREEZE_STALE_DATA" in narration.narration
    assert "Submitted to the broker" not in narration.narration


def test_dry_run_and_live_submit_are_distinguished() -> None:
    dry = narrate_run("a", TREND_RUN).narration
    live = narrate_run("b", VOLTARGET_RUN).narration
    assert "DRY RUN" in dry and "no orders could be sent" in dry
    assert "LIVE SUBMIT" in live and "DRY RUN" not in live


def test_disclaimer_states_the_constraint() -> None:
    narration = narrate_run("a", VOLTARGET_RUN)
    assert "no market commentary" in narration.disclaimer
    assert "traceable" in narration.disclaimer


# --------------------------------------------------------------------------- #
# Rule constants are grounded in code, not typed in                           #
# --------------------------------------------------------------------------- #

def test_rule_constants_match_the_live_strategy_objects() -> None:
    """Source (2) of the hard rule must reflect the code, not a hand-kept map."""
    assert rule_constants("voltarget") == {
        "target_vol": VolTarget().target_vol,
        "lookback_days": VolTarget().lookback_days,
        "max_weight": VolTarget().max_weight,
        "periods_per_year": VolTarget().periods_per_year,
    }
    assert rule_constants("crypto_voltarget") == {
        "target_vol": CryptoVolTargetBTC().target_vol,
        "lookback_days": CryptoVolTargetBTC().lookback_days,
        "max_weight": CryptoVolTargetBTC().max_weight,
        "periods_per_year": CryptoVolTargetBTC().periods_per_year,
    }
    assert rule_constants("trend") == {
        "n_months": TrendSMA10().n_months,
        "periods_per_year": TrendSMA10().periods_per_year,
    }
    assert rule_constants("crypto_trend") == {
        "n_months": CryptoTrendBTC().n_months,
        "periods_per_year": CryptoTrendBTC().periods_per_year,
    }


def test_crypto_voltarget_quotes_its_own_parameters_not_the_equity_ones() -> None:
    """The two vol-target accounts differ; the narration must not blur them."""
    report = dict(VOLTARGET_RUN)
    report["strategy"] = "crypto_voltarget"
    rule = narrate_run("x", report).rule_sentences[0]
    assert "20%" in rule          # CryptoVolTargetBTC target_vol == 0.20
    assert "365-day year" in rule  # crypto annualization
    assert "252" not in rule


def test_unknown_strategy_narrates_without_inventing_a_rule() -> None:
    report = dict(TREND_RUN)
    report["strategy"] = "not_a_strategy"
    narration = narrate_run("x", report)
    assert narration.rule_sentences == []
    assert "not_a_strategy" in narration.narration
    assert "moving average" not in narration.narration
    assert "volatility" not in narration.narration


def test_narration_survives_a_truncated_report() -> None:
    """A half-written report must narrate what it has, not raise."""
    for partial in ({}, {"strategy": "trend"}, {"strategy": "trend", "plan": None},
                    {"strategy": "voltarget", "plan": {"intents": [{}], "skipped": [{}]}},
                    {"strategy": "trend", "stages": "not-a-list",
                     "submitted_orders": "nope", "target_weights": "nope"}):
        narration = narrate_run("run_partial", partial)
        assert isinstance(narration.narration, str)
        assert narration.run_id == "run_partial"
