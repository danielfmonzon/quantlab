/**
 * Fixture API responses, and the `mockApi` helper that installs them on `fetch`.
 *
 * Two complete sets: `populated` (shaped like the real 2026-07 artifacts) and
 * `empty` (what the API returns for a repo with no artifacts at all). Every screen
 * test runs against BOTH — an empty tree must produce explicit empty states, never
 * a blank panel or a crash.
 */

import { vi } from 'vitest'
import type {
  DecisionsResponse,
  DivergenceResponse,
  EquityResponse,
  IgnoredInputsResponse,
  OverviewResponse,
  RiskResponse,
  RunNarration,
  RunsResponse,
  TimelineResponse,
} from '../src/lib/api'

const today = new Date().toISOString().slice(0, 10)

export const overviewPopulated: OverviewResponse = {
  generated_at: `${today}T18:00:00Z`,
  week_ending: '2026-07-24',
  note: null,
  accounts: [
    {
      label: 'voltarget',
      asset_class: 'us_equity',
      latest_equity: 98821.82,
      latest_snapshot_at: '2026-07-24T14:00:07.519467',
      latest_snapshot_provenance: 'on_schedule',
      snapshot_count: 11,
      risk: { halted: false, reason: null, triggered_at: null, requires_manual_reset: false },
      validation_tier: 'Probable',
      validation_tier_rationale: 'Battery on record; day-90 gate NOT yet passed.',
      validation_tier_upgrade_condition:
        'Proven upon a clean day-90 readiness review for us_equity — no DIVERGING weeks, no KILL, projected ~2026-10-07.',
      clock: {
        asset_class: 'us_equity',
        paper_start_date: '2026-07-09',
        calendar_days_elapsed: 15,
        target_days: 90,
        pct_complete: 16.666,
        start_note: null,
        blockers: ['trend: DIVERGING week (-54 bps)'],
      },
    },
    {
      label: 'crypto_voltarget',
      asset_class: 'crypto',
      latest_equity: 99631.61,
      latest_snapshot_at: '2026-07-25T00:30:08.321565',
      latest_snapshot_provenance: 'catch_up',
      snapshot_count: 21,
      risk: {
        halted: true,
        reason: 'daily loss 16.2%',
        triggered_at: '2026-07-24T00:30:00Z',
        requires_manual_reset: true,
      },
      validation_tier: 'Probable',
      validation_tier_rationale: 'Battery on record; day-90 gate NOT yet passed.',
      validation_tier_upgrade_condition:
        'Proven upon a clean day-90 readiness review for crypto — projected ~2026-10-20.',
      clock: {
        asset_class: 'crypto',
        paper_start_date: '2026-07-22',
        calendar_days_elapsed: 2,
        target_days: 90,
        pct_complete: 2.222,
        start_note: 'clock restarted 2026-07-22 by ruling',
        blockers: [],
      },
    },
  ],
}

export const overviewEmpty: OverviewResponse = {
  generated_at: `${today}T18:00:00Z`,
  week_ending: null,
  note: 'no artifacts found; this is an empty-state response, not an error',
  accounts: [
    {
      label: 'voltarget',
      asset_class: 'us_equity',
      latest_equity: null,
      latest_snapshot_at: null,
      latest_snapshot_provenance: null,
      snapshot_count: 0,
      risk: { halted: false, reason: null, triggered_at: null, requires_manual_reset: false },
      validation_tier: 'Probable',
      validation_tier_rationale: 'Battery on record; day-90 gate NOT yet passed.',
      validation_tier_upgrade_condition: 'Proven upon a clean day-90 readiness review.',
      clock: null,
    },
  ],
}

export const runsPopulated: RunsResponse = {
  count: 2,
  label: null,
  note: null,
  runs: [
    {
      run_id: 'run_voltarget_20260724T140007Z',
      strategy: 'voltarget',
      timestamp: '2026-07-24T14:00:07.519467Z',
      dry_run: false,
      aborted: false,
      abort_stage: null,
      abort_reason: null,
      equity: 98821.82,
      target_weights: { SPY: 0.85715659109397 },
      no_trades: false,
      est_turnover: 0.0799,
      min_trade_frac: 0.01,
      stages: [
        { stage: 'risk_state', ok: true, detail: 'not halted' },
        { stage: 'submit', ok: true, detail: 'submitted 1 order(s)' },
      ],
      intents: [
        { symbol: 'SPY', side: 'sell', notional: 7897.07, current_w: 0.9371, target_w: 0.8572 },
      ],
      submitted_orders: [
        {
          symbol: 'SPY',
          side: 'sell',
          notional: 7897.07,
          status: 'filled',
          client_order_id: 'ql-voltarget-20260724-SPY-sell',
          submitted_at: '2026-07-24T14:00:08Z',
          was_duplicate: false,
        },
      ],
    },
    {
      run_id: 'run_trend_20260722T140028Z',
      strategy: 'trend',
      timestamp: '2026-07-22T14:00:28.578414Z',
      dry_run: true,
      aborted: true,
      abort_stage: 'health',
      abort_reason: 'FREEZE_STALE_DATA: SPY is 2 sessions stale',
      equity: null,
      target_weights: {},
      no_trades: false,
      est_turnover: null,
      min_trade_frac: null,
      stages: [{ stage: 'health', ok: false, detail: 'stale' }],
      intents: [],
      submitted_orders: [],
    },
  ],
}

export const runsEmpty: RunsResponse = {
  count: 0,
  label: null,
  runs: [],
  note: 'no artifacts found; this is an empty-state response, not an error',
}

export const narrationPopulated: RunNarration = {
  run_id: 'run_voltarget_20260724T140007Z',
  strategy: 'voltarget',
  narration:
    'Run run_voltarget_20260724T140007Z: account voltarget executed as a LIVE SUBMIT ' +
    'against the paper broker. Account equity was read as $98,821.82. That rule produced ' +
    'a target of SPY at 85.72%. Planned orders: SELL SPY for $7,897.07 notional moving ' +
    'weight from 93.71% to 85.72%. Estimated turnover for the plan was 0.0799 of equity.',
  rule_sentences: [
    'Rule: voltarget sizes exposure as its target volatility (10%) divided by trailing 20-day realized volatility.',
  ],
  counterfactuals: [
    'SPY: traded because drift was 7.99%, above the 1.00% minimum-trade band; had drift been at or below that band the runner would have left the position to drift untouched, placing no order.',
  ],
  facts: [
    { rendered: '$98,821.82', value: 98821.82, source: 'report.equity' },
    { rendered: '85.72%', value: 0.85715659109397, source: 'report.target_weights.SPY' },
    { rendered: '$7,897.07', value: 7897.07, source: 'report.plan.intents[0].notional' },
    { rendered: '93.71%', value: 0.9371, source: 'report.plan.intents[0].current_w' },
    { rendered: '0.0799', value: 0.0799, source: 'report.plan.est_turnover' },
    {
      rendered: '7.99%',
      value: 0.0799,
      source: 'derived.abs(report.plan.intents[0].target_w - report.plan.intents[0].current_w)',
    },
    { rendered: '1.00%', value: 0.01, source: 'report.plan.min_trade_frac' },
  ],
  disclaimer:
    "Generated from this run's structured fields and the strategy's pre-registered rule parameters only. It contains no market commentary.",
  available: true,
  note: null,
}

export const divergencePopulated: DivergenceResponse = {
  label: 'trend',
  note: null,
  weeks: [
    {
      week_ending: '2026-07-17',
      label: 'trend',
      asset_class: 'us_equity',
      paper_week_return: -0.004,
      shadow_week_return: -0.0038,
      divergence_bps: -2.0,
      cumulative_divergence_bps: -2.0,
      verdict: 'TRACKING',
      threshold_bps: 50,
      excluded_tail_days: [],
      window_start: '2026-07-13',
      window_end: '2026-07-17',
      structural_note: null,
    },
    {
      week_ending: '2026-07-24',
      label: 'trend',
      asset_class: 'us_equity',
      paper_week_return: -0.0173,
      shadow_week_return: -0.0167,
      divergence_bps: -6.06,
      cumulative_divergence_bps: 26.9,
      verdict: 'TRACKING',
      threshold_bps: 50,
      excluded_tail_days: ['2026-07-24'],
      window_start: '2026-07-16',
      window_end: '2026-07-23',
      structural_note:
        'Alpaca paper does not credit cash dividends while the shadow uses dividend-adjusted returns.',
    },
  ],
  corrections: [
    {
      week_ending: '2026-07-24',
      label: 'trend',
      published_divergence_bps: -54.33,
      published_verdict: 'DIVERGING',
      corrected_divergence_bps: -6.06,
      corrected_verdict: 'TRACKING',
      corrected_window: '2026-07-16 -> 2026-07-23',
      cause:
        'The 2026-07-24 snapshot was compared against a shadow with no 2026-07-24 session at all.',
      reference:
        'docs/decisions.md — 2026-07-25 — Week 2026-07-24 divergence diagnosis, and two re-rulings',
    },
  ],
}

export const divergenceEmpty: DivergenceResponse = {
  label: 'voltarget',
  weeks: [],
  corrections: [],
  note: 'no artifacts found; this is an empty-state response, not an error',
}

export const equityPopulated: EquityResponse = {
  label: 'crypto_voltarget',
  note: null,
  series: [
    {
      label: 'crypto_voltarget',
      asset_class: 'crypto',
      provenance_counts: { on_schedule: 1, catch_up: 1, leaked: 1 },
      points: [
        {
          timestamp: '2026-07-22T14:00:46',
          equity: 101519.84,
          provenance: 'leaked',
          provenance_rationale: 'A crypto mark produced by the 10:00 ET EQUITY task.',
        },
        {
          timestamp: '2026-07-23T00:30:09',
          equity: 101918.02,
          provenance: 'on_schedule',
          provenance_rationale: 'Mark landed within 30 minutes of the scheduled run time.',
        },
        {
          timestamp: '2026-07-24T05:43:03',
          equity: 100872.81,
          provenance: 'catch_up',
          provenance_rationale:
            'Mark landed well outside the scheduled window — a StartWhenAvailable catch-up run.',
        },
      ],
    },
  ],
}

export const equityEmpty: EquityResponse = {
  label: 'voltarget',
  series: [{ label: 'voltarget', asset_class: 'us_equity', points: [], provenance_counts: {} }],
  note: 'no artifacts found; this is an empty-state response, not an error',
}

export const riskPopulated: RiskResponse = {
  note: null,
  accounts: [
    {
      label: 'voltarget',
      asset_class: 'us_equity',
      limits: {
        max_position_weight: 1,
        max_gross_exposure: 1,
        max_daily_loss: 0.03,
        max_weekly_loss: 0.08,
        max_drawdown_kill: 0.25,
        staleness_max_sessions: 1,
        weekly_divergence_alert_bps: 50,
      },
      limits_source: 'risk.yaml',
      peak_equity: 100613.77,
      latest_equity: 98821.82,
      current_drawdown: -0.01781,
      drawdown_kill_limit: 0.25,
      drawdown_headroom: 0.23219,
      kill_switch: {
        halted: false,
        reason: null,
        triggered_at: null,
        requires_manual_reset: false,
      },
      note: null,
    },
    {
      label: 'crypto_voltarget',
      asset_class: 'crypto',
      limits: {
        max_position_weight: 1,
        max_gross_exposure: 1,
        max_daily_loss: 0.15,
        max_weekly_loss: 0.25,
        max_drawdown_kill: 0.5,
        staleness_max_sessions: 1,
        weekly_divergence_alert_bps: null,
      },
      limits_source: 'crypto_risk.yaml',
      peak_equity: 102465.73,
      latest_equity: 99631.61,
      current_drawdown: -0.4,
      drawdown_kill_limit: 0.5,
      drawdown_headroom: 0.1,
      kill_switch: {
        halted: true,
        reason: 'drawdown 40%',
        triggered_at: '2026-07-24T00:30:00Z',
        requires_manual_reset: true,
      },
      note: null,
    },
  ],
}

export const riskEmpty: RiskResponse = {
  note: null,
  accounts: [
    {
      label: 'voltarget',
      asset_class: 'us_equity',
      limits: {
        max_position_weight: null,
        max_gross_exposure: null,
        max_daily_loss: null,
        max_weekly_loss: null,
        max_drawdown_kill: null,
        staleness_max_sessions: null,
        weekly_divergence_alert_bps: null,
      },
      limits_source: 'risk.yaml (absent)',
      peak_equity: null,
      latest_equity: null,
      current_drawdown: null,
      drawdown_kill_limit: null,
      drawdown_headroom: null,
      kill_switch: {
        halted: false,
        reason: null,
        triggered_at: null,
        requires_manual_reset: false,
      },
      note: 'no equity history yet; drawdown and headroom are unknown',
    },
  ],
}

export const timelinePopulated: TimelineResponse = {
  count: 4,
  note: null,
  events: [
    {
      at: `${today}T14:00:08Z`,
      kind: 'order',
      label: 'voltarget',
      title: 'sell SPY $7,897.07',
      detail: 'status=filled run=run_voltarget_20260724T140007Z',
      level: null,
    },
    {
      at: `${today}T13:00:00Z`,
      kind: 'alert',
      label: 'trend',
      title: 'weekly review: trend DIVERGING',
      detail: 'exceeds the 50 bps threshold',
      level: 'WARNING',
    },
    {
      at: '2026-07-24T21:00:03Z',
      kind: 'weekly_verdict',
      label: 'trend',
      title: 'week 2026-07-24: trend TRACKING',
      detail: 'divergence -6 bps',
      level: null,
    },
    {
      at: '2026-07-25T00:00:00Z',
      kind: 'decision',
      label: null,
      title: 'Glass Box design ruling',
      detail: 'docs/decisions.md',
      level: null,
    },
  ],
}

export const timelineEmpty: TimelineResponse = {
  count: 0,
  events: [],
  note: 'no artifacts found; this is an empty-state response, not an error',
}

export const decisionsPopulated: DecisionsResponse = {
  count: 1,
  note: null,
  entries: [
    {
      date: '2026-07-25',
      title: 'Glass Box design ruling',
      body: '**Decision.** Narration is template-bound to structured fields.',
    },
  ],
}

export const decisionsEmpty: DecisionsResponse = {
  count: 0,
  entries: [],
  note: 'no artifacts found; this is an empty-state response, not an error',
}

export const ignoredInputsPopulated: IgnoredInputsResponse = {
  statement: 'This system reads settled daily prices and its own account state.',
  reads: [
    {
      name: 'Tiingo end-of-day bars',
      role: 'primary equity EOD price source',
      rationale: 'Adjusted daily closes are the only prices every strategy signal reads.',
    },
    {
      name: 'Alpaca IEX end-of-day bars',
      role: 'independent cross-check on Tiingo',
      rationale: 'A second feed reconciled against the first catches a bad vendor print.',
    },
  ],
  ignores: [
    {
      name: 'News and headlines',
      rationale: 'No strategy has a news term.',
    },
    {
      name: 'Any large-language-model judgement about the market',
      rationale: 'No endpoint asks a model what it thinks.',
    },
  ],
}

export const ignoredInputsEmpty: IgnoredInputsResponse = {
  statement: 'This system reads settled daily prices and its own account state.',
  reads: [],
  ignores: [],
}

export interface ApiFixtures {
  overview: OverviewResponse
  runs: RunsResponse
  narrate: RunNarration
  divergence: DivergenceResponse
  equity: EquityResponse
  risk: RiskResponse
  timeline: TimelineResponse
  decisions: DecisionsResponse
  ignoredInputs: IgnoredInputsResponse
}

export const POPULATED: ApiFixtures = {
  overview: overviewPopulated,
  runs: runsPopulated,
  narrate: narrationPopulated,
  divergence: divergencePopulated,
  equity: equityPopulated,
  risk: riskPopulated,
  timeline: timelinePopulated,
  decisions: decisionsPopulated,
  ignoredInputs: ignoredInputsPopulated,
}

export const EMPTY: ApiFixtures = {
  overview: overviewEmpty,
  runs: runsEmpty,
  narrate: narrationPopulated,
  divergence: divergenceEmpty,
  equity: equityEmpty,
  risk: riskEmpty,
  timeline: timelineEmpty,
  decisions: decisionsEmpty,
  ignoredInputs: ignoredInputsEmpty,
}

/** Route `fetch` to fixtures by URL path. Unknown paths reject loudly. */
export function mockApi(fixtures: ApiFixtures): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      const path = url.split('?')[0] ?? url
      let body: unknown
      if (path === '/api/overview') body = fixtures.overview
      else if (path === '/api/runs') body = fixtures.runs
      else if (/^\/api\/runs\/.+\/narrate$/.test(path)) body = fixtures.narrate
      else if (path === '/api/divergence') body = fixtures.divergence
      else if (path === '/api/equity') body = fixtures.equity
      else if (path === '/api/risk') body = fixtures.risk
      else if (path === '/api/timeline') body = fixtures.timeline
      else if (path === '/api/decisions') body = fixtures.decisions
      else if (path === '/api/ignored-inputs') body = fixtures.ignoredInputs
      else {
        return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }),
  )
}
