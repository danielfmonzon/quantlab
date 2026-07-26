"""Template-bound narration of a single paper run.

THE HARD RULE. Every token in a narration must be derivable from exactly three
sources, and the test suite enforces it:

1. the run report's own structured fields,
2. the account's pre-registered rule constants, which are read off the LIVE
   strategy object (``rule_constants``) rather than typed in here — so they cannot
   drift into fiction while still passing a test, and
3. the ``run_id`` being narrated, echoed as the narration's subject. An identifier
   supplied by the caller; it asserts nothing about the world.

Nothing else. No market commentary, no news, no "because the market fell", no
inferred motive, no LLM judgement. The narrator is a formatter, not an analyst.
Every rendered number is recorded as a :class:`NarrationFact` carrying its source
path, so a reader (and a test) can trace each figure back to the field it came
from. If a fact cannot be sourced, it is not emitted.

Counterfactuals are stated because a rule you only see fire is a rule you cannot
audit: for each order the narration also names the branch NOT taken (the drift band
the position would have been left alone under), computed from the report's own
``min_trade_frac``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from quantlab.paper.runner import make_paper_strategy

# Attributes that constitute an account's published rule parameters. Read from the
# strategy instance; absent attributes are simply not part of that rule.
_RULE_ATTRS = ("target_vol", "lookback_days", "max_weight", "n_months")

_DISCLAIMER = (
    "Generated from this run's structured fields and the strategy's pre-registered "
    "rule parameters only. It contains no market commentary, no news, and no "
    "inferred reasoning: every number above is traceable to a named source field."
)


class NarrationFact(BaseModel):
    """One rendered figure and where it came from."""

    rendered: str
    value: float | int | str
    source: str


class RunNarration(BaseModel):
    run_id: str
    strategy: str
    narration: str
    rule_sentences: list[str] = []
    counterfactuals: list[str] = []
    facts: list[NarrationFact] = []
    disclaimer: str = _DISCLAIMER
    available: bool = True
    note: str | None = None


def rule_constants(label: str) -> dict[str, float | int]:
    """The account's pre-registered rule parameters, read off the live strategy.

    Sourcing these from the object rather than a literal map means a parameter
    change in the strategy is reflected here automatically, and a narration can
    never quote a parameter the code does not actually use.
    """
    try:
        strategy = make_paper_strategy(label)
    except Exception:  # noqa: BLE001 - unknown label narrates without rule constants
        return {}
    out: dict[str, float | int] = {}
    for attr in _RULE_ATTRS:
        value = getattr(strategy, attr, None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[attr] = value
    try:
        out["periods_per_year"] = int(strategy.periods_per_year)
    except Exception:  # noqa: BLE001
        pass
    return out


class _Facts:
    """Accumulates rendered figures with their provenance."""

    def __init__(self) -> None:
        self.items: list[NarrationFact] = []

    def add(self, rendered: str, value: float | int | str, source: str) -> str:
        self.items.append(NarrationFact(rendered=rendered, value=value, source=source))
        return rendered

    def pct(self, value: float, source: str) -> str:
        return self.add(f"{value * 100:.2f}%", value, source)

    def pct0(self, value: float, source: str) -> str:
        return self.add(f"{value * 100:.0f}%", value, source)

    def money(self, value: float, source: str) -> str:
        return self.add(f"${value:,.2f}", value, source)

    def ratio(self, value: float, source: str) -> str:
        return self.add(f"{value:.4f}", value, source)

    def count(self, value: int, source: str) -> str:
        return self.add(str(value), value, source)


def _as_float(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _rule_sentence(label: str, consts: dict[str, float | int], facts: _Facts) -> str | None:
    """The account's rule in one sentence, with its own parameters substituted."""
    if "target_vol" in consts and "lookback_days" in consts:
        target = facts.pct0(float(consts["target_vol"]), f"rule_constant.{label}.target_vol")
        window = facts.count(int(consts["lookback_days"]),
                             f"rule_constant.{label}.lookback_days")
        parts = [
            f"Rule: {label} sizes exposure as its target volatility ({target}) divided "
            f"by trailing {window}-day realized volatility"
        ]
        if "periods_per_year" in consts:
            ann = facts.count(int(consts["periods_per_year"]),
                              f"rule_constant.{label}.periods_per_year")
            parts.append(f", annualized on a {ann}-day year")
        if "max_weight" in consts:
            cap = facts.pct0(float(consts["max_weight"]),
                             f"rule_constant.{label}.max_weight")
            parts.append(f", capped at {cap} of equity")
        return "".join(parts) + "; the remainder is held in cash."
    if "n_months" in consts:
        months = facts.count(int(consts["n_months"]), f"rule_constant.{label}.n_months")
        return (
            f"Rule: {label} holds the risk asset while its price is above its "
            f"{months}-month simple moving average, and rotates to the safe asset or "
            "cash otherwise."
        )
    return None


def _order_lines(report: dict[str, Any], facts: _Facts) -> tuple[list[str], list[str]]:
    """One paragraph per intent, plus the counterfactual branch each did not take."""
    plan = report.get("plan")
    if not isinstance(plan, dict):
        return [], []

    band = _as_float(plan.get("min_trade_frac"))
    lines: list[str] = []
    counterfactuals: list[str] = []

    intents = plan.get("intents")
    for idx, intent in enumerate(intents if isinstance(intents, list) else []):
        if not isinstance(intent, dict):
            continue
        symbol = str(intent.get("symbol", "?"))
        side = str(intent.get("side", "?"))
        src = f"report.plan.intents[{idx}]"
        bits = [f"{side.upper()} {symbol}"]

        notional = _as_float(intent.get("notional"))
        if notional is not None:
            bits.append(f"for {facts.money(notional, f'{src}.notional')} notional")
        cur_w = _as_float(intent.get("current_w"))
        tgt_w = _as_float(intent.get("target_w"))
        if cur_w is not None and tgt_w is not None:
            bits.append(
                f"moving weight from {facts.pct(cur_w, f'{src}.current_w')} to "
                f"{facts.pct(tgt_w, f'{src}.target_w')}"
            )
        lines.append(" ".join(bits) + ".")

        if cur_w is not None and tgt_w is not None and band is not None:
            drift = abs(tgt_w - cur_w)
            counterfactuals.append(
                f"{symbol}: traded because drift was "
                f"{facts.pct(drift, f'derived.abs({src}.target_w - {src}.current_w)')}, "
                f"above the {facts.pct(band, 'report.plan.min_trade_frac')} "
                "minimum-trade band; had drift been at or below that band the runner "
                "would have left the position to drift untouched, placing no order."
            )

    skipped = plan.get("skipped")
    for idx, entry in enumerate(skipped if isinstance(skipped, list) else []):
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol", "?"))
        diff = _as_float(entry.get("diff"))
        if diff is None or band is None:
            continue
        # `plan.skipped[].diff` is SIGNED (target minus current), but the band test the
        # sentence describes is on its magnitude — the runner skips when
        # |diff| <= min_trade_frac. Reporting the signed value produced "drift was
        # -0.13%, at or below the 1.00% band", which reads as a different, weaker claim.
        counterfactuals.append(
            f"{symbol}: NOT traded because drift was "
            f"{facts.pct(abs(diff), f'derived.abs(report.plan.skipped[{idx}].diff)')}, "
            f"at or below the {facts.pct(band, 'report.plan.min_trade_frac')} "
            "minimum-trade band; had drift exceeded that band the runner would have "
            "re-traded it back to target."
        )

    return lines, counterfactuals


def narrate_run(run_id: str, report: dict[str, Any]) -> RunNarration:
    """Narrate one run report. Template-only; see this module's hard rule."""
    label = str(report.get("strategy", "")) or "unknown"
    facts = _Facts()
    consts = rule_constants(label)
    paragraphs: list[str] = []

    # -- what ran ----------------------------------------------------------
    stamp = report.get("timestamp")
    when = f" at {stamp}" if isinstance(stamp, str) and stamp else ""
    dry_run = report.get("dry_run")
    mode = ("a DRY RUN (no orders could be sent)" if dry_run
            else "a LIVE SUBMIT against the paper broker" if dry_run is False
            else "an unrecorded mode")
    paragraphs.append(f"Run {run_id}: account {label} executed{when} as {mode}.")

    # -- outcome -----------------------------------------------------------
    if report.get("aborted"):
        stage = report.get("abort_stage") or "unknown"
        reason = report.get("abort_reason") or "no reason recorded"
        paragraphs.append(
            f"The gated pipeline ABORTED at stage '{stage}' and placed no orders. "
            f"Reason as recorded: {reason}"
        )
    else:
        stages = report.get("stages")
        n_ok = sum(1 for s in stages if isinstance(s, dict) and s.get("ok")) \
            if isinstance(stages, list) else 0
        if n_ok:
            paragraphs.append(
                f"The gated pipeline completed {facts.count(n_ok, 'report.stages[*].ok')} "
                "stages without aborting."
            )

    equity = _as_float(report.get("equity"))
    if equity is not None:
        paragraphs.append(f"Account equity was read as {facts.money(equity, 'report.equity')}.")

    # -- the rule ----------------------------------------------------------
    rule_sentences: list[str] = []
    sentence = _rule_sentence(label, consts, facts)
    if sentence is not None:
        rule_sentences.append(sentence)
        paragraphs.append(sentence)

    targets = report.get("target_weights")
    if isinstance(targets, dict) and targets:
        rendered = []
        for symbol, weight in targets.items():
            value = _as_float(weight)
            if value is None:
                continue
            rendered.append(
                f"{symbol} at {facts.pct(value, f'report.target_weights.{symbol}')}"
            )
        if rendered:
            paragraphs.append("That rule produced a target of " + ", ".join(rendered) + ".")
    elif isinstance(targets, dict):
        paragraphs.append("That rule produced a target of 100% cash (no positions).")

    # -- orders ------------------------------------------------------------
    order_lines, counterfactuals = _order_lines(report, facts)
    raw_plan = report.get("plan")
    plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    turnover = _as_float(plan.get("est_turnover"))

    if order_lines:
        paragraphs.append("Planned orders: " + " ".join(order_lines))
    elif report.get("no_trades"):
        paragraphs.append(
            "No orders were planned: every holding was already inside the "
            "minimum-trade band, so the run left the account untouched."
        )
    if turnover is not None:
        paragraphs.append(
            f"Estimated turnover for the plan was "
            f"{facts.ratio(turnover, 'report.plan.est_turnover')} of equity."
        )

    submitted = report.get("submitted_orders")
    if isinstance(submitted, list) and submitted:
        bits = []
        for idx, order in enumerate(submitted):
            if not isinstance(order, dict):
                continue
            src = f"report.submitted_orders[{idx}]"
            notional = _as_float(order.get("notional"))
            amount = f" for {facts.money(notional, f'{src}.notional')}" if notional else ""
            dup = " (flagged a duplicate)" if order.get("was_duplicate") else ""
            bits.append(
                f"{order.get('side', '?')} {order.get('symbol', '?')}{amount} — broker "
                f"status '{order.get('status', 'unknown')}'{dup}"
            )
        if bits:
            paragraphs.append("Submitted to the broker: " + "; ".join(bits) + ".")

    if counterfactuals:
        paragraphs.append("Branches the rule did not take: " + " ".join(counterfactuals))

    return RunNarration(
        run_id=run_id, strategy=label, narration=" ".join(paragraphs),
        rule_sentences=rule_sentences, counterfactuals=counterfactuals,
        facts=facts.items,
    )


__all__ = ["narrate_run", "rule_constants", "RunNarration", "NarrationFact"]
