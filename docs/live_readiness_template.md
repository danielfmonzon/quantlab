# Live-Readiness Report — quantlab

> **Phase-8 gate.** This report must be completed, reviewed, and signed **before**
> live trading is even considered. Completing it does **not** enable live trading:
> quantlab is architecturally paper-only (the `ALPACA_BASE_URL` safety gate), and
> enabling live orders is out of scope. This template exists so the readiness
> decision is documented, evidence-based, and human-approved.
>
> Fill in every section. Leave no `______` blank. "N/A" must be justified.

- **Strategy / account:** `______`
- **Report author:** `______`
- **Report date:** `______`
- **quantlab version (`quantlab version`):** `______`
- **Paper track window covered:** `______` to `______`

---

## 1. Backtest summary

| Metric | Value | Notes |
|--------|-------|-------|
| Full-sample period | `______` | |
| CAGR | `______` | |
| Annualized volatility | `______` | |
| Sharpe ratio | `______` | |
| Max drawdown | `______` | vs 25% kill policy |
| Annual turnover | `______` | |
| Cost assumption (bps) | `______` | |

- Command(s) used: `______`
- Parameters are literature-fixed (never tuned): ☐ confirmed

## 2. Out-of-sample / walk-forward results

| Fold | Period | Sharpe | Max DD | Return | Notes |
|------|--------|--------|--------|--------|-------|
| 1 | `______` | `______` | `______` | `______` | |
| 2 | `______` | `______` | `______` | `______` | |
| … | | | | | |

- Walk-forward degradation vs full-sample: `______`
- Parameter-perturbation stability (Sharpe range across ± perturbations): `______`
- Command: `quantlab validate-strategy --strategy ______`

## 3. Paper-trading results

| Metric | Value |
|--------|-------|
| Paper days elapsed (target ≥ 90) | `______` |
| Cumulative paper return | `______` |
| Cumulative **shadow** return | `______` |
| **Cumulative paper-vs-shadow divergence (bps)** | `______` |
| Expected dividend drag over window | `______` |
| Weeks TRACKING / DIVERGING | `______` / `______` |

**Operational statistics**

| Item | Value |
|------|-------|
| Runs attempted | `______` |
| Runs completed | `______` |
| Runs aborted (by stage) | `______` |
| Alerts by level (INFO / WARNING / CRITICAL) | `______` |
| HALT events (auto-cleared) | `______` |
| KILL events (manual reset) | `______` |

- Divergence explained (dividends, timing) vs unexplained: `______`
- Source: `reports/weekly/week_*.md`, `reports/paper/run_*.json`,
  `reports/alerts/alerts.jsonl`.

## 4. Known risks

List each known risk and its mitigation.

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `______` | `______` | `______` | `______` |
| `______` | `______` | `______` | `______` |

## 5. Worst-case scenarios (bootstrap tails)

From the stationary block bootstrap (`quantlab validate-strategy`):

| Quantity | Value |
|----------|-------|
| Bootstrap resamples | `______` |
| 5th-percentile annual return | `______` |
| 95th-percentile max drawdown | `______` |
| P(drawdown worse than −30%) | `______` |
| P(drawdown worse than −25% kill) | `______` |

- Interpretation vs the 25% kill policy: `______`

## 6. Maximum capital at risk

| Item | Value |
|------|-------|
| Proposed initial capital | `$______` |
| Max single-position exposure (policy 100%) | `$______` |
| Max modeled daily loss (3% HALT) | `$______` |
| Max modeled drawdown before KILL (25%) | `$______` |
| Capital the operator can afford to lose entirely | `$______` |

- ☐ The proposed capital is money the operator can afford to lose in full.

## 7. Broker / API failure plan

| Failure mode | Detection | Response |
|--------------|-----------|----------|
| Alpaca API down at run time | run aborts at account stage; alert | `______` |
| Data feed stale | health preflight FREEZE; run aborts | `______` |
| Partial / rejected orders | order status in run report | `______` |
| Duplicate submission | idempotent client order IDs | `______` |
| Scheduler / host down | missing digest; converge-to-target recovers next run | `______` |
| Credentials expired | account stage failure; alert | `______` |

## 8. Kill-switch test results

**Static verification**

- ☐ `max_daily_loss < max_weekly_loss < max_drawdown_kill` enforced on load.
- ☐ Unit tests for HALT (auto-clear) and KILL (manual-reset, persistent) pass.
- ☐ Per-account state isolation verified (a KILL in one account does not affect
  the other).

**REQUIRED live-fire drill.** Manually exercise the kill switch end-to-end:

1. Set a halted `RiskState` for one account
   (`data/risk_state_{label}.json`, `halted=true`).
2. Trigger / wait for the next scheduled `paper run-all` (or run `paper run
   --strategy {label} --submit`).
3. Verify the run **aborts at the risk-state stage before any broker call** and
   emits an alert.
4. Confirm the other account is unaffected.
5. Reset with `quantlab risk reset --strategy {label} --confirm YES` and verify
   the next run proceeds normally.

| Drill field | Value |
|-------------|-------|
| Drill date | `______` |
| Account exercised | `______` |
| Run aborted at risk stage? | `______` |
| Alert emitted (level/channel)? | `______` |
| Other account unaffected? | `______` |
| Reset succeeded / next run normal? | `______` |
| Outcome (PASS / FAIL) | `______` |

## 9. Monitoring plan

| Question | Answer |
|----------|--------|
| Who watches alerts, and how (console/file/email)? | `______` |
| Response-time expectation for a CRITICAL alert | `______` |
| Daily check: digest reviewed by whom, when? | `______` |
| Weekly check: readiness ledger reviewed by whom? | `______` |
| Escalation path | `______` |
| Where logs/reports are archived | `______` |

## 10. Tax and recordkeeping considerations

> **Not tax advice.** These are **questions to raise with a qualified tax
> professional**, not guidance. Consult a professional before trading live.

- ☐ **Consult a tax professional** about the items below.
- Wash-sale rule: how do rebalances that realize losses and re-enter within 30
  days interact with the wash-sale rule? (Ask a professional.) `______`
- Short-term vs long-term gains: monthly rebalancing generates short-term gains —
  what is the tax treatment and rate? (Ask a professional.) `______`
- Recordkeeping: are all fills, costs, and rebalances retained for tax reporting?
  Where? `______`
- Account type / entity considerations: `______`

## 11. Final checklist

- ☐ ≥ 90 clean paper-trading days completed.
- ☐ No unresolved KILL/HALT; no DIVERGING weeks in the final window.
- ☐ Backtest, walk-forward, and bootstrap sections complete.
- ☐ Worst-case tails reconciled against the 25% kill policy.
- ☐ Broker/API failure plan documented.
- ☐ Live-fire kill-switch drill PASSED (Section 8).
- ☐ Monitoring plan staffed.
- ☐ Tax professional consulted (Section 10).
- ☐ Maximum capital at risk is affordable to lose in full.

## 12. Mandatory risk statement

> **Live trading can lose money, including the total loss of the capital
> committed.** Paper and backtest results do not predict live results and omit
> slippage, partial fills, liquidity constraints, dividend crediting, and timing
> effects. There is no guarantee of profit. Proceeding is done knowingly and at
> the operator's own risk.

## 13. Approval

> Approval is only valid when it names a **specific dollar amount** of initial
> capital. An open-ended or unspecified amount is **not** an approval.

```
Approved for live trading by: ______________________

date: ______________________

initial capital: $______________________
```

Approval **must name a specific dollar amount**; without one, this report does
not authorize anything.
