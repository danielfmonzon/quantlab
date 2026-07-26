/**
 * LEDGER — one merged, filterable stream: orders, alerts, weekly verdicts, and the
 * decisions log. Decisions are the only entries with a body worth reading in full,
 * so they expand in place.
 */

import { useState } from 'react'
import { api } from '../lib/api'
import type { DecisionsResponse, TimelineEvent, TimelineResponse } from '../lib/api'
import { stamp } from '../lib/format'
import { useApi } from '../lib/useApi'
import { EmptyState, SectionHeading } from '../components/primitives'

type Kind = TimelineEvent['kind']

const KINDS: Array<{ kind: Kind; label: string }> = [
  { kind: 'order', label: 'orders' },
  { kind: 'alert', label: 'alerts' },
  { kind: 'weekly_verdict', label: 'verdicts' },
  { kind: 'decision', label: 'decisions' },
]

const KIND_STYLE: Record<Kind, string> = {
  order: 'border-signal-info/40 text-signal-info',
  alert: 'border-signal-warn/40 text-signal-warn',
  weekly_verdict: 'border-signal-ok/40 text-signal-ok',
  decision: 'border-ink/[0.16] text-ink-2',
}

const LEVEL_STYLE: Record<string, string> = {
  INFO: 'text-muted',
  WARNING: 'text-signal-warn',
  CRITICAL: 'text-signal-danger',
}

export function Ledger() {
  const [active, setActive] = useState<Set<Kind>>(new Set(KINDS.map((k) => k.kind)))
  const timeline = useApi<TimelineResponse>(() => api.timeline(1000))
  const decisions = useApi<DecisionsResponse>(() => api.decisions())

  const bodyByTitle = new Map(
    (decisions.data?.entries ?? []).map((entry) => [entry.title, entry.body]),
  )

  const events = (timeline.data?.events ?? []).filter((event) => active.has(event.kind))

  const toggle = (kind: Kind) => {
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  return (
    <div>
      <SectionHeading
        eyebrow="ledger"
        title="Everything, in order"
        lede="Orders submitted, alerts fired, weekly verdicts recorded, and design decisions ruled — merged into one stream, newest first. Undated entries sort last."
      />

      <div className="mb-6 flex flex-wrap gap-1.5">
        {KINDS.map(({ kind, label }) => (
          <button
            key={kind}
            type="button"
            onClick={() => toggle(kind)}
            aria-pressed={active.has(kind)}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              active.has(kind)
                ? 'border-signal-info/50 bg-signal-info/10 text-ink'
                : 'border-ink/[0.16] bg-cream-2 text-muted hover:text-ink-2'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {timeline.error ? (
        <EmptyState title="Could not read /api/timeline." detail={timeline.error} />
      ) : timeline.loading ? (
        <p className="text-xs text-muted">reading /api/timeline…</p>
      ) : events.length === 0 ? (
        <EmptyState
          title={
            (timeline.data?.events.length ?? 0) === 0
              ? 'Nothing has been recorded yet.'
              : 'No events match the selected filters.'
          }
          detail={
            (timeline.data?.events.length ?? 0) === 0
              ? 'Orders, alerts, weekly verdicts, and decisions all land here once they exist. An empty ledger on a fresh install is the expected state.'
              : 'Re-enable a filter above to see the rest of the stream.'
          }
          hint={timeline.data?.note ?? undefined}
        />
      ) : (
        <ol className="space-y-1" data-testid="ledger-list">
          {events.map((event, index) => {
            const body = event.kind === 'decision' ? bodyByTitle.get(event.title) : undefined
            return (
              <li
                key={`${event.kind}-${index}`}
                className="rounded border border-ink/[0.10] bg-cream-2/70 px-4 py-2.5"
                data-testid={`ledger-${event.kind}`}
              >
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span
                    className={`rounded border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wider ${KIND_STYLE[event.kind]}`}
                  >
                    {event.kind === 'weekly_verdict' ? 'verdict' : event.kind}
                  </span>
                  <span className="min-w-0 flex-1 text-sm text-ink-2">{event.title}</span>
                  {event.label ? (
                    <span className="font-mono text-2xs text-muted">{event.label}</span>
                  ) : null}
                  {event.level ? (
                    <span
                      className={`font-mono text-2xs ${LEVEL_STYLE[event.level] ?? 'text-muted'}`}
                    >
                      {event.level}
                    </span>
                  ) : null}
                  <span className="font-mono text-2xs tabular-nums text-muted">
                    {event.at ? stamp(event.at) : 'undated'}
                  </span>
                </div>

                {event.detail && event.kind !== 'decision' ? (
                  <p className="mt-1.5 text-xs leading-relaxed text-muted">
                    {event.detail}
                  </p>
                ) : null}

                {body ? (
                  <details className="mt-2">
                    <summary className="cursor-pointer text-2xs text-signal-info hover:text-ink">
                      read the ruling
                    </summary>
                    <div
                      className="mt-2 whitespace-pre-wrap border-l-2 border-ink/[0.16] pl-3 text-xs leading-relaxed text-muted"
                      data-testid="decision-body"
                    >
                      {body}
                    </div>
                  </details>
                ) : null}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
