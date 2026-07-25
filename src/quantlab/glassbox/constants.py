"""Documented constants behind the Glass Box's interpretations.

Everything here is a *stated editorial position* rather than something read out of
an artifact, so it lives in one file where it can be reviewed and argued with. Two
categories matter most:

* ``VALIDATION_TIERS`` — how strong the evidence for each account is. A label, not
  a measurement.
* the provenance schedule constants — how a paper equity mark's timestamp is
  classified against the task schedule that was supposed to produce it.

The narration rule constants are deliberately NOT here: they are read off the live
strategy objects (see ``narrate.rule_constants``) so they cannot drift into
fiction.
"""

from __future__ import annotations

from datetime import date, timedelta

# --------------------------------------------------------------------------- #
# Validation tiers                                                            #
# --------------------------------------------------------------------------- #
# Deliberately coarse. "Proven" is EARNED at the day-90 readiness gate and not
# before; "Probable" is where an account sits while the battery is on record but
# the live paper track has not yet run the gate. Neither tier is a claim about
# future returns.
TIER_PROVEN = "Proven"
TIER_PROBABLE = "Probable"

# QUANT LEAD RULING 2026-07-25: every account is Probable. The equity accounts were
# previously labelled Proven on the strength of their validation battery and a
# 15-day paper track, which inverted the gate — the battery is the ENTRY condition
# for paper tracking, not a substitute for it. No account can be Proven before its
# asset class passes a clean day-90 review.
VALIDATION_TIERS: dict[str, str] = {
    "voltarget": TIER_PROBABLE,
    "trend": TIER_PROBABLE,
    "crypto_trend": TIER_PROBABLE,
    "crypto_voltarget": TIER_PROBABLE,
}

TIER_RATIONALE: dict[str, str] = {
    TIER_PROVEN: (
        "Pre-registered parameters, the full validation battery on record, AND a "
        "clean day-90 readiness review passed on live paper tracking. Still not a "
        "forecast — only a statement about evidence already collected."
    ),
    TIER_PROBABLE: (
        "Pre-registered parameters from the source literature and the full "
        "validation battery (walk-forward, bootstrap, perturbation) on record — but "
        "the day-90 readiness gate has NOT yet been passed, so the live track "
        "cannot yet corroborate the backtest. Probable is the honest ceiling until "
        "it does."
    ),
}

# The readiness gate an account must clear to reach Proven, per asset class. Each
# class runs its own 90-day clock (equity from its first snapshot, crypto from the
# 2026-07-22 restart), so each has its own projected date.
READINESS_TARGET_DAYS = 90

TIER_UPGRADE_CONDITION_TEMPLATE = (
    "Proven upon a clean day-{days} readiness review for {asset_class} — no "
    "DIVERGING weeks, no KILL, and at least four completed runs per week "
    "sustained to the gate{projection}."
)

# Used only when no weekly review is on disk to read a real clock start from.
# Derived from each class's known paper start: equity 2026-07-09 + 90d, crypto
# 2026-07-22 + 90d (the restart).
TIER_UPGRADE_FALLBACK_DATE: dict[str, date] = {
    "us_equity": date(2026, 10, 7),
    "crypto": date(2026, 10, 20),
}


def upgrade_condition(
    asset_class: str,
    paper_start_date: date | None = None,
    target_days: int = READINESS_TARGET_DAYS,
) -> str:
    """What this asset class must do to earn Proven, with a projected date.

    The date is computed from the clock's ACTUAL start where one is available, so it
    tracks a restart instead of going stale; the fallback is used only when no
    weekly review exists to read a start from.
    """
    start = paper_start_date or TIER_UPGRADE_FALLBACK_DATE.get(asset_class)
    if start is None:
        projection = ""
    else:
        gate = (start + timedelta(days=target_days)) if paper_start_date else start
        projection = f", projected ~{gate.isoformat()}"
    return TIER_UPGRADE_CONDITION_TEMPLATE.format(
        days=target_days, asset_class=asset_class, projection=projection
    )

# --------------------------------------------------------------------------- #
# Equity-mark provenance                                                      #
# --------------------------------------------------------------------------- #
# Scheduled task times, expressed in UTC. The scheduler (scheduling/tasks.py) uses
# the HOST's local clock: the equity `paper run-all` fires at 10:00 local and the
# crypto run at 20:30 local. On US Eastern DAYLIGHT time those are 14:00 UTC and
# 00:30 UTC respectively, which is what every mark in the 2026-07 record shows.
#
# DOCUMENTED LIMITATION: these are the EDT-era offsets. Under EST the same tasks
# land an hour later (15:00 / 01:30 UTC) and marks from a standard-time month would
# be classified `catch_up` rather than `on_schedule`. Fixing that needs a real
# tz-aware schedule model, which is a later decision, not a silent guess here.
EQUITY_RUN_UTC_MINUTES = 14 * 60      # 10:00 America/New_York (EDT)
CRYPTO_RUN_UTC_MINUTES = 0 * 60 + 30  # 20:30 America/New_York (EDT), next UTC day

# A mark this close to its scheduled minute counts as punctual. Observed on-time
# marks land 5-55 seconds late; 30 minutes is deliberately generous so ordinary
# host latency is never reported as a catch-up.
ON_SCHEDULE_TOLERANCE_MINUTES = 30

# A CRYPTO mark inside this window around the EQUITY run time can only have come
# from the equity task iterating the crypto accounts — the leak fixed on
# 2026-07-22. The window is wider than the punctuality tolerance because a LATE
# equity task drags its leaked crypto marks along with it (2026-07-16 15:09 UTC).
LEAKED_WINDOW_MINUTES = 90

PROVENANCE_ON_SCHEDULE = "on_schedule"
PROVENANCE_CATCH_UP = "catch_up"
PROVENANCE_LEAKED = "leaked"

PROVENANCE_RATIONALE: dict[str, str] = {
    PROVENANCE_ON_SCHEDULE: (
        "Mark landed within 30 minutes of this account's scheduled run time."
    ),
    PROVENANCE_CATCH_UP: (
        "Mark landed well outside the scheduled window — a StartWhenAvailable "
        "catch-up run after a missed start. The mark is real; its SPACING from the "
        "neighbouring marks is not one uniform session."
    ),
    PROVENANCE_LEAKED: (
        "A crypto mark produced by the 10:00 ET EQUITY task, which iterated the "
        "crypto accounts until the --asset-class us_equity fix on 2026-07-22."
    ),
}

# --------------------------------------------------------------------------- #
# The week 2026-07-24 correction (reference only — never recomputed here)      #
# --------------------------------------------------------------------------- #
# Both DIVERGING verdicts published for week 2026-07-24 were measurement
# artifacts. The published reports stand as the record of what was reported; the
# corrections were ruled in docs/decisions.md. The Glass Box SURFACES that pair so
# a reader sees both numbers and the ruling, and does NOT recompute either.
DECISIONS_CORRECTION_REF = (
    "docs/decisions.md — 2026-07-25 — "
    "Week 2026-07-24 divergence diagnosis, and two re-rulings"
)

WEEK_CORRECTIONS: dict[str, dict[str, dict[str, object]]] = {
    "2026-07-24": {
        "trend": {
            "published_divergence_bps": -54.33,
            "published_verdict": "DIVERGING",
            "corrected_divergence_bps": -6.06,
            "corrected_verdict": "TRACKING",
            "corrected_window": "2026-07-16 -> 2026-07-23",
            "cause": (
                "The 2026-07-24 14:00Z snapshot was compared against a shadow with "
                "no 2026-07-24 session at all (SPY's EOD bar did not exist yet), so "
                "that day's -32 bps landed whole in the divergence. Aligning the "
                "windows leaves structural 10:00-ET-vs-close mark-phase drift."
            ),
        },
        "crypto_voltarget": {
            "published_divergence_bps": 91.24,
            "published_verdict": "DIVERGING",
            "corrected_divergence_bps": None,
            "corrected_verdict": "VOIDED",
            "corrected_window": None,
            "cause": (
                "The BTC 2026-07-24 daily bar was PARTIAL when the review ran "
                "(65,230 at 05:43 UTC against a 64,083 final close), so the figure "
                "is not reproducible: recomputing yields +211 bps and flips the "
                "cumulative sign. No verdict is recorded for this week; the next "
                "clean Friday decides."
            ),
        },
    }
}

# --------------------------------------------------------------------------- #
# Ignored inputs                                                              #
# --------------------------------------------------------------------------- #
# The honest inverse of a feature list: what this system reads, and what it
# deliberately refuses to read. Replaces any "AI confidence" or news-sentiment
# surface, which would imply reasoning the system does not perform.
INPUTS_READ: list[dict[str, str]] = [
    {
        "name": "Tiingo end-of-day bars",
        "role": "primary equity EOD price source",
        "rationale": "Adjusted daily closes are the only prices every strategy signal reads.",
    },
    {
        "name": "Alpaca IEX end-of-day bars",
        "role": "independent cross-check on Tiingo",
        "rationale": (
            "A second feed reconciled against the first (data/reconcile.py) catches "
            "a bad vendor print before it reaches a signal."
        ),
    },
    {
        "name": "Coinbase daily candles",
        "role": "crypto EOD price source (BTC-USD)",
        "rationale": "The 24/7 UTC-day equivalent of the equity EOD feed.",
    },
    {
        "name": "Alpaca paper account state",
        "role": "positions, cash, equity for the paper accounts",
        "rationale": "What the account actually holds, never a source of signal.",
    },
    {
        "name": "Exchange calendars (XNYS) and a 24/7 UTC calendar",
        "role": "session boundaries and completion cutoffs",
        "rationale": "Decides which bars are settled enough to read at all.",
    },
]

INPUTS_IGNORED: list[dict[str, str]] = [
    {
        "name": "News and headlines",
        "rationale": (
            "No strategy has a news term. Surfacing headlines beside a position "
            "would invite a causal story the system never computed."
        ),
    },
    {
        "name": "Earnings reports and guidance",
        "rationale": (
            "The universe is broad-market ETFs; single-name fundamentals are not an "
            "input to any signal."
        ),
    },
    {
        "name": "Analyst ratings and price targets",
        "rationale": "Third-party opinion is not a pre-registered, testable input.",
    },
    {
        "name": "Social and market sentiment scores",
        "rationale": (
            "Not in any pre-registered rule, and the iron rule forbids adding an "
            "input because it would have improved a backtest."
        ),
    },
    {
        "name": "Intraday bars, quotes, and order-book depth",
        "rationale": (
            "Every signal is computed from settled daily closes. Intraday data is "
            "not stored, which is why the Glass Box reports mark timing as "
            "structural drift rather than pretending to price it."
        ),
    },
    {
        "name": "Macroeconomic releases and rate decisions",
        "rationale": (
            "Trend and volatility targeting respond to price only; a macro overlay "
            "would be a new, unvalidated strategy."
        ),
    },
    {
        "name": "Any large-language-model judgement about the market",
        "rationale": (
            "No endpoint in this service asks a model what it thinks. Narration is "
            "template-bound to structured run fields (see narrate.py); anything "
            "beyond that would be fabrication wearing an explanation's clothes."
        ),
    },
]


__all__ = [
    "VALIDATION_TIERS",
    "TIER_PROVEN",
    "TIER_PROBABLE",
    "TIER_RATIONALE",
    "READINESS_TARGET_DAYS",
    "TIER_UPGRADE_CONDITION_TEMPLATE",
    "TIER_UPGRADE_FALLBACK_DATE",
    "upgrade_condition",
    "EQUITY_RUN_UTC_MINUTES",
    "CRYPTO_RUN_UTC_MINUTES",
    "ON_SCHEDULE_TOLERANCE_MINUTES",
    "LEAKED_WINDOW_MINUTES",
    "PROVENANCE_ON_SCHEDULE",
    "PROVENANCE_CATCH_UP",
    "PROVENANCE_LEAKED",
    "PROVENANCE_RATIONALE",
    "DECISIONS_CORRECTION_REF",
    "WEEK_CORRECTIONS",
    "INPUTS_READ",
    "INPUTS_IGNORED",
]
