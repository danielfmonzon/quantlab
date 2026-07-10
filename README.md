# quantlab

quantlab is an algorithmic-trading **research and paper-trading** system for
systematic strategies over a fixed universe of liquid ETFs. It ingests and
validates end-of-day data, backtests literature-based strategies with a custom
daily engine, runs a report-only statistical validation battery, and operates a
risk-gated **paper** trading loop against Alpaca — with daily digests, a weekly
paper-vs-expectation review, and multi-channel alerting.

It is version **1.0.0**. Every generated report header embeds the version plus
the git short hash, so any artifact is traceable to the commit that produced it
(`quantlab version`).

## ⚠️ SAFETY — read this first

- **Research / paper-trading only.** quantlab does not place live orders. It
  trades exclusively against the Alpaca *paper* endpoint.
- **Live trading is architecturally disabled.** The config layer enforces a hard
  gate: `ALPACA_BASE_URL` must be the paper endpoint
  (`https://paper-api.alpaca.markets`). Any URL targeting the live host
  (`api.alpaca.markets` without the `paper-` prefix) raises `ConfigError` at load
  time and the program refuses to start. This gate applies to **every** account.
  Enabling live trading would require *deliberately removing that safety gate* —
  which is explicitly **out of scope** for this project (see
  [Path to live trading](#path-to-live-trading)).
- **Nothing here is financial advice.** No part of this project constitutes
  financial, investment, tax, or trading advice.
- **Paper results do not predict live results.** Simulated and paper fills omit
  real-world slippage, partial fills, liquidity, dividend crediting, and timing
  effects. Past and paper performance is not indicative of future results.
  **Live trading can lose money, including total loss of capital.**

## Setup

Requires Python >= 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create .venv and install all dependencies (incl. dev)
cp .env.example .env    # then fill in your API keys (never commit .env)
```

Non-secret configuration lives in `config/` (`settings.yaml`, `universe.yaml`,
`risk.yaml`); secret keys are read from the environment / `.env`. The universe is
12 liquid ETFs spanning US/international equities, REITs, Treasuries, credit,
commodities, gold, and a T-bill cash proxy (`config/universe.yaml`).

## Architecture overview

The code lives under `src/quantlab/`, one package per concern:

- **`data`** — EOD ingestion (Tiingo), a Parquet store with per-symbol metadata,
  a trading calendar, schema/quality validation, cross-vendor reconciliation
  against Alpaca IEX bars, and a freshness/health preflight.
- **`backtest`** — the price panel, shared signal helpers, the strategy interface
  and roster, performance metrics, and a custom daily backtest engine with
  one-session signal lag, weight drift, and a turnover cost model.
- **`risk`** — declarative `RiskLimits` (YAML-overridable), a `RiskEngine` that
  contains weights and evaluates HALT/KILL conditions, and a persistent,
  atomically-written kill-switch state.
- **`validation`** — a report-only statistical battery: walk-forward analysis,
  parameter perturbation, and a stationary block bootstrap for tail risk.
- **`broker`** — a thin, typed Alpaca *paper* trading client (account, positions,
  orders) with idempotent client order IDs.
- **`paper`** — the gated rebalance pipeline: an ordered, abort-on-first-failure
  runner (risk → ingest → validate → health → account → target → contain →
  evaluate → plan → submit → report) plus the converge-to-target rebalance
  planner. Dry-run by default.
- **`reporting`** — the daily multi-account digest, the shadow-return
  reconstruction, the weekly paper-vs-shadow review + readiness ledger, and
  multi-channel alerting (console + file always; email when SMTP is configured).
- **`scheduling`** — Windows Task Scheduler wiring for the three recurring tasks.

## Strategy roster

All strategy parameters are **fixed from the source literature** and never tuned
to the data (see [decisions](docs/decisions.md), the "iron rule"). Backtestable
strategies:

| Strategy    | Reference | Rule |
|-------------|-----------|------|
| `buyhold`   | baseline | Hold a single ETF at 100%. |
| `sixty40`   | baseline | Fixed 60% SPY / 40% IEF, re-normalized monthly. |
| `trend`     | Faber (2007), *A Quantitative Approach to Tactical Asset Allocation* | Hold SPY while its price is above its 10-month SMA (month-end), else the safe asset (IEF) or cash. |
| `dualmom`   | Antonacci (2014), *Dual Momentum Investing* | Relative momentum between SPY/EFA over 12 months, gated by absolute momentum; else IEF/cash. **Excluded from paper trading.** |
| `voltarget` | Volatility targeting (conventional) | Weight = min(1.0, 10% target vol / trailing 20-day realized vol); remainder in cash. |

**Approved for paper trading:** `voltarget` and `trend` only. **`dualmom` is
deliberately excluded**: in validation it showed a Sharpe of ~0.60 and a
bootstrap probability of a drawdown worse than −30% of **72.2%** — incompatible
with the 25% max-drawdown kill policy (a strategy expected to breach the kill
threshold most of the time is not a candidate for capital). The exclusion is a
risk decision, not a data-mining one; see [decisions](docs/decisions.md).

## Risk model

Limits are declared in `config/risk.yaml` and validated on load
(`risk/limits.py`). Loss/exposure fields are fractions in (0, 1] and must satisfy
`daily < weekly < kill`.

| Limit | Default | Meaning |
|-------|---------|---------|
| `max_position_weight` | 1.00 | Per-symbol cap (100%: tactical single-ETF positions are intended). |
| `max_gross_exposure` | 1.00 | Long-only, no leverage: `sum(weights) <= 1`. |
| `max_daily_loss` | 0.03 | 3% single-session loss → **HALT**. |
| `max_weekly_loss` | 0.08 | 8% rolling 5-session loss → **HALT**. |
| `max_drawdown_kill` | 0.25 | 25% peak-to-trough → **KILL** (manual reset). |
| `staleness_max_sessions` | 1 | Data older than this many sessions → **FREEZE** (health preflight aborts the run). |
| `weekly_divergence_alert_bps` | 50 | Weekly paper-vs-shadow gap beyond this flags **DIVERGING** (report-only). |

**Kill-switch semantics.** A **HALT** (daily or weekly loss) forces 100% cash and
auto-clears the next session once the condition passes — no human action needed.
A **KILL** (max-drawdown breach) sets `requires_manual_reset=True`, is persisted
atomically to disk, and survives process restarts until an operator explicitly
runs `quantlab risk reset`. Risk thresholds are **live-operations policy**, chosen
independently of any backtest result and never tuned to improve historical
returns (see [decisions](docs/decisions.md)).

**Per-account isolation.** Each approved strategy runs in its **own dedicated
Alpaca paper account** with fully isolated state:
`data/equity_history_{label}.parquet` and `data/risk_state_{label}.json`. A KILL
in one account can never halt another, and the paper runner reads/writes only its
own label's files.

## Operating runbook

**Scheduled tasks** (installed via `quantlab schedule install --confirm YES`;
times are the host's local clock, intended as US/Eastern):

| Task | When | Command |
|------|------|---------|
| `quantlab-paper-run` | Mon–Fri 10:00 | `paper run-all --submit` |
| `quantlab-digest` | Mon–Fri 16:45 | `digest` |
| `quantlab-weekly` | Fri 17:00 | `weekly` |

The paper run fires 30 minutes after the open (past the opening auction; a
monthly-signal strategy is insensitive to intraday timing). The digest runs after
the close once marks settle; the weekly review runs after Friday's digest.

**On a CRITICAL alert.** A CRITICAL alert means a KILL fired (max-drawdown breach)
or a run aborted at a safety-critical stage. (1) Do not intervene in the market —
the runner has already forced cash / stopped submitting. (2) Read the latest
`reports/paper/run_{label}_*.json` for the abort stage and reason. (3) Confirm the
`data/risk_state_{label}.json` state. (4) Only after understanding the cause,
clear a KILL with the reset procedure below. HALTs need no action — they
auto-clear.

**How to read the weekly review** (`reports/weekly/week_*.md`). Per account it
shows the paper week return vs the **shadow** return (what a paper account
*should* have earned), their **divergence in bps**, and a **TRACKING**
(|divergence| ≤ 50 bps) or **DIVERGING** verdict. Expect some structural drift:
paper equity is marked ~10:00 ET while the shadow is close-to-close, and Alpaca
paper does not credit dividends while the shadow uses dividend-adjusted returns —
so paper lags the shadow by roughly the portfolio's dividend yield over time.
That is **expected dividend drag**, annotated as such, not tracking error. The
**readiness ledger** tracks elapsed clean paper days against the 90-day gate and
lists blockers.

**Risk reset procedure** (clearing a halted/killed account):

```bash
quantlab risk show                                   # inspect limits + state
quantlab risk reset --strategy voltarget --confirm YES
```

The reset requires `--confirm YES`, targets exactly one account's kill-switch, and
prints what it cleared. Investigate the root cause *before* resetting a KILL.

## CLI reference

Run `uv run quantlab <command>`. Every command is one line below.

| Command | Purpose |
|---------|---------|
| `version` | Print the version + git short hash. |
| `ingest --start DATE [--symbols ...]` | Fetch EOD data from Tiingo into the store. |
| `validate [--symbols ...]` | Validate stored EOD data (schema + quality). |
| `reconcile [--symbols ...] [--days N] [--tolerance T]` | Cross-check stored data against Alpaca IEX bars. |
| `health` | Data-freshness / health preflight over stored symbols. |
| `backtest --strategy S [--symbol SPY] [--start DATE] [--cost-bps 5] [--benchmark SPY] [--risk]` | Run one strategy backtest. |
| `compare [--start DATE] [--cost-bps 5] [--risk]` | Compare all baseline + tactical strategies. |
| `validate-strategy --strategy S [--start DATE] [--cost-bps 5] [--seed 42]` | Report-only validation battery (walk-forward, perturbation, bootstrap). |
| `digest [--send-test-alert]` | Build + write the daily multi-account paper digest. |
| `weekly [--week-ending YYYY-MM-DD]` | Build + write the weekly paper-vs-shadow review. |
| `schedule install --confirm YES` \| `uninstall` \| `show` | Manage the three scheduled tasks. |
| `paper run --strategy S [--submit]` | Run the gated rebalance pipeline for one account (dry-run unless `--submit`). |
| `paper run-all [--submit]` | Run every approved strategy in its own account, in order. |
| `paper status [--strategy all\|voltarget\|trend]` | Per-account equity, positions, orders, risk state. |
| `risk show` | Print `RiskLimits` and each account's `RiskState`. |
| `risk reset --strategy S --confirm YES` | Clear a halted/killed account's kill-switch. |

## Running tests

```bash
uv run ruff check .            # lint (line length 100)
uv run mypy src/               # strict type check
uv run pytest -v               # tests with coverage
```

Network-touching tests are marked `live` and skip automatically when credentials
are absent, so the default suite performs no network I/O.

## Path to live trading

Live trading is **not enabled and not in scope.** The Phase-8 gate that would
have to be satisfied *before even considering* it is:

1. **≥ 90 clean paper-trading days** — tracked by the weekly readiness ledger,
   with no unresolved KILL/HALT, no DIVERGING weeks, and consistent run coverage.
2. **A completed live-readiness report** — the template in
   [`docs/live_readiness_template.md`](docs/live_readiness_template.md), including
   a live-fire kill-switch drill and a bootstrap worst-case analysis.
3. **Explicit, written human approval naming a specific dollar amount** of initial
   capital at risk.

Even with all three satisfied, enabling live orders would require **deliberately
removing the `ALPACA_BASE_URL` safety gate** in the config layer — a change this
project intentionally does not make. quantlab ships as a paper-only system by
design.

## Project layout

```
config/            settings.yaml, universe.yaml, risk.yaml
docs/              live_readiness_template.md, decisions.md
src/quantlab/      data, backtest, risk, validation, broker, paper, reporting, scheduling
tests/             unit + live-marked tests
data/ reports/     generated artifacts (gitignored)
notebooks/         exploratory notebooks
```
