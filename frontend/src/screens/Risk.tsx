/**
 * RISK — distance to the limit that would stop trading.
 *
 * Every gauge is captioned with the literal answer to "should I be worried?",
 * derived from thresholds and the current drawdown ONLY. No judgement, no market
 * view: the caption is a function of two numbers, so it cannot flatter or alarm
 * beyond what the arithmetic supports.
 */

import { api } from '../lib/api'
import type { AccountRisk, RiskResponse } from '../lib/api'
import { accountName, money, pct, signedPct } from '../lib/format'
import { useApi } from '../lib/useApi'
import {
  EmptyState,
  KillSwitchBadge,
  Metric,
  Panel,
  SectionHeading,
} from '../components/primitives'

/**
 * The "should I be worried?" caption, computed from thresholds alone.
 *
 * Exported so the test suite can pin the wording to the arithmetic rather than
 * trusting a screenshot.
 */
export function worryCaption(account: AccountRisk): string {
  if (account.kill_switch.halted) {
    return account.kill_switch.requires_manual_reset
      ? 'Yes — the kill switch is ACTIVE and requires a manual reset. This account will not trade until a human clears it.'
      : 'Yes — this account is halted. It will not trade until the halt clears.'
  }
  const dd = account.current_drawdown
  const kill = account.drawdown_kill_limit
  if (dd === null || kill === null) {
    return 'Unknown — there is not enough equity history to measure a drawdown yet. Nothing to be worried about, and nothing to be reassured by either.'
  }
  const used = Math.abs(dd) / kill
  const headroom = account.drawdown_headroom ?? kill - Math.abs(dd)
  const furtherNeeded = `would need a further ${pct(-headroom)} from here to trigger the kill switch`
  if (used < 0.25) {
    return `No — the drawdown is using ${pct(used, 1)} of the kill threshold; it ${furtherNeeded}.`
  }
  if (used < 0.6) {
    return `Not yet, but worth watching — the drawdown is using ${pct(used, 1)} of the kill threshold; it ${furtherNeeded}.`
  }
  return `Yes — the drawdown is using ${pct(used, 1)} of the kill threshold; it ${furtherNeeded}.`
}

function Gauge({ account }: { account: AccountRisk }) {
  const kill = account.drawdown_kill_limit
  const dd = account.current_drawdown === null ? null : Math.abs(account.current_drawdown)
  const fillPct = kill && dd !== null ? Math.min(100, (dd / kill) * 100) : 0

  return (
    <div data-testid={`gauge-${account.label}`}>
      <div className="flex items-baseline justify-between text-2xs text-signal-idle">
        <span>0%</span>
        <span className="text-slate-300">
          drawdown{' '}
          <span className="font-mono tabular-nums text-slate-100">
            {signedPct(account.current_drawdown)}
          </span>
        </span>
        <span>
          kill at{' '}
          <span className="font-mono tabular-nums text-signal-warn">
            {kill === null ? '—' : `-${pct(kill)}`}
          </span>
        </span>
      </div>

      <div className="relative mt-2 h-3 overflow-hidden rounded-full bg-ink-600">
        {/* Filled portion = how much of the kill budget the drawdown has consumed. */}
        <div
          className="h-full rounded-full bg-signal-warn/60 transition-[width] duration-500"
          style={{ width: `${fillPct}%` }}
          data-testid={`gauge-fill-${account.label}`}
        />
        {dd !== null && kill !== null ? (
          <div
            className="absolute top-0 h-full w-0.5 bg-slate-100"
            style={{ left: `${fillPct}%` }}
            aria-hidden
          />
        ) : null}
      </div>

      <p
        className="mt-3 text-xs leading-relaxed text-slate-300"
        data-testid={`worry-${account.label}`}
      >
        <span className="text-signal-idle">Should I be worried? </span>
        {worryCaption(account)}
      </p>
    </div>
  )
}

export function Risk() {
  const resource = useApi<RiskResponse>(() => api.risk())
  const accounts = resource.data?.accounts ?? []

  return (
    <div>
      <SectionHeading
        eyebrow="risk"
        title="How far from the brakes"
        lede="Each account has a peak-to-trough drawdown limit that trips a kill switch and stops trading until a human resets it. These gauges show how much of that budget the current drawdown has used — and the limits come from the same YAML the risk engine reads."
      />

      {resource.error ? (
        <EmptyState title="Could not read /api/risk." detail={resource.error} />
      ) : resource.loading ? (
        <p className="text-xs text-signal-idle">reading /api/risk…</p>
      ) : accounts.length === 0 ? (
        <EmptyState
          title="No accounts to report."
          detail="The approved roster is empty, so there are no limits to check against."
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {accounts.map((account) => (
            <Panel
              key={account.label}
              title={`${accountName(account.label)} · ${account.asset_class}`}
              actions={
                <KillSwitchBadge
                  halted={account.kill_switch.halted}
                  reason={account.kill_switch.reason}
                  requiresManualReset={account.kill_switch.requires_manual_reset}
                />
              }
            >
              <Gauge account={account} />

              <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-ink-600 pt-4 sm:grid-cols-4">
                <Metric label="peak" value={money(account.peak_equity)} />
                <Metric label="latest" value={money(account.latest_equity)} />
                <Metric
                  label="headroom"
                  value={
                    account.drawdown_headroom === null ? '—' : pct(account.drawdown_headroom)
                  }
                  hint="before KILL"
                />
                <Metric
                  label="daily / weekly"
                  value={
                    <span className="text-xs">
                      {pct(account.limits.max_daily_loss)} / {pct(account.limits.max_weekly_loss)}
                    </span>
                  }
                  hint="HALT limits"
                />
              </dl>

              <p className="mt-4 font-mono text-2xs text-signal-idle">
                limits read from {account.limits_source}
              </p>
              {account.note ? (
                <p className="mt-2 text-2xs leading-relaxed text-signal-warn/80">
                  {account.note}
                </p>
              ) : null}
            </Panel>
          ))}
        </div>
      )}
    </div>
  )
}
