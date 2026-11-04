# Crypto backtests at the measured cost

Report-only, 2026-11-04. Base: `main` at f14dc03. No strategy, risk file, broker code, task, sanitizer pattern or default cost changed; costs are arguments in `docs/research/crypto_cost_rerun_2026-11.py`, which computes the figures here. Numbers only. The Quant Lead rules on what they mean.

## Summary

| Measure | crypto_trend | crypto_voltarget |
|---|--:|--:|
| Annualized return at 5.0 → 24.1 → 30.0 bps | 70.68% → 70.29% → 70.17% | 25.06% → 24.65% → 24.52% |
| Sharpe at the same costs | 1.221 → 1.216 → 1.215 | 0.983 → 0.970 → 0.966 |
| Bootstrap P(drawdown worse than −25%), 5.0 → 24.1 bps | 100.0% → 100.0% | 97.9% → 98.3% |
| Bootstrap P(drawdown worse than −50%), 5.0 → 24.1 bps | 91.5% → 91.6% | 31.7% → 32.4% |

Annual turnover of crypto_voltarget is **10.43x live** against **1.68x in the backtest**. At 24.1 bps the difference is **2.11% of equity a year** (range across the measurement choices in section 4: 2.05% to 2.33%). The cost grid does not capture this difference, because each run charges cost on the backtest's own turnover.

The tables use local prices ending 2026-09-09, which is stale. Section 6 gives the effect.

## Where the record differs from the brief

These change how the numbers below read, so they come first.

1. **The recorded crypto backtests ran at 25.0 bps, not 5.0.** `crypto-backtest` defaults to 25 (`src/quantlab/cli.py`), and all three 2026-07-11 `crypto_compare` records and both 2026-07-11 crypto validation records carry `cost_bps: 25.0`. The 5.0 is the shadow's modeled rate (`_DEFAULT_COST_BPS`, `src/quantlab/reporting/shadow.py:57`) and the default of `run_backtest` and `validate-strategy`. The decisions entry of 2026-10-31 states "the backtest's 5.0". The 5.0 runs below were run as the brief asks; they have no prior crypto record to match.
2. **The 25% kill threshold is the equity limit.** `config/risk.yaml` has `max_drawdown_kill: 0.25`; `config/crypto_risk.yaml`, which the crypto accounts run under, has 0.50. The dualmom entry's figure was the probability of a drawdown worse than −30%. Section 5 reports all three thresholds.
3. **`crypto-backtest` with its default overlay loads the equity limits.** It calls `load_risk_limits()`, which reads `config/risk.yaml`, so those recorded runs kill at 25%: average exposure over the window was 1.6% (trend) and 4.8% (voltarget). The main tables here are ungated, matching the recorded `--no-risk` run and the bootstrap. Appendix A gives the overlay at the crypto limits.
4. **Local paper reports stop at 2026-09-09.** Section 4 uses the committed snapshot on `main`, `frontend/public/snapshot/api-runs--label-crypto_voltarget.json`, which runs to 2026-10-30.

## 1. Baseline: does the instrument reproduce?

**At 5.0 bps for the crypto strategies, no prior figure exists in `docs/`.** No crypto backtest or bootstrap result appears there at any cost. The nearest is the 2026-10-31 entry's "~0.6% charged", which is a rough estimate, not a backtest output.

Two tests stand in, each re-run at the record's own cost and end date.

**The bootstrap figure on record in `docs/`, at 5.0 bps.** `docs/decisions.md`, entry 2026-07-07, and `README.md` give dualmom a Sharpe of ~0.60 and a 72.2% probability of a drawdown worse than −30%. The re-run matches exactly: 72.2%, median Sharpe 0.6063 (record 0.6063), 5913 returns, ending 2026-07-07.

**The crypto records, at 25.0 bps, ending 2026-07-11** (`reports/backtests/crypto_compare_20260711T231931Z.json` and `crypto_compare_20260711T231901Z.json`, local and gitignored):

| Run | Strategy | Metric | 2026-07-11 record | Re-run |
|---|---|---|--:|--:|
| Ungated | crypto_trend | Ann. return | 71.4768% | 71.4768% |
| Ungated | crypto_trend | Ann. vol | 57.4776% | 57.4776% |
| Ungated | crypto_trend | Sharpe | 1.2232 | 1.2232 |
| Ungated | crypto_trend | Max DD | -72.9779% | -72.9779% |
| Ungated | crypto_trend | Turnover (engine) | 1.2388x | 1.2388x |
| Ungated | crypto_voltarget | Ann. return | 23.4874% | 23.4441% |
| Ungated | crypto_voltarget | Ann. vol | 27.0073% | 27.0076% |
| Ungated | crypto_voltarget | Sharpe | 0.9343 | 0.9330 |
| Ungated | crypto_voltarget | Max DD | -52.3729% | -52.3729% |
| Ungated | crypto_voltarget | Turnover (engine) | 1.8054x | 1.8054x |
| Overlay (`risk.yaml`) | crypto_trend | Ann. return | 0.6549% | 0.6549% |
| Overlay (`risk.yaml`) | crypto_trend | Ann. vol | 8.6225% | 8.6225% |
| Overlay (`risk.yaml`) | crypto_trend | Sharpe | 0.1167 | 0.1167 |
| Overlay (`risk.yaml`) | crypto_trend | Max DD | -26.1474% | -26.1474% |
| Overlay (`risk.yaml`) | crypto_trend | Turnover (engine) | 0.8259x | 0.8259x |
| Overlay (`risk.yaml`) | crypto_voltarget | Ann. return | 5.9292% | 5.9292% |
| Overlay (`risk.yaml`) | crypto_voltarget | Ann. vol | 10.5612% | 10.5612% |
| Overlay (`risk.yaml`) | crypto_voltarget | Sharpe | 0.6439 | 0.6439 |
| Overlay (`risk.yaml`) | crypto_voltarget | Max DD | -28.9614% | -28.9614% |
| Overlay (`risk.yaml`) | crypto_voltarget | Turnover (engine) | 1.2085x | 1.2085x |

**The bootstrap records, at 25.0 bps** (`reports/validation/crypto_*_20260711*.json`, local and gitignored):

| Strategy | Metric | 2026-07-11 record | Re-run |
|---|---|--:|--:|
| crypto_trend | Returns sampled | 3844 | 3844 |
| crypto_trend | P(DD worse than −30%) | 100.0% | 100.0% |
| crypto_trend | Median max DD | -65.00% | -65.00% |
| crypto_trend | Median CAGR | 62.24% | 62.24% |
| crypto_trend | Median Sharpe | 1.1562 | 1.1562 |
| crypto_voltarget | Returns sampled | 3844 | 3844 |
| crypto_voltarget | P(DD worse than −30%) | 92.9% | 92.9% |
| crypto_voltarget | Median max DD | -45.45% | -45.45% |
| crypto_voltarget | Median CAGR | 26.37% | 26.36% |
| crypto_voltarget | Median Sharpe | 1.0052 | 1.0039 |

**One difference remains.** Ungated crypto_voltarget differs by −0.04 points of annual return and −0.0013 of Sharpe, and its bootstrap medians differ by a similar small amount. Across 117 months only one differs, July 2026, the record's final month (6.04% recorded, 5.68% re-run). This is the only re-run holding BTC on the final bar (weight 0.61); the three that match exactly were flat on it. That fits the 2026-07-11 bar having been revised by a later overlapping ingest, but the original bar was not kept, so this is not proven. All other backtest figures match to the digits shown.

## 2–3. Results by strategy and cost

Local store, ungated, identical window for all rows: 2016-11-01 to 2026-09-09, 3600 daily bars, 365-day annualization. Annualized return is CAGR. Trades are days with non-zero turnover; the small extra trades in crypto_trend at higher cost are residual weight from the engine's cost handling, so the count at or above the live planner's 1% minimum is shown in brackets.

| Strategy | Cost (bps) | Trades (≥1% of equity) | Turnover: traded / avg equity / yr | Turnover: engine Σ\|Δw\| / yr | Ann. return | Ann. vol | Sharpe | Max DD |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| crypto_trend | 5.0 | 21 (13) | 0.79x | 1.32x | 70.68% | 57.02% | 1.221 | -72.85% |
| crypto_trend | 24.1 | 25 (13) | 0.79x | 1.32x | 70.29% | 57.03% | 1.216 | -72.97% |
| crypto_trend | 30.0 | 25 (13) | 0.79x | 1.32x | 70.17% | 57.03% | 1.215 | -73.01% |
| crypto_voltarget | 5.0 | 119 (110) | 1.68x | 1.80x | 25.06% | 26.95% | 0.983 | -52.21% |
| crypto_voltarget | 24.1 | 119 (110) | 1.68x | 1.80x | 24.65% | 26.95% | 0.970 | -52.37% |
| crypto_voltarget | 30.0 | 119 (110) | 1.68x | 1.80x | 24.52% | 26.96% | 0.966 | -52.41% |

The turnover columns differ because the engine sums daily weight changes, while the brief's formula weights each trade by its dollar size against average equity over the window. With equity compounding, early trades count for less. Section 4 uses the brief's formula, with the engine's beside it.

## 4. Turnover gap, crypto_voltarget

Live: 44 orders and $331,007.71 requested over 100 days (2026-07-22 to 2026-10-30), against average equity of $115,853.55 from 89 run marks.

| Comparison | Live | Backtest | Difference | Extra cost at 24.1 bps (% of equity / yr) |
|---|--:|--:|--:|--:|
| Traded / avg equity / yr, against full backtest (headline) | 10.43x | 1.68x | 8.75x | 2.11% |
| Sum of daily plan turnover, against engine sum of weight changes | 10.29x | 1.80x | 8.49x | 2.05% |
| Same dates in the backtest (3 rebalances, fresh prices) | 10.43x | 1.16x | 9.27x | 2.23% |
| Live excluding the 8 aborted nights, against full backtest | 11.34x | 1.68x | 9.66x | 2.33% |

At 24.1 bps, the headline turnovers imply fees of 2.51% of equity a year live and 0.40% in the backtest. This is commission only, and it is simple arithmetic rather than a simulated run.

Limits of the live figure:

- **Window:** 100 days, annualized, against a backtest of 9.9 years. BTC volatility over those days is not adjusted for. The snapshot ends 2026-10-30.
- **Notional:** requested, not filled, because the snapshot carries fills for only 2 orders. All 55 orders since account creation total $425,318.11 requested against the $424,092.42 traded in the 2026-10-31 entry, a 0.29% difference, so this is not adjusted.
- **Gaps inside the window:** the 8 aborted nights (2026-10-15 to 10-22) placed no orders and their non-positive equity is excluded from the average. The 2026-08-18 to 08-21 silence also placed no orders. Only the last table row removes any days.
- **Reconciliation:** from account creation the same calculation gives 12.51x, in line with the entry's "roughly twelve times". The 10.43x here starts later, at the clock start.

## 5. Bootstrap drawdown check

Same instrument as `validate-strategy`: stationary block bootstrap, 1,000 samples, mean block 20 days, seed 42, ungated, 3904 daily returns from 2016-01-02 on the local store. That sample includes the pre-warmup period, as the recorded runs did. The function reports only −30%; the script replays its random stream for the other thresholds and asserts equality at −30%.

| Strategy | Threshold | 5.0 bps | 24.1 bps | 30.0 bps |
|---|---|--:|--:|--:|
| crypto_trend | Worse than −25% (brief) | 100.0% | 100.0% | 100.0% |
| crypto_trend | Worse than −30% (dualmom entry) | 100.0% | 100.0% | 100.0% |
| crypto_trend | Worse than −50% (`crypto_risk.yaml` kill) | 91.5% | 91.6% | 91.7% |
| crypto_voltarget | Worse than −25% (brief) | 97.9% | 98.3% | 98.3% |
| crypto_voltarget | Worse than −30% (dualmom entry) | 91.2% | 91.7% | 92.0% |
| crypto_voltarget | Worse than −50% (`crypto_risk.yaml` kill) | 31.7% | 32.4% | 32.5% |

Median simulated max drawdown at 5.0 → 24.1 bps: crypto_trend -64.86% → -65.02%; crypto_voltarget -44.82% → -44.94%.

These runs charge cost on the backtest's turnover, so they do not reflect the live turnover in section 4.

## 6. Price data

**The local store is stale.** `data/eod/BTCUSD.parquet` ends **2026-09-09** and starts 2016-01-01 (3905 bars), frozen at the workstation's last sync, 55 days short of the last complete day at this writing (2026-11-03). Its final bar is partial: volume 633 against a median of 6,045 over the prior 30 days. The backtest treats it as a full day.

**Does it matter?** To measure this, the script copied the local file to a scratch store and added current public Coinbase candles through 2026-11-03, the same source the ingest uses. `data/` was not modified. This scratch data did not go through the repo's validation step.

| Strategy (24.1 bps) | Metric | To 2026-09-09 (local) | To 2026-11-03 (fresh) |
|---|---|--:|--:|
| crypto_trend | Bars | 3600 | 3655 |
| crypto_trend | Ann. return | 70.29% | 68.56% |
| crypto_trend | Ann. vol | 57.03% | 56.76% |
| crypto_trend | Sharpe | 1.216 | 1.201 |
| crypto_trend | Max DD | -72.97% | -72.97% |
| crypto_trend | Turnover (traded / avg equity / yr) | 0.79x | 0.76x |
| crypto_trend | P(DD worse than −25%) | 100.0% | 100.0% |
| crypto_trend | P(DD worse than −50%) | 91.6% | 93.1% |
| crypto_voltarget | Bars | 3600 | 3655 |
| crypto_voltarget | Ann. return | 24.65% | 24.03% |
| crypto_voltarget | Ann. vol | 26.95% | 26.81% |
| crypto_voltarget | Sharpe | 0.970 | 0.955 |
| crypto_voltarget | Max DD | -52.37% | -52.37% |
| crypto_voltarget | Turnover (traded / avg equity / yr) | 1.68x | 1.68x |
| crypto_voltarget | P(DD worse than −25%) | 98.3% | 98.5% |
| crypto_voltarget | P(DD worse than −50%) | 32.4% | 32.9% |

- **Return levels move:** at 24.1 bps, crypto_trend by -1.73 points and crypto_voltarget by -0.62 points.
- **The cost effect barely moves:** going from 5.0 to 24.1 bps costs crypto_trend 0.39 points on the local store and 0.38 on the fresh one, and crypto_voltarget 0.41 and 0.41.
- **Live turnover is unaffected:** it comes from run reports, not this store. The only figure in section 4 that needs the fresh prices is the same-dates row.

## Appendix A: overlay at the crypto limits

Local store, `config/crypto_risk.yaml` (50% kill). A kill holds cash for the rest of the run, so the years after the kill date are flat in these figures.

| Strategy | Cost (bps) | Trades (≥1% of equity) | Turnover: traded / avg equity / yr | Ann. return | Ann. vol | Sharpe | Max DD | Kill date |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| crypto_trend | 5.0 | 11 (6) | 0.53x | 28.66% | 31.83% | 0.947 | -50.05% | 2018-02-03 |
| crypto_trend | 24.1 | 12 (6) | 0.53x | 28.53% | 31.83% | 0.944 | -50.29% | 2018-02-03 |
| crypto_trend | 30.0 | 12 (6) | 0.53x | 28.49% | 31.82% | 0.943 | -50.36% | 2018-02-03 |
| crypto_voltarget | 5.0 | 26 (25) | 0.56x | 5.66% | 14.61% | 0.484 | -51.71% | 2018-11-25 |
| crypto_voltarget | 24.1 | 26 (25) | 0.56x | 5.56% | 14.60% | 0.477 | -51.86% | 2018-11-25 |
| crypto_voltarget | 30.0 | 26 (25) | 0.56x | 5.53% | 14.60% | 0.475 | -51.91% | 2018-11-25 |

## Reproducing

`uv run python docs/research/crypto_cost_rerun_2026-11.py --out results.json --fresh-eod-dir <empty scratch dir>`

The script needs the local `data/eod` store and the local `reports/` records named above. The fresh-store figures will change as new candles arrive.
