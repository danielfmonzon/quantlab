# Decision log

Major design decisions made during the quantlab build, with rationale. Each
entry is dated to the build phase in which the decision was made; the log was
compiled on 2026-07-10 (v1.0.0). Newest entries first.

---

## 2026-07-22 — Scheduler catch-up, paired with a 15:30 ET submit cutoff

**Decision.** Enable `StartWhenAvailable` (missed-start catch-up) on the
scheduled tasks, and pair it with a **hard 15:30 ET cutoff** on any *submitting*
equity paper run. A run invoked with `--submit` after 15:30 ET on a trading day
aborts **before any broker call**, emitting a WARNING alert. Dry runs are
unaffected; crypto is unaffected.

**Rationale.** Two equity trading days were lost in two weeks because the host
was off at 10:00 and `schtasks` simply skipped the run — a silent gap in the
track record that the 90-day readiness gate depends on. Catch-up is the right
fix because **converge-to-target** makes a late run safe by construction: the
runner pursues the current target rather than replaying a missed rebalance, so a
recovered run reaches the same allocation a punctual one would.

The cutoff exists because that argument stops holding near the close. A signal
intended for 10:00 fired at 15:55 converges into the closing auction, taking the
day's full intraday move as slippage against a target chosen from the prior
session's data — and the shadow, which models a single daily mark, would read the
difference as tracking error. 15:30 leaves 30 minutes of liquid session for a
DAY order to fill while keeping the run clear of the close. A skipped day is a
visible gap in the ledger; a late near-close fill is invisible contamination, and
between the two the visible failure is strictly preferable.

Chosen over the alternative of "machine-on discipline" — an operational
convention that the host stays awake at 10:00 — because that is an unenforceable
promise about human behaviour guarding an automated track record, and it had
already failed twice.

---

## 2026-07-22 — The test suite polluted the production alert log

**Incident.** `pytest` wrote **49 fixture alerts** into the production
`reports/alerts/alerts.jsonl` across 16 bursts between `2026-07-22T17:19:48Z`
and `2026-07-22T22:13:56Z` — one burst per test invocation. The pollution
surfaced in that evening's weekly review, where `trend` reported
`CRITICAL=7, INFO=21, WARNING=14` for a week in which it had aborted no runs at
all; the `$200,000.00 notional` figure repeated 21 times is a fixture constant.

**Cause.** `FileChannel.__init__` took `path: Path = ALERTS_JSONL`. A default
argument binds **at import time**, so monkeypatching the module constant could
never redirect it, and any test reaching real `dispatch` wrote to the live log.

**Decision.** Three changes, and one deliberate non-change:

* `FileChannel` resolves its path at **send** time, so the constant is patchable.
* An **autouse** `isolate_alert_log` fixture in `tests/conftest.py` redirects
  every test's alert output to `tmp_path`. It also strips the five SMTP env vars
  — a developer with a populated `.env` exported into their shell would
  otherwise have had the suite send **real alert emails**.
* A regression test asserts the production log's size and mtime are unchanged
  across a real `dispatch`, reading the true path from `PROJECT_ROOT` rather than
  the redirected constant so it fails if the redirect ever breaks.
* **The polluted entries are NOT deleted.** A single structured annotation record
  (`source: ops.annotation`) was appended instead, naming the count, the burst
  timestamps, the cause, and the remediation.

**Rationale.** An append-only operational log is evidence. Editing it to remove
inconvenient entries destroys the audit trail and sets a precedent that the log
may be rewritten when it embarrasses us — exactly the property that makes it
worthless for a live-readiness decision later. Annotating costs one line and
leaves both the contamination and its explanation permanently inspectable.

---

## 2026-07-22 — Alert attribution by structured field, not substring

**Decision.** Every account-scoped alert carries a structured `strategy` field,
and `_alerts_in_window` attributes on that field. Legacy records written before
the field existed fall back to a **word-boundary** title match.

**Rationale.** Attribution was `label.lower() in title.lower()`. `trend` is a
substring of `crypto_trend` and `voltarget` of `crypto_voltarget`, so each equity
account silently absorbed its crypto namesake's alerts — `trend`'s `WARNING=14`
was 7 of its own plus 7 belonging to `crypto_trend`. The defect was invisible
while the weekly review covered only the equity pair, and became wrong the moment
both namesake pairs appeared in one report. A structured field is exact and
cannot be defeated by a future label that happens to contain an existing one. The
word-boundary fallback is correct for the legacy rows specifically because `_` is
a regex word character, so `trend` does not match `crypto_trend`.

---

## 2026-07-22 — Weekly review covers every asset class

**Decision.** `build_weekly_review` iterates **`APPROVED_STRATEGIES`** rather than
`EQUITY_APPROVED_STRATEGIES`, so the weekly paper-vs-shadow review renders a
section for all four approved accounts (`voltarget`, `trend`, `crypto_trend`,
`crypto_voltarget`). Three things vary by asset class:

* **Window length.** An equity week is 5 sessions; a crypto week is **7** UTC
  days, because the crypto accounts trade and snapshot every calendar day.
* **Structural-drift note.** Equity sections keep the dividend-drag note. Crypto
  sections carry a crypto-specific caveat instead: crypto pays no dividends, so
  there is no drag — the structural gap is *timing*, since BTC trades 24/7 while
  both the paper equity snapshot and the shadow's bars are once-daily, so
  weekend and overnight moves land entirely between two marks.
* **Snapshot collapse.** Crypto history is collapsed to the **last snapshot per
  UTC day** before any return is computed (`_last_snapshot_per_day`).

The DIVERGING threshold stays a single portfolio-wide policy number (50 bps)
applied to every account's **weekly aggregate**, crypto included.

**Rationale.** Excluding crypto from the only report that compares paper equity
against expectation left half the paper roster untracked — the crypto accounts
were being traded daily with no divergence gate at all. The three per-class
adjustments are what make the comparison honest rather than merely present: a
5-snapshot window on a 7-day market would label a 5-day span a "week"; the
dividend note is simply false for BTC; and the once-daily collapse is required
because the pre-fix double-runs (see the entry below) left two marks on some
days, which would have compressed a 7-snapshot window into roughly three days
and compared that against a threshold calibrated for a full week.

The equity path is deliberately untouched — same 5-snapshot window, same
dividend note, same numbers — so this change cannot perturb the equity track
record that the readiness gate depends on.

---

## 2026-07-22 — Crypto track-record clock restarts (Quant Lead ruling)

**Decision.** The **crypto** live-readiness clock **restarts at 2026-07-22**.
The readiness ledger therefore carries one independent 90-day clock per asset
class: **`us_equity` from 2026-07-09**, **`crypto` from 2026-07-22**. Crypto
paper history from 2026-07-12 to 2026-07-21 is **retained as diagnostic data
only** — it is still on disk, still rendered in the weekly return series, but it
does **not** count toward the 90-day gate. **Equity records are unaffected** by
this ruling; the equity clock keeps its original 2026-07-09 start.

**Rationale.** The pre-fix crypto history is contaminated by the double-runs
described in the entry below. Those leaked 10:00 ET runs were **not** dry runs —
they submitted real paper orders (e.g. `crypto_voltarget` submitted an order on
both its 00:30 UTC and its 14:00 UTC run on 2026-07-21) — so the affected days
carry rebalances at a second daily timestamp that the once-daily shadow does not
model. A track record whose turnover and mark timing do not match the policy
being evaluated cannot support a live-readiness decision, and the honest remedy
for a contaminated window is to restart the clock rather than to quietly average
the contamination away. Retaining rather than deleting the old history keeps the
contamination auditable.

Implementation: `_TRACK_START_FLOOR` in `reporting/weekly.py` floors the crypto
clock at 2026-07-22. The floored clock renders a `start_note` recording that the
clock was restarted by ruling and that the earlier history does not count, so the
restart is visible in every weekly report rather than buried in code.

---

## 2026-07-22 — Equity scheduled task leaked into the crypto accounts

**Decision.** The `quantlab-paper-run` scheduled task runs
`paper run-all **--asset-class us_equity** --submit`. The flag is load-bearing
and must never be dropped.

**Diagnosis.** `paper run-all` defaults to `--asset-class all`, which iterates
every entry in `APPROVED_STRATEGIES`. When the crypto sleeve added
`crypto_trend` and `crypto_voltarget` to that tuple, the pre-existing 10:00 ET
equity task silently widened to cover them as well — while the separate
`quantlab-crypto-paper-run` task at 20:30 local was already running them. The
crypto accounts were therefore run **twice a day** on weekdays. The evidence is
in the artifacts: `data/equity_history_crypto_*.parquet` carries two snapshots on
each affected weekday (one at ~00:30/05:00 UTC from the crypto task, one at
14:00 UTC = 10:00 ET from the equity task), and `reports/paper/` holds a matching
pair of non-dry-run reports per day, several with orders submitted on both.

**Rationale.** The default of `all` is right for an interactive
`paper run-all` — an operator asking to run everything means everything. The
defect was that a *scheduled* task inherited a default that changed meaning when
the roster grew. Pinning the asset class in the task definition makes each task's
scope explicit and immune to future roster additions; the crypto sleeve's own
task is likewise pinned to `--asset-class crypto`. The load-bearing nature of the
flag is documented in `scheduling/tasks.py` so it survives the next edit.

---

## 2026-07-11 — Crypto sleeve: strategies, accounts, and schedule

**Decision.** Add a crypto sleeve alongside the equity roster, kept structurally
separate at every layer rather than merged into the equity path:

* **Strategies.** `CryptoTrendBTC` (Faber 10-month SMA on BTC-USD, **no safe
  asset** — below the SMA is 100% cash) and `CryptoVolTargetBTC` (20% target vol,
  20-day realized window, weight capped at 1.0). Both annualize on a **365-day**
  grid. Parameters are literature/convention-fixed under the iron rule.
* **Accounts.** Two further dedicated, fully isolated Alpaca paper accounts,
  `crypto_trend` and `crypto_voltarget`, each with its own key pair and its own
  `equity_history_{label}.parquet` / `risk_state_{label}.json` namespace. Both
  were appended to `APPROVED_STRATEGIES` after passing the walk-forward +
  perturbation + bootstrap battery on 2026-07-11.
* **Calendar and data.** A `CryptoCalendar` emitting every UTC day (not NYSE
  sessions), Coinbase as the crypto price source, and a separate
  `config/crypto_universe.yaml` so crypto symbols can never leak into the equity
  ingest/validate/paper symbol set.
* **Risk.** A separate `config/crypto_risk.yaml` calibrated to crypto volatility
  (15% daily HALT, 25% weekly HALT, 50% drawdown KILL) — the equity
  `config/risk.yaml` is left untouched and the runner selects the file by the
  account's asset class.
* **Schedule.** A separate `quantlab-crypto-paper-run` task, `/SC DAILY` (all 7
  days) at 20:30 local, distinct from the three equity task definitions.

**Rationale.** Crypto differs from the equity sleeve in the three things that
drive nearly all of this codebase's logic — the calendar (24/7 vs NYSE), the
volatility regime (hence the risk limits), and the data source. Sharing one code
path and branching internally on asset class would have put crypto-shaped edge
cases inside the equity trading path, which is the one path with a real track
record. Separate config files, a separate calendar, separate accounts, and a
separate scheduled task mean a crypto change cannot regress equities. The cost of
that separation is that shared reports must be taught about asset classes one at
a time — the asset-class leak and the weekly-coverage gap above are both
instances of exactly that cost.

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
