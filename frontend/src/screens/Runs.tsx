/**
 * RUNS — the narration screen, and the app's most important disclosure.
 *
 * THREE-LAYER DISCLOSURE. The prose is the primary content, but every number in it
 * is hoverable and reveals the JSON path it came from:
 *
 *   layer 1  the sentence           "moving weight from 93.71% to 85.72%"
 *   layer 2  the fact               93.71% ← report.plan.intents[0].current_w
 *   layer 3  the raw report         the collapsed <details> at the bottom
 *
 * `NarrationFacts` splits the narration on the exact `rendered` strings the API
 * returned, so the mapping is the API's, not a client-side re-derivation. A number
 * the API did not declare as a fact renders as plain text — it cannot acquire a
 * source path it was never given.
 */

import { useState } from 'react'
import { api } from '../lib/api'
import type { RunNarration, RunView, RunsResponse } from '../lib/api'
import { ACCOUNTS } from '../lib/api'
import { accountName, money, stamp } from '../lib/format'
import { useApi } from '../lib/useApi'
import { EmptyState, SectionHeading } from '../components/primitives'

/** Escape a fact's rendered form for use inside a RegExp alternation. */
const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Whether a match at `index` is a standalone token rather than part of a longer one.
 *
 * This guard is load-bearing. Bare numeric facts are common — `20` for a lookback
 * window, `252` for an annualization basis — and a naive substring match finds `20`
 * inside the run id `run_voltarget_20260724T140007Z` and inside the timestamp
 * `2026-07-24`, shredding the sentence. A match is accepted only when it is not
 * preceded by a digit, letter, `.` or `,` (so it is not the tail of a longer number)
 * and not followed by a digit or letter (so it is not the head of one).
 */
function isStandalone(text: string, index: number, length: number): boolean {
  const before = index > 0 ? text[index - 1] : undefined
  const after = text[index + length]
  if (before !== undefined && /[0-9A-Za-z.,]/.test(before)) return false
  if (after !== undefined && /[0-9A-Za-z]/.test(after)) return false
  return true
}

/**
 * Render `text`, wrapping every declared fact in a hoverable annotation.
 *
 * Single pass with a longest-first alternation, so `$7,897.07` is matched before the
 * `7` inside it, and each candidate is boundary-checked before it is accepted.
 */
export function NarrationFacts({
  text,
  facts,
  testId = 'narration',
}: {
  text: string
  facts: RunNarration['facts']
  /** Distinguishes the main narration from each counterfactual line. */
  testId?: string
}) {
  const unique = new Map<string, string>()
  for (const fact of facts) {
    // First declaration wins; the API lists facts in emission order.
    if (!unique.has(fact.rendered)) unique.set(fact.rendered, fact.source)
  }
  // Longest first: JS alternation is ordered, so `$7,897.07` wins over `7`.
  const needles = [...unique.keys()].sort((a, b) => b.length - a.length)

  const nodes: Array<string | { rendered: string; source: string }> = []
  if (needles.length === 0) {
    nodes.push(text)
  } else {
    const pattern = new RegExp(needles.map(escapeRe).join('|'), 'g')
    let cursor = 0
    let match: RegExpExecArray | null
    while ((match = pattern.exec(text)) !== null) {
      const found = match[0]
      if (!isStandalone(text, match.index, found.length)) {
        // Not a real occurrence — resume one character along so a valid match that
        // starts inside this span is still found.
        pattern.lastIndex = match.index + 1
        continue
      }
      if (match.index > cursor) nodes.push(text.slice(cursor, match.index))
      nodes.push({ rendered: found, source: unique.get(found)! })
      cursor = match.index + found.length
      pattern.lastIndex = cursor
    }
    if (cursor < text.length) nodes.push(text.slice(cursor))
  }

  return (
    <p className="text-[0.95rem] leading-7 text-ink-2" data-testid={testId}>
      {nodes.map((node, index) =>
        typeof node === 'string' ? (
          <span key={index}>{node}</span>
        ) : (
          <span
            key={index}
            className="group relative cursor-help font-mono text-ink underline decoration-signal-info/40 decoration-dotted underline-offset-4 hover:decoration-signal-info"
            title={`source: ${node.source}`}
            data-testid="narration-fact"
            data-source={node.source}
          >
            {node.rendered}
            <span
              className="pointer-events-none absolute bottom-full left-0 z-20 mb-1.5 hidden w-max max-w-sm rounded border border-ink/[0.16] bg-cream px-2 py-1 font-mono text-2xs text-signal-info shadow-xl group-hover:block"
              role="tooltip"
              data-testid="fact-source"
            >
              {node.source}
            </span>
          </span>
        ),
      )}
    </p>
  )
}

function StageChecklist({ stages }: { stages: RunView['stages'] }) {
  if (stages.length === 0) {
    return <p className="text-2xs text-muted">no stages recorded</p>
  }
  return (
    <ol className="flex flex-wrap gap-1.5" data-testid="stage-checklist">
      {stages.map((stage, index) => (
        <li
          key={`${stage.stage}-${index}`}
          className={`rounded border px-1.5 py-0.5 font-mono text-2xs ${
            stage.ok
              ? 'border-signal-ok/30 bg-signal-ok/5 text-signal-ok'
              : 'border-signal-warn/50 bg-signal-warn/10 text-signal-warn'
          }`}
          title={stage.detail ?? undefined}
          data-testid={stage.ok ? 'stage-ok' : 'stage-failed'}
        >
          {stage.ok ? '✓' : '✕'} {stage.stage}
        </li>
      ))}
    </ol>
  )
}

function RunCard({ run }: { run: RunView }) {
  const [open, setOpen] = useState(false)
  const narration = useApi<RunNarration>(
    () => (open ? api.narrate(run.run_id) : Promise.resolve(null as never)),
    [open, run.run_id],
  )

  return (
    <article
      className="rounded-brand border border-ink/[0.16] bg-cream-2"
      data-testid={`run-${run.run_id}`}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink/[0.10] px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-2">
            {/* h2, not h3: the page heading is the h1, so an h3 here skips a level
                and breaks the document outline for screen-reader navigation. */}
            <h2 className="text-[1.05rem] font-medium tracking-tight text-ink">
              {accountName(run.strategy ?? 'unknown')}
            </h2>
            <span className="font-mono text-2xs text-muted">{stamp(run.timestamp)}</span>
            {run.dry_run ? (
              <span className="rounded border border-ink/[0.16] bg-cream-3 px-1.5 py-0.5 text-2xs uppercase tracking-wider text-muted">
                dry run
              </span>
            ) : (
              <span className="rounded border border-signal-info/40 bg-signal-info/10 px-1.5 py-0.5 text-2xs uppercase tracking-wider text-signal-info">
                submit
              </span>
            )}
            {run.aborted ? (
              <span
                className="rounded border border-signal-warn/50 bg-signal-warn/10 px-1.5 py-0.5 text-2xs uppercase tracking-wider text-signal-warn"
                data-testid="run-aborted"
              >
                aborted @ {run.abort_stage}
              </span>
            ) : null}
          </div>
          <p className="mt-1 font-mono text-2xs text-muted">{run.run_id}</p>
        </div>
        <div className="text-right">
          <p className="font-mono text-sm tabular-nums text-ink-2">{money(run.equity)}</p>
          <p className="text-2xs text-muted">equity at run</p>
        </div>
      </header>

      <div className="space-y-4 px-5 py-4">
        <StageChecklist stages={run.stages} />

        {run.aborted && run.abort_reason ? (
          <p className="rounded border border-signal-warn/30 bg-signal-warn/5 px-3 py-2 text-xs leading-relaxed text-signal-warn">
            {run.abort_reason}
          </p>
        ) : null}

        {!open ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded border border-ink/[0.16] bg-cream-3 px-3 py-1.5 text-xs text-ink-2 transition-colors hover:border-signal-info/50 hover:text-ink"
            data-testid={`explain-${run.run_id}`}
          >
            Explain this run
          </button>
        ) : narration.loading ? (
          <p className="text-xs text-muted">reading narration…</p>
        ) : narration.error ? (
          <EmptyState title="Narration unavailable." detail={narration.error} />
        ) : narration.data ? (
          <div className="space-y-4">
            <NarrationFacts text={narration.data.narration} facts={narration.data.facts} />

            {narration.data.counterfactuals.length > 0 ? (
              <div
                className="rounded-md border border-dashed border-ink/[0.16] bg-cream-3/60 px-4 py-3"
                data-testid="counterfactual-block"
              >
                <p className="text-2xs font-medium uppercase tracking-widest text-muted">
                  What it did NOT do
                </p>
                <ul className="mt-2 space-y-2">
                  {narration.data.counterfactuals.map((line, index) => (
                    <li key={index} className="text-xs leading-relaxed text-ink-2">
                      <NarrationFacts
                        text={line}
                        facts={narration.data!.facts}
                        testId="counterfactual-line"
                      />
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <p className="border-t border-ink/[0.10] pt-3 text-2xs leading-relaxed text-muted">
              {narration.data.disclaimer}
            </p>

            <details className="group">
              <summary className="cursor-pointer font-mono text-2xs text-signal-info hover:text-ink">
                raw run report (JSON)
              </summary>
              <pre className="mt-2 max-h-96 overflow-auto rounded border border-ink/[0.10] bg-cream p-3 font-mono text-2xs leading-relaxed text-muted">
                {JSON.stringify(run, null, 2)}
              </pre>
            </details>
          </div>
        ) : null}
      </div>
    </article>
  )
}

export function Runs() {
  const [label, setLabel] = useState<string>('')
  const runs = useApi<RunsResponse>(() => api.runs(label || undefined, 50), [label])

  return (
    <div>
      <SectionHeading
        eyebrow="runs"
        title="Every rebalance, and why"
        lede="Each run is a gated pipeline: stages pass in order and the first failure aborts before any order is sent. The narration below is generated from the run report's own fields — hover any number to see the exact JSON path it came from."
      />

      <div className="mb-6 flex flex-wrap gap-1.5">
        <FilterButton active={label === ''} onClick={() => setLabel('')}>
          all accounts
        </FilterButton>
        {ACCOUNTS.map((account) => (
          <FilterButton
            key={account}
            active={label === account}
            onClick={() => setLabel(account)}
          >
            {accountName(account)}
          </FilterButton>
        ))}
      </div>

      {runs.error ? (
        <EmptyState title="Could not read /api/runs." detail={runs.error} />
      ) : runs.loading ? (
        <p className="text-xs text-muted">reading /api/runs…</p>
      ) : (runs.data?.runs.length ?? 0) === 0 ? (
        <EmptyState
          title="No run reports on file."
          detail={
            label
              ? `No runs recorded for ${accountName(label)}. Once the scheduled pipeline runs for this account, each attempt appears here with its stage checklist and narration.`
              : 'The paper runner writes one report per attempt to reports/paper/. None exist yet, so there is nothing to explain.'
          }
          hint={runs.data?.note ?? undefined}
        />
      ) : (
        <div className="space-y-4">
          {runs.data!.runs.map((run) => (
            <RunCard key={run.run_id} run={run} />
          ))}
        </div>
      )}
    </div>
  )
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded border px-2.5 py-1 text-xs transition-colors ${
        active
          ? 'border-signal-info/50 bg-signal-info/10 text-ink'
          : 'border-ink/[0.16] bg-cream-2 text-muted hover:text-ink-2'
      }`}
      aria-pressed={active}
    >
      {children}
    </button>
  )
}
