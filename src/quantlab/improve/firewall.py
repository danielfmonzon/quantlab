"""The firewall: what an automated proposal may never touch.

THIS IS STRUCTURAL, NOT ADVISORY. The distinction is the whole point. A prompt that
says "please do not tune the strategy parameters" is a request, and a request is
satisfied or not depending on how a model reads it that day. This module is a gate:
:func:`check` returns a refusal, ``propose`` will not write the file, and ``implement``
re-runs the same check against the ACTUAL diff before it will gate or push. A proposal
that touches a forbidden path cannot become a commit no matter how good the argument
for it is, because nothing in the pipeline has a code path that emits one.

WHY THESE THINGS SPECIFICALLY. The project's primary defense against overfitting is the
iron rule (2026-07-06): every strategy parameter is taken directly from the source
literature and is NEVER chosen or adjusted to improve a backtest metric. An automated
improvement loop is precisely the mechanism that would erode that rule fastest — it can
read the performance data, notice that a different lookback would have scored better,
and write a persuasive proposal saying so. That proposal would not be wrong on its own
terms. It would just be overfitting with a good bibliography. So the loop is not
permitted to form the thought in a way that reaches the repository.

The same reasoning covers the other four classes. Risk limits and thresholds are
DECISIONS with a dated ruling behind them, not tunables — a system that can widen its
own alerting threshold in response to an alert has removed the alarm, not the fault
(2026-08-10, "Residual thresholding: fix the instrument, not the threshold"). Schedule
cadences determine what the paper record even means, because a changed mark interval
silently redefines every divergence figure computed against it. Sanitizer patterns are
the secret-leak gate; a loop that can widen them can publish a key. Broker logic is the
order path, which has been frozen under human review since the first paper account went
live.

WHAT IS ALLOWED. Everything else — reporting, the Glass Box service, the frontend,
scheduling *plumbing* (as opposed to cadence), CLI ergonomics, tests, docs, CI. The loop
is meant to improve the machine around the strategy, never the strategy.

STRATEGY-PERFORMANCE DATA MAY INFORM INFRASTRUCTURE PROPOSALS ONLY. Reading the weekly
divergence figures to notice that the weekly is silent on a clean week is legitimate and
is exactly the kind of observation this pipeline exists to produce. Reading the same
figures to notice that `trend` would have done better with a 12-month SMA is the
forbidden move. The rule is enforced on the PROPOSAL'S EFFECT, not on what it read:
evidence is unrestricted within the allowed source set, affected paths are not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from quantlab.constants import PROJECT_ROOT

# Cited verbatim in every refusal, so the refusal explains itself without the reader
# needing to already know the project's history.
IRON_RULE = (
    "IRON RULE (docs/decisions.md, 2026-07-06 'Literature-fixed parameters and the "
    "\"iron rule\"'): every strategy parameter is taken directly from the source "
    "literature and is never chosen or adjusted to improve a backtest metric. "
    "Risk limits, alerting thresholds, schedule cadences, sanitizer patterns and the "
    "broker order path are dated DECISIONS under human review, not tunables. An "
    "automated proposal may improve the machine around the strategy; it may never "
    "adjust the strategy, the limits that constrain it, the instruments that measure "
    "it, or the gate that keeps secrets out of the published bytes."
)


@dataclass(frozen=True)
class ForbiddenPath:
    """A repo-relative path prefix no automated change may touch."""

    prefix: str
    reason: str

    def matches(self, rel_posix: str) -> bool:
        if self.prefix.endswith("/"):
            return rel_posix.startswith(self.prefix)
        return rel_posix == self.prefix


# Directories end in "/", files do not. Kept explicit rather than globbed so that reading
# this list tells you exactly what is frozen without evaluating a pattern language.
FORBIDDEN_PATHS: tuple[ForbiddenPath, ...] = (
    ForbiddenPath(
        "src/quantlab/backtest/strategies/",
        "strategy definitions and their literature-fixed parameters",
    ),
    ForbiddenPath(
        "src/quantlab/broker/",
        "the broker order path, frozen under human review since the first paper account",
    ),
    ForbiddenPath(
        "src/quantlab/risk/",
        "the risk engine: limits, kill-switch, and halt state",
    ),
    ForbiddenPath("config/risk.yaml", "equity risk limit values"),
    ForbiddenPath("config/crypto_risk.yaml", "crypto risk limit values"),
    ForbiddenPath(
        "src/quantlab/glassbox/sanitize.py",
        "sanitizer patterns — the secret-leak gate over published bytes",
    ),
    ForbiddenPath(
        "src/quantlab/scheduling/tasks.py",
        "schedule cadences, which define what the paper mark interval means",
    ),
)


@dataclass(frozen=True)
class ForbiddenClass:
    """A kind of change that is forbidden regardless of which file it lands in.

    Path rules alone are not enough: a threshold can be widened from a constant in a
    reporting module, and a cadence can be changed from a CLI default. These catch the
    INTENT where it is stated, in the proposal's own prose.
    """

    name: str
    reason: str
    # Both must appear for the class to fire — a target being discussed is not a
    # proposal to mutate it, and a mutation verb alone is most of English.
    targets: tuple[str, ...]
    verbs: tuple[str, ...] = (
        "widen", "widening", "raise", "raising", "lower", "lowering", "relax",
        "relaxing", "loosen", "loosening", "tune", "tuning", "retune", "adjust",
        "adjusting", "increase", "increasing", "decrease", "decreasing", "bump",
        "soften", "softening", "tighten", "tightening", "optimi", "recalibrat",
        "change", "changing", "set", "reset", "override", "disable", "remove",
    )


FORBIDDEN_CLASSES: tuple[ForbiddenClass, ...] = (
    ForbiddenClass(
        "strategy_parameters",
        "a literature-fixed parameter may never be chosen or adjusted to improve a metric",
        targets=(
            "lookback", "sma", "moving average", "strategy parameter", "vol target",
            "volatility target", "rebalance band", "momentum window", "signal lag",
        ),
    ),
    ForbiddenClass(
        "risk_limits",
        "risk limits are dated decisions with a ruling behind them, not tunables",
        targets=(
            "risk limit", "max drawdown", "drawdown limit", "kill switch", "kill-switch",
            "halt threshold", "position limit", "exposure limit",
        ),
    ),
    ForbiddenClass(
        "threshold_constants",
        "widening the alarm in response to the alarm removes the alarm, not the fault",
        targets=(
            "threshold", "diverging threshold", "divergence threshold", "bps limit",
            "alert threshold", "tolerance",
        ),
    ),
    ForbiddenClass(
        "schedule_cadence",
        "a changed mark interval silently redefines every divergence figure",
        targets=(
            "cadence", "schedule time", "run time", "cron", "trigger time",
            "how often", "frequency of the run", "mark interval", "submit cutoff",
        ),
    ),
    ForbiddenClass(
        "sanitizer_patterns",
        "the sanitizer is the secret-leak gate; widening it can publish a key",
        targets=(
            "sanitiz", "forbidden pattern", "redaction pattern", "secret pattern",
            "allowlist of secrets", "env_secret",
        ),
    ),
    ForbiddenClass(
        "broker_logic",
        "the order path is frozen under human review",
        targets=(
            "broker logic", "order submission", "order path", "order type",
            "submit logic", "fill logic",
        ),
    ),
)


@dataclass(frozen=True)
class Refusal:
    """One reason a proposal was refused."""

    kind: str          # "path" | "class"
    identifier: str    # the offending path, or the class name
    reason: str
    evidence: str = "" # the phrase or path that triggered it


@dataclass
class FirewallVerdict:
    allowed: bool
    refusals: list[Refusal] = field(default_factory=list)

    def render(self) -> str:
        """The refusal text. Always cites the iron rule — that is the whole point."""
        if self.allowed:
            return "FIREWALL PASS — no forbidden path or change class touched."
        lines = [
            "=" * 72,
            "FIREWALL REFUSAL — this proposal will not be written.",
            "=" * 72,
            "",
        ]
        for r in self.refusals:
            if r.kind == "path":
                lines.append(f"  FORBIDDEN PATH   {r.identifier}")
            else:
                lines.append(f"  FORBIDDEN CLASS  {r.identifier}")
            lines.append(f"                   {r.reason}")
            if r.evidence:
                lines.append(f"    triggered by:  {r.evidence}")
            lines.append("")
        lines += [
            IRON_RULE,
            "",
            "This refusal is structural. There is no flag that overrides it and no code "
            "path in `propose` or `implement` that emits a proposal touching these. If "
            "the change is genuinely warranted, it is a HUMAN decision: take it to the "
            "Quant Lead, and if it is approved it is recorded as a dated ruling in "
            "docs/decisions.md and applied by hand.",
        ]
        return "\n".join(lines)


def _normalise(path: str | Path) -> str:
    """Repo-relative POSIX form, so matching is stable across OS and absolute inputs.

    BACKSLASHES ARE SEPARATORS ON EVERY PLATFORM, not only on Windows. `Path` is
    platform-dependent here and that dependence was a real hole in the gate, not merely a
    test artifact: on POSIX, ``Path(r"config\\risk.yaml")`` is a single filename that
    happens to contain a backslash, so it never matched the ``config/risk.yaml`` entry and
    the firewall ALLOWED it. CI on ubuntu-latest is what surfaced it (2026-08-15) — the
    same assertion passed on the Windows dev machine, where `Path` splits on backslash.

    A gate whose verdict depends on which operating system evaluates it is not a gate. So
    the separator is normalised in the string, before `Path` ever sees it. The cost is
    that a POSIX filename containing a literal backslash is read as a path; for a
    security boundary that is the correct direction to be wrong in.
    """
    p = Path(str(path).replace("\\", "/"))
    if p.is_absolute():
        try:
            p = p.relative_to(PROJECT_ROOT)
        except ValueError:
            return p.as_posix()
    return p.as_posix().lstrip("./")


def check_paths(paths: list[str] | tuple[str, ...]) -> list[Refusal]:
    """Refusals for any affected path that lands inside a frozen area."""
    out: list[Refusal] = []
    for raw in paths:
        rel = _normalise(raw)
        for forbidden in FORBIDDEN_PATHS:
            if forbidden.matches(rel):
                out.append(Refusal("path", rel, forbidden.reason, evidence=rel))
                break
    return out


def _term_pattern(term: str) -> re.Pattern[str]:
    """Word-boundary matcher for one target or verb.

    Naive substring matching is wrong in both directions and was a real defect: `change`
    matched inside "un**change**d", so the sentence "the threshold value itself is
    unchanged" — an explicit statement that nothing is being tuned — was refused as a
    proposal to tune it. A firewall that fires on its own disclaimers trains its operator
    to route around it, which is the failure mode the sanitizer's `apca_api_header`
    pattern was already narrowed to avoid (2026-07-26).

    Leading `\\b` always; trailing `\\b` too for short alphabetic terms, where a prefix
    match is nearly always a different word — `set` in "settled", `sma` in "smart",
    `cron` in "chronic". Longer terms keep the open end deliberately, so `optimi` covers
    optimise/optimize/optimisation and `raise` covers raises/raised.
    """
    escaped = re.escape(term)
    if len(term) <= 4 and term.isalpha():
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(rf"\b{escaped}", re.IGNORECASE)


def _first_match(terms: tuple[str, ...], text: str) -> str | None:
    return next((t for t in terms if _term_pattern(t).search(text)), None)


def check_text(text: str) -> list[Refusal]:
    """Refusals for a forbidden change class stated in the proposal's own prose.

    Fails CLOSED by design: a proposal that merely discusses a threshold in mutating
    language is refused even when the mutation was not the point. Over-refusal costs a
    human sentence of clarification; under-refusal costs the iron rule.
    """
    out: list[Refusal] = []
    for cls in FORBIDDEN_CLASSES:
        hit_target = _first_match(cls.targets, text)
        if hit_target is None:
            continue
        hit_verb = _first_match(cls.verbs, text)
        if hit_verb is None:
            continue
        # Quote the sentence that fired, so the refusal is actionable rather than cryptic.
        # Both halves must co-occur IN THE SAME SENTENCE for the quote to be honest; if
        # they never do, the class still fires but says so without inventing a quote.
        sentence = ""
        for candidate in re.split(r"(?<=[.!?])\s+|\n", text):
            if _first_match(cls.targets, candidate) and _first_match(cls.verbs, candidate):
                sentence = candidate.strip()
                break
        out.append(Refusal(
            "class", cls.name, cls.reason,
            evidence=f'"{sentence}"' if sentence else f"target={hit_target!r} verb={hit_verb!r}",
        ))
    return out


def check(*, affected_paths: list[str] | tuple[str, ...] = (), text: str = "") -> FirewallVerdict:
    """The gate. Both halves run; a proposal must clear paths AND prose."""
    refusals = check_paths(affected_paths) + check_text(text)
    return FirewallVerdict(allowed=not refusals, refusals=refusals)


__all__ = [
    "IRON_RULE",
    "ForbiddenPath",
    "ForbiddenClass",
    "FORBIDDEN_PATHS",
    "FORBIDDEN_CLASSES",
    "Refusal",
    "FirewallVerdict",
    "check",
    "check_paths",
    "check_text",
]
