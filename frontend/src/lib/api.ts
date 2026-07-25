/**
 * Types and fetchers for the nine Glass Box endpoints.
 *
 * These mirror the pydantic response models in `glassbox/models.py`. Every
 * collection is non-optional and every scalar that can genuinely be unknown is
 * `| null` — the API's contract is that absence is a state, not an error, and the
 * UI's job is to render that state explicitly rather than blank a panel.
 */

export type Provenance = 'on_schedule' | 'catch_up' | 'leaked'
export type Verdict = 'TRACKING' | 'DIVERGING' | 'INSUFFICIENT'

export interface RiskStateView {
  halted: boolean
  reason: string | null
  triggered_at: string | null
  requires_manual_reset: boolean
}

export interface ClockView {
  asset_class: string
  paper_start_date: string | null
  calendar_days_elapsed: number
  target_days: number
  pct_complete: number
  start_note: string | null
  blockers: string[]
}

export interface AccountOverview {
  label: string
  asset_class: string
  latest_equity: number | null
  latest_snapshot_at: string | null
  latest_snapshot_provenance: Provenance | null
  snapshot_count: number
  risk: RiskStateView
  validation_tier: string
  validation_tier_rationale: string
  validation_tier_upgrade_condition: string
  clock: ClockView | null
}

export interface OverviewResponse {
  generated_at: string
  accounts: AccountOverview[]
  week_ending: string | null
  note: string | null
}

export interface StageView {
  stage: string
  ok: boolean
  detail: string | null
}

export interface OrderView {
  symbol: string | null
  side: string | null
  notional: number | null
  status: string | null
  client_order_id: string | null
  submitted_at: string | null
  was_duplicate: boolean
}

export interface IntentView {
  symbol: string | null
  side: string | null
  notional: number | null
  current_w: number | null
  target_w: number | null
}

export interface RunView {
  run_id: string
  strategy: string | null
  timestamp: string | null
  dry_run: boolean | null
  aborted: boolean
  abort_stage: string | null
  abort_reason: string | null
  equity: number | null
  target_weights: Record<string, number>
  no_trades: boolean | null
  est_turnover: number | null
  min_trade_frac: number | null
  stages: StageView[]
  intents: IntentView[]
  submitted_orders: OrderView[]
}

export interface RunsResponse {
  count: number
  label: string | null
  runs: RunView[]
  note: string | null
}

export interface NarrationFact {
  rendered: string
  value: number | string
  source: string
}

export interface RunNarration {
  run_id: string
  strategy: string
  narration: string
  rule_sentences: string[]
  counterfactuals: string[]
  facts: NarrationFact[]
  disclaimer: string
  available: boolean
  note: string | null
}

export interface WeekDivergence {
  week_ending: string | null
  label: string
  asset_class: string | null
  paper_week_return: number | null
  shadow_week_return: number | null
  divergence_bps: number | null
  cumulative_divergence_bps: number | null
  verdict: Verdict | null
  threshold_bps: number | null
  excluded_tail_days: string[]
  window_start: string | null
  window_end: string | null
  structural_note: string | null
}

export interface WeekCorrection {
  week_ending: string
  label: string
  published_divergence_bps: number | null
  published_verdict: string | null
  corrected_divergence_bps: number | null
  corrected_verdict: string | null
  corrected_window: string | null
  cause: string | null
  reference: string
}

export interface DivergenceResponse {
  label: string | null
  weeks: WeekDivergence[]
  corrections: WeekCorrection[]
  note: string | null
}

export interface EquityPoint {
  timestamp: string
  equity: number
  provenance: Provenance
  provenance_rationale: string
}

export interface EquitySeries {
  label: string
  asset_class: string
  points: EquityPoint[]
  provenance_counts: Partial<Record<Provenance, number>>
}

export interface EquityResponse {
  label: string | null
  series: EquitySeries[]
  note: string | null
}

export interface LimitsView {
  max_position_weight: number | null
  max_gross_exposure: number | null
  max_daily_loss: number | null
  max_weekly_loss: number | null
  max_drawdown_kill: number | null
  staleness_max_sessions: number | null
  weekly_divergence_alert_bps: number | null
}

export interface AccountRisk {
  label: string
  asset_class: string
  limits: LimitsView
  limits_source: string
  peak_equity: number | null
  latest_equity: number | null
  current_drawdown: number | null
  drawdown_kill_limit: number | null
  drawdown_headroom: number | null
  kill_switch: RiskStateView
  note: string | null
}

export interface RiskResponse {
  accounts: AccountRisk[]
  note: string | null
}

export interface TimelineEvent {
  at: string | null
  kind: 'order' | 'alert' | 'weekly_verdict' | 'decision'
  label: string | null
  title: string
  detail: string | null
  level: string | null
}

export interface TimelineResponse {
  count: number
  events: TimelineEvent[]
  note: string | null
}

export interface DecisionEntry {
  date: string | null
  title: string
  body: string
}

export interface DecisionsResponse {
  count: number
  entries: DecisionEntry[]
  note: string | null
}

export interface InputRead {
  name: string
  role: string
  rationale: string
}

export interface InputIgnored {
  name: string
  rationale: string
}

export interface IgnoredInputsResponse {
  statement: string
  reads: InputRead[]
  ignores: InputIgnored[]
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { accept: 'application/json' } })
  if (!response.ok) {
    throw new ApiError(`${path} returned ${response.status}`, response.status)
  }
  return (await response.json()) as T
}

const query = (params: Record<string, string | number | undefined>): string => {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  if (entries.length === 0) return ''
  return '?' + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join('&')
}

export const api = {
  overview: () => get<OverviewResponse>('/api/overview'),
  runs: (label?: string, limit?: number) =>
    get<RunsResponse>('/api/runs' + query({ label, limit })),
  narrate: (runId: string) =>
    get<RunNarration>(`/api/runs/${encodeURIComponent(runId)}/narrate`),
  divergence: (label?: string) =>
    get<DivergenceResponse>('/api/divergence' + query({ label })),
  equity: (label?: string) => get<EquityResponse>('/api/equity' + query({ label })),
  risk: () => get<RiskResponse>('/api/risk'),
  timeline: (limit?: number) =>
    get<TimelineResponse>('/api/timeline' + query({ limit })),
  decisions: () => get<DecisionsResponse>('/api/decisions'),
  ignoredInputs: () => get<IgnoredInputsResponse>('/api/ignored-inputs'),
}

export const ACCOUNTS = ['voltarget', 'trend', 'crypto_trend', 'crypto_voltarget'] as const
