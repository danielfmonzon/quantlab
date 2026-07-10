# Decision log

Major design decisions made during the quantlab build, with rationale. Each
entry is dated to the build phase in which the decision was made; the log was
compiled on 2026-07-10 (v1.0.0). Newest entries first.

---

## 2026-07-10 — Version stamping on every report

**Decision.** Introduce a single `__version__` ("1.0.0") and embed
`version + git short hash` in every digest and weekly-review header.

**Rationale.** Generated reports drive operational decisions (including the
eventual live-readiness call). Every artifact must be traceable to the exact
commit that produced it, so a report can never be silently attributed to the
wrong code. The hash is computed at render time and degrades cleanly to the bare
version when git is unavailable.

---

## 2026-07-09 — Dividend-drag expectation in shadow tracking

**Decision.** The weekly review compares paper equity to a **shadow** return
series and *expects* paper to lag the shadow over time; the gap is annotated as
dividend drag rather than alarmed on.

**Rationale.** Alpaca paper does **not** credit cash dividends, while the shadow
uses dividend-adjusted (`adj_close`) returns, which include them. Over long
windows paper therefore trails the shadow by roughly the portfolio's dividend
yield — a *structural* difference, not tracking error. Two further structural
gaps are documented: paper equity is marked ~10:00 ET while the shadow is
close-to-close, and paper fills at ~10:00 vs the shadow's close price add
entry-day noise. The DIVERGING threshold (50 bps) and the dividend-drag note
exist so the review distinguishes expected drift from genuine divergence.

---

## 2026-07-09 — Per-account state isolation

**Decision.** Each approved strategy runs in its **own** Alpaca paper account with
fully isolated state: `data/equity_history_{label}.parquet` and
`data/risk_state_{label}.json`. The runner reads/writes only its own label.

**Rationale.** A KILL in one strategy must never halt another, and equity/risk
histories must not be co-mingled (that would corrupt drawdown and divergence
math). Isolation also mirrors how independent live sleeves would be operated and
keeps a single account's failure contained.

---

## 2026-07-08 — Risk thresholds are live-ops policy, never backtest-tuned

**Decision.** `RiskLimits` (3% daily HALT, 8% weekly HALT, 25% drawdown KILL,
etc.) are set as **operational policy**, chosen independently of any backtest
result, and never adjusted to improve historical performance.

**Rationale.** Tuning risk limits against the backtest would overfit the safety
system to the past and defeat its purpose. Limits express how much loss is
tolerable in live operation — a risk-appetite question, not an optimization
target. They are validated on load (`daily < weekly < kill`) and applied
identically in backtest overlay and paper trading.

---

## 2026-07-08 — Converge-to-target vs rebalance-date semantics

**Decision.** The **backtest** trades only on rebalance dates (month-end weights
take effect at t+1 and then drift). The **paper runner** instead converges toward
the *current* target whenever live drift exceeds `min_trade_frac` (1%), not only
on the rebalance day.

**Rationale.** A live process can miss its month-end run (host down, holiday, late
feed). Converge-to-target lets the next successful run still reach the intended
allocation. Because signals are monthly and only change at month-ends, the two
policies pursue the *same* target and differ only in *when* it is reached; the 1%
band prevents reconvergence churn. The shadow simulation mirrors these exact
semantics so paper-vs-shadow comparisons are apples-to-apples.

---

## 2026-07-07 — Exclude `dualmom` from paper trading

**Decision.** Dual Momentum (`dualmom`) remains available for backtesting and
research but is **excluded** from the paper-trading roster. Approved strategies
are `voltarget` and `trend` only.

**Rationale.** In the validation battery `dualmom` showed a Sharpe of ~**0.60**
and a bootstrap probability of a drawdown worse than −30% of **72.2%**. With a
25% max-drawdown **kill** policy, a strategy expected to breach the kill threshold
the majority of the time is not a viable candidate for capital — it would spend
much of its life in a manual-reset KILL state. This is a **risk** decision
grounded in the tail analysis, not a performance-ranking or data-mining one.

---

## 2026-07-06 — Literature-fixed parameters and the "iron rule"

**Decision.** Every strategy parameter is taken **directly from the source
literature** and never tuned to our data: Faber's 10-month SMA (`trend`),
Antonacci's 12-month lookback (`dualmom`), a conventional 10% target with a
20-day realized window (`voltarget`), 60/40 for the balanced baseline.

**Rationale.** The iron rule — no parameter is ever chosen or adjusted to improve
a backtest metric — is the project's primary defense against overfitting. Fixed,
citable parameters make results honest and reproducible, and make walk-forward /
perturbation analysis meaningful rather than circular.

---

## 2026-07-05 — Custom daily engine over vectorbt

**Decision.** Implement a custom NumPy/pandas daily backtest engine instead of
adopting `vectorbt`.

**Rationale.** `vectorbt`'s numba/numpy version pins conflicted with the rest of
the stack under the project's uv-locked environment, and the engine's needs are
narrow and specific: adj_close returns, a strict one-session signal lag (no
lookahead by construction), weight drift between rebalances, and a turnover cost
model. A ~250-line engine we fully control — and can mirror exactly with a test
oracle — is more maintainable and auditable than fighting a heavyweight
dependency for features we do not use.

---

## 2026-07-04 — 10:00 ET scheduled run time

**Decision.** The daily `paper run-all` fires at **10:00** local (intended ET),
30 minutes after the 09:30 open.

**Rationale.** Starting 30 minutes in sidesteps opening-auction noise and
first-print gaps; a monthly-signal strategy is insensitive to intraday timing, so
any post-open minute is acceptable; and a DAY order placed at 10:00 still has the
full session to fill. The digest runs at 16:45 (after marks settle) and the
weekly review at 17:00 Friday (after that day's digest). schtasks uses the host's
local clock, so the host is assumed to run on Eastern time.
