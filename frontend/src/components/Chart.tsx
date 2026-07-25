/**
 * The three-layer chart contract, enforced by the type system.
 *
 * No chart in this app renders without:
 *   1. `takeaway` — one sentence stating what the reader should conclude. REQUIRED
 *      and non-empty; a chart without a stated conclusion invites the reader to
 *      invent one.
 *   2. `mechanics` — the caption below, explaining how the numbers were produced.
 *      REQUIRED, for the same reason.
 *   3. `rawHref` — a link to the endpoint the chart was drawn from, so the reader
 *      can check the arithmetic.
 *
 * `takeaway` and `mechanics` are non-optional props, so omitting either is a
 * COMPILE error (`tsc -b` runs in `npm run build`). Emptiness can't be caught by
 * the type system, so the component asserts it at runtime too — see
 * `assertChartContract`.
 */

import type { ReactNode } from 'react'

export interface ChartProps {
  /** One-sentence conclusion, shown above the plot. Required, must be non-empty. */
  takeaway: string
  /** How the numbers were produced, shown below the plot. Required, non-empty. */
  mechanics: string
  /** Endpoint this chart was drawn from — the reader's route to the raw numbers. */
  rawHref: string
  title: string
  children: ReactNode
  /** Optional extra annotation row between plot and mechanics. */
  annotation?: ReactNode
}

export class ChartContractError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ChartContractError'
  }
}

/**
 * Runtime half of the contract. The compiler guarantees the props EXIST; this
 * guarantees they say something. Exported so it can be tested directly.
 */
export function assertChartContract(props: Pick<ChartProps, 'takeaway' | 'mechanics' | 'title'>): void {
  if (!props.takeaway || props.takeaway.trim().length === 0) {
    throw new ChartContractError(
      `Chart "${props.title}" has no takeaway. Every chart must state its own ` +
        'conclusion in one sentence.',
    )
  }
  if (!props.mechanics || props.mechanics.trim().length === 0) {
    throw new ChartContractError(
      `Chart "${props.title}" has no mechanics caption. Every chart must explain ` +
        'how its numbers were produced.',
    )
  }
}

export function Chart({
  takeaway,
  mechanics,
  rawHref,
  title,
  children,
  annotation,
}: ChartProps) {
  assertChartContract({ takeaway, mechanics, title })

  return (
    <figure className="rounded-lg border border-ink-500 bg-ink-800" data-testid="chart">
      <div className="border-b border-ink-600 px-5 py-4">
        <h3 className="text-2xs font-medium uppercase tracking-widest text-signal-idle">
          {title}
        </h3>
        <p
          className="mt-2 text-[0.95rem] leading-snug text-slate-100"
          data-testid="chart-takeaway"
        >
          {takeaway}
        </p>
      </div>

      <div className="px-2 py-4">{children}</div>

      {annotation ? (
        <div className="border-t border-ink-600 px-5 py-3" data-testid="chart-annotation">
          {annotation}
        </div>
      ) : null}

      <figcaption className="flex flex-wrap items-baseline justify-between gap-3 border-t border-ink-600 px-5 py-3">
        <p className="max-w-3xl text-xs leading-relaxed text-signal-idle" data-testid="chart-mechanics">
          {mechanics}
        </p>
        <a
          href={rawHref}
          className="shrink-0 font-mono text-2xs text-signal-info underline decoration-dotted underline-offset-4 hover:text-slate-100"
          data-testid="chart-raw-link"
        >
          raw ↗
        </a>
      </figcaption>
    </figure>
  )
}
