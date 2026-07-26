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
    <section className="rounded-brand border border-ink/[0.16] bg-cream-2">
      {title ? (
        <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-ink/[0.10] px-5 py-3">
          <div>
            <h2 className="text-2xs font-medium uppercase tracking-widest text-muted">
              {title}
            </h2>
            {subtitle ? (
              <p className="mt-1 text-sm text-ink-2">{subtitle}</p>
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
      <p className="text-2xs font-medium uppercase tracking-[0.2em] text-muted">
        {eyebrow}
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      {lede ? (
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">{lede}</p>
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
      className="rounded-md border border-dashed border-ink/[0.16] bg-cream-3/60 px-5 py-8 text-center"
      data-testid="empty-state"
    >
      <p className="text-sm font-medium text-ink-2">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-xs leading-relaxed text-muted">
        {detail}
      </p>
      {hint ? (
        <p className="mx-auto mt-3 max-w-xl font-mono text-2xs text-muted">{hint}</p>
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
  // The hint lives INSIDE the <dd>. A <dl>'s div wrapper may contain only <dt>/<dd>
  // groups, so a sibling <p> here is a real structure violation (axe: definition-list)
  // and leaves the hint outside the term/definition pairing a screen reader announces.
  return (
    <div>
      <dt className="text-2xs uppercase tracking-widest text-muted">{label}</dt>
      <dd className={`mt-1 text-[0.95rem] text-ink ${mono ? 'font-mono tabular-nums' : ''}`}>
        {value}
        {hint ? (
          <span className="mt-1 block font-sans text-2xs normal-case tracking-normal text-muted">
            {hint}
          </span>
        ) : null}
      </dd>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Badges                                                                      //
// --------------------------------------------------------------------------- //

const PROVENANCE_STYLE: Record<Provenance, string> = {
  on_schedule: 'border-signal-ok/40 bg-signal-ok/[0.08] text-signal-ok',
  catch_up: 'border-signal-warn/40 bg-signal-warn/[0.08] text-signal-warn',
  leaked: 'border-signal-info/40 bg-signal-info/[0.08] text-signal-info',
}

export const PROVENANCE_LABEL: Record<Provenance, string> = {
  on_schedule: 'on schedule',
  catch_up: 'catch-up',
  leaked: 'leaked task',
}

/**
 * Provenance is encoded THREE ways: shape, colour, and text.
 *
 * WCAG 1.4.1 forbids colour as the only carrier of meaning, and this is the field where
 * that rule bites hardest — the whole point of provenance is that a reader can tell a
 * clean mark from a late one, and roughly 1 in 12 men cannot separate the green from the
 * clay. So each state also gets a distinct glyph (● on time, ◐ late, ▲ wrong task) and a
 * written label. Any one of the three carries the meaning alone.
 */
export const PROVENANCE_SHAPE: Record<Provenance, string> = {
  on_schedule: '●', // ● filled circle — complete, as intended
  catch_up: '◐', // ◐ half-filled — happened, but late
  leaked: '▲', // ▲ triangle — a warning shape, distinct at any size
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
      <span className="rounded border border-ink/[0.16] px-1.5 py-0.5 text-2xs text-muted">
        <span aria-hidden className="mr-1">○</span>
        no marks
      </span>
    )
  }
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs ${PROVENANCE_STYLE[provenance]}`}
      title={title}
      data-testid={`provenance-${provenance}`}
    >
      <span aria-hidden data-testid={`provenance-shape-${provenance}`}>
        {PROVENANCE_SHAPE[provenance]}
      </span>
      {PROVENANCE_LABEL[provenance]}
    </span>
  )
}

// Amber, not red, for DIVERGING: a diverging week is a question to investigate,
// not an emergency. Red is reserved for a live KILL.
const VERDICT_STYLE: Record<Verdict, string> = {
  TRACKING: 'border-signal-ok/40 bg-signal-ok/[0.08] text-signal-ok',
  DIVERGING: 'border-signal-warn/50 bg-signal-warn/[0.08] text-signal-warn',
  INSUFFICIENT: 'border-ink/[0.16] bg-cream-3 text-muted',
}

const VERDICT_SHAPE: Record<Verdict, string> = {
  TRACKING: '✓', // ✓
  DIVERGING: '▲', // ▲ — a question to investigate, not an alarm
  INSUFFICIENT: '–', // – nothing to say yet
}

export function VerdictChip({ verdict }: { verdict: Verdict | string | null }) {
  const key = (verdict ?? 'INSUFFICIENT') as Verdict
  const style = VERDICT_STYLE[key] ?? VERDICT_STYLE.INSUFFICIENT
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 font-mono text-2xs uppercase tracking-wider ${style}`}
      data-testid={`verdict-${key}`}
    >
      <span aria-hidden>{VERDICT_SHAPE[key] ?? VERDICT_SHAPE.INSUFFICIENT}</span>
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
      className="group relative cursor-help rounded border border-ink/[0.16] bg-cream-3 px-2 py-0.5 text-2xs uppercase tracking-wider text-ink-2"
      title={`${rationale}\n\nTo upgrade: ${upgradeCondition}`}
      data-testid="tier-badge"
    >
      {tier}
      <span
        className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-80 rounded-md border border-ink/[0.16] bg-cream p-3 text-2xs normal-case leading-relaxed tracking-normal text-ink-2 shadow-xl group-hover:block"
        role="tooltip"
        data-testid="tier-tooltip"
      >
        <span className="block text-muted">{rationale}</span>
        <span className="mt-2 block border-t border-ink/[0.10] pt-2 text-ink-2">
          <span className="text-muted">To upgrade: </span>
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
      className="rounded border border-signal-danger/40 bg-signal-danger/10 px-2 py-0.5 text-2xs uppercase tracking-wider text-signal-danger"
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
      <div className="flex items-baseline justify-between text-2xs text-muted">
        <span>
          day{' '}
          <span className="font-mono tabular-nums text-ink-2">
            {clock.calendar_days_elapsed}
          </span>{' '}
          of {clock.target_days}
        </span>
        <span className="font-mono tabular-nums">{pct.toFixed(1)}%</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-cream-4">
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
