/**
 * Shared primitives. Dark-first, typography-driven: hierarchy comes from weight,
 * size, and colour temperature rather than borders and fills. Motion is reserved
 * for state transitions (a panel appearing, a disclosure opening) — nothing here
 * animates decoratively.
 */

import type { ReactNode } from 'react'
import type { Provenance, Verdict } from '../lib/api'

// --------------------------------------------------------------------------- //
// Layout                                                                      //
// --------------------------------------------------------------------------- //

export function Panel({
  title,
  subtitle,
  children,
  actions,
}: {
  title?: string
  subtitle?: string
  children: ReactNode
  actions?: ReactNode
}) {
  return (
    <section className="rounded-lg border border-ink-500 bg-ink-800">
      {title ? (
        <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-ink-600 px-5 py-3">
          <div>
            <h2 className="text-2xs font-medium uppercase tracking-widest text-signal-idle">
              {title}
            </h2>
            {subtitle ? (
              <p className="mt-1 text-sm text-slate-300">{subtitle}</p>
            ) : null}
          </div>
          {actions}
        </header>
      ) : null}
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}

export function SectionHeading({
  eyebrow,
  title,
  lede,
}: {
  eyebrow: string
  title: string
  lede?: string
}) {
  return (
    <header className="mb-6">
      <p className="text-2xs font-medium uppercase tracking-[0.2em] text-signal-idle">
        {eyebrow}
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-50">{title}</h1>
      {lede ? (
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">{lede}</p>
      ) : null}
    </header>
  )
}

/**
 * The explicit empty state. Never a blank panel: say what is missing, and why
 * that is a legitimate state rather than a failure.
 */
export function EmptyState({
  title,
  detail,
  hint,
}: {
  title: string
  detail: string
  hint?: string
}) {
  return (
    <div
      className="rounded-md border border-dashed border-ink-500 bg-ink-900/40 px-5 py-8 text-center"
      data-testid="empty-state"
    >
      <p className="text-sm font-medium text-slate-300">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-xs leading-relaxed text-signal-idle">
        {detail}
      </p>
      {hint ? (
        <p className="mx-auto mt-3 max-w-xl font-mono text-2xs text-signal-idle/70">{hint}</p>
      ) : null}
    </div>
  )
}

export function Metric({
  label,
  value,
  hint,
  mono = true,
}: {
  label: string
  value: ReactNode
  hint?: string
  mono?: boolean
}) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-widest text-signal-idle">{label}</dt>
      <dd
        className={`mt-1 text-slate-100 ${mono ? 'font-mono tabular-nums' : ''} text-[0.95rem]`}
      >
        {value}
      </dd>
      {hint ? <p className="mt-1 text-2xs text-signal-idle/80">{hint}</p> : null}
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Badges                                                                      //
// --------------------------------------------------------------------------- //

const PROVENANCE_STYLE: Record<Provenance, string> = {
  on_schedule: 'border-signal-ok/40 bg-signal-ok/10 text-signal-ok',
  catch_up: 'border-signal-warn/40 bg-signal-warn/10 text-signal-warn',
  leaked: 'border-signal-info/40 bg-signal-info/10 text-signal-info',
}

export const PROVENANCE_LABEL: Record<Provenance, string> = {
  on_schedule: 'on schedule',
  catch_up: 'catch-up',
  leaked: 'leaked task',
}

export function ProvenanceBadge({
  provenance,
  title,
}: {
  provenance: Provenance | null
  title?: string
}) {
  if (!provenance) {
    return (
      <span className="rounded border border-ink-400 px-1.5 py-0.5 text-2xs text-signal-idle">
        no marks
      </span>
    )
  }
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-2xs ${PROVENANCE_STYLE[provenance]}`}
      title={title}
      data-testid={`provenance-${provenance}`}
    >
      {PROVENANCE_LABEL[provenance]}
    </span>
  )
}

// Amber, not red, for DIVERGING: a diverging week is a question to investigate,
// not an emergency. Red is reserved for a live KILL.
const VERDICT_STYLE: Record<Verdict, string> = {
  TRACKING: 'border-signal-ok/40 bg-signal-ok/10 text-signal-ok',
  DIVERGING: 'border-signal-warn/50 bg-signal-warn/10 text-signal-warn',
  INSUFFICIENT: 'border-ink-400 bg-ink-700 text-signal-idle',
}

export function VerdictChip({ verdict }: { verdict: Verdict | string | null }) {
  const key = (verdict ?? 'INSUFFICIENT') as Verdict
  const style = VERDICT_STYLE[key] ?? VERDICT_STYLE.INSUFFICIENT
  return (
    <span
      className={`rounded border px-2 py-0.5 font-mono text-2xs uppercase tracking-wider ${style}`}
      data-testid={`verdict-${key}`}
    >
      {verdict ?? 'INSUFFICIENT'}
    </span>
  )
}

/** Tier badge; the upgrade condition is revealed on hover via the native title. */
export function TierBadge({
  tier,
  rationale,
  upgradeCondition,
}: {
  tier: string
  rationale: string
  upgradeCondition: string
}) {
  return (
    <span
      className="group relative cursor-help rounded border border-ink-400 bg-ink-700 px-2 py-0.5 text-2xs uppercase tracking-wider text-slate-300"
      title={`${rationale}\n\nTo upgrade: ${upgradeCondition}`}
      data-testid="tier-badge"
    >
      {tier}
      <span
        className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-80 rounded-md border border-ink-400 bg-ink-900 p-3 text-2xs normal-case leading-relaxed tracking-normal text-slate-300 shadow-xl group-hover:block"
        role="tooltip"
        data-testid="tier-tooltip"
      >
        <span className="block text-slate-400">{rationale}</span>
        <span className="mt-2 block border-t border-ink-600 pt-2 text-slate-200">
          <span className="text-signal-idle">To upgrade: </span>
          {upgradeCondition}
        </span>
      </span>
    </span>
  )
}

export function KillSwitchBadge({
  halted,
  reason,
  requiresManualReset,
}: {
  halted: boolean
  reason: string | null
  requiresManualReset: boolean
}) {
  if (!halted) {
    return (
      <span
        className="rounded border border-signal-ok/40 bg-signal-ok/10 px-2 py-0.5 text-2xs uppercase tracking-wider text-signal-ok"
        data-testid="kill-inactive"
      >
        not halted
      </span>
    )
  }
  // A live KILL is the one place red is correct: it stops trading until a human acts.
  return (
    <span
      className="rounded border border-red-500/50 bg-red-500/10 px-2 py-0.5 text-2xs uppercase tracking-wider text-red-300"
      title={reason ?? undefined}
      data-testid="kill-active"
    >
      {requiresManualReset ? 'KILL — manual reset required' : 'HALTED'}
    </span>
  )
}

// --------------------------------------------------------------------------- //
// Progress                                                                    //
// --------------------------------------------------------------------------- //

export function ClockBar({ clock }: { clock: ClockLike }) {
  const pct = Math.max(0, Math.min(100, clock.pct_complete))
  return (
    <div data-testid="clock-bar">
      <div className="flex items-baseline justify-between text-2xs text-signal-idle">
        <span>
          day{' '}
          <span className="font-mono tabular-nums text-slate-200">
            {clock.calendar_days_elapsed}
          </span>{' '}
          of {clock.target_days}
        </span>
        <span className="font-mono tabular-nums">{pct.toFixed(1)}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-600">
        <div
          className="h-full rounded-full bg-signal-info/70 transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export interface ClockLike {
  calendar_days_elapsed: number
  target_days: number
  pct_complete: number
}
