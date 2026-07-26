/**
 * DIVERGENCE — paper against the shadow it should have matched.
 *
 * Two editorial decisions are load-bearing here:
 *
 * 1. DIVERGING is AMBER, never red. A diverging week is a question — usually about
 *    measurement, as week 2026-07-24 turned out to be — not an emergency. The
 *    caption says so in words, because a colour convention alone can be misread.
 * 2. Week 2026-07-24 renders BOTH the published figure and the corrected one, with
 *    the ruling that connects them. Quietly replacing a published number with a
 *    better one would erase the audit trail that makes the correction credible.
 */

import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../lib/api'
import type { DivergenceResponse, WeekCorrection, WeekDivergence } from '../lib/api'
import { ACCOUNTS } from '../lib/api'
import { accountName, bps, signedPct } from '../lib/format'
import { useApi } from '../lib/useApi'
import { Chart } from '../components/Chart'
import { EmptyState, SectionHeading, VerdictChip } from '../components/primitives'

const VERDICT_FILL: Record<string, string> = {
  TRACKING: '#1e5141',
  DIVERGING: '#8f5113',
  INSUFFICIENT: '#645f4e',
}

const takeawayFor = (weeks: WeekDivergence[], threshold: number): string => {
  if (weeks.length === 0) return 'No weekly reviews on file yet.'
  const beyond = weeks.filter(
    (w) => w.divergence_bps !== null && Math.abs(w.divergence_bps) > threshold,
  )
  const latest = weeks[weeks.length - 1]!
  if (beyond.length === 0) {
    return `Every recorded week tracked its shadow within the ${threshold.toFixed(0)} bps threshold; the latest is ${bps(latest.divergence_bps)}.`
  }
  return `${beyond.length} of ${weeks.length} recorded week${weeks.length === 1 ? '' : 's'} exceeded the ${threshold.toFixed(0)} bps threshold — the latest week is ${bps(latest.divergence_bps)}, verdict ${latest.verdict ?? 'unrecorded'}.`
}

function CorrectionCallout({ correction }: { correction: WeekCorrection }) {
  return (
    <div
      className="rounded-md border border-signal-warn/30 bg-signal-warn/5 px-4 py-3"
      data-testid={`correction-${correction.label}-${correction.week_ending}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-2xs font-medium uppercase tracking-widest text-signal-warn">
          re-ruled
        </span>
        <span className="font-mono text-2xs text-muted">
          week {correction.week_ending}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 font-mono text-sm tabular-nums">
        <span className="text-muted line-through decoration-signal-warn/50">
          {bps(correction.published_divergence_bps, 2)}
        </span>
        <span className="text-2xs uppercase tracking-wider text-muted">
          {correction.published_verdict}
        </span>
        <span aria-hidden className="text-signal-warn">
          →
        </span>
        <span className="text-ink" data-testid="corrected-value">
          {correction.corrected_divergence_bps === null
            ? 'no figure'
            : bps(correction.corrected_divergence_bps, 2)}
        </span>
        <VerdictChip verdict={correction.corrected_verdict} />
        {correction.corrected_window ? (
          <span className="text-2xs text-muted">
            over {correction.corrected_window}
          </span>
        ) : null}
      </div>

      {correction.cause ? (
        <p className="mt-3 max-w-3xl text-xs leading-relaxed text-ink-2">
          {correction.cause}
        </p>
      ) : null}
      <p className="mt-2 font-mono text-2xs text-muted">
        re-ruled: see decision 2026-07-25 — {correction.reference}
      </p>
    </div>
  )
}

export function Divergence() {
  const [label, setLabel] = useState<string>(ACCOUNTS[0])
  const resource = useApi<DivergenceResponse>(() => api.divergence(label), [label])

  const weeks = resource.data?.weeks ?? []
  const corrections = resource.data?.corrections ?? []
  const threshold = weeks.find((w) => w.threshold_bps !== null)?.threshold_bps ?? 50
  const structural = [...weeks].reverse().find((w) => w.structural_note)?.structural_note

  const chartData = weeks.map((week) => ({
    week: week.week_ending ?? '—',
    divergence: week.divergence_bps ?? 0,
    paper: (week.paper_week_return ?? 0) * 100,
    shadow: (week.shadow_week_return ?? 0) * 100,
    verdict: week.verdict ?? 'INSUFFICIENT',
    excluded: week.excluded_tail_days,
  }))

  return (
    <div>
      <SectionHeading
        eyebrow="divergence"
        title="Paper against its shadow"
        lede="The shadow is what this account SHOULD have earned under its own rules, recomputed from settled prices. The gap between them is either structural (mark timing, dividends) or a real tracking problem — and the point of measuring it weekly is to tell those apart."
      />

      <div className="mb-6 flex flex-wrap gap-1.5">
        {ACCOUNTS.map((account) => (
          <button
            key={account}
            type="button"
            onClick={() => setLabel(account)}
            aria-pressed={label === account}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              label === account
                ? 'border-signal-info/50 bg-signal-info/10 text-ink'
                : 'border-ink/[0.16] bg-cream-2 text-muted hover:text-ink-2'
            }`}
          >
            {accountName(account)}
          </button>
        ))}
      </div>

      {resource.error ? (
        <EmptyState title="Could not read /api/divergence." detail={resource.error} />
      ) : resource.loading ? (
        <p className="text-xs text-muted">reading /api/divergence…</p>
      ) : (
        <div className="space-y-6">
          {weeks.length === 0 ? (
            <EmptyState
              title="No weekly reviews for this account yet."
              detail="The weekly review runs Friday and writes reports/weekly/week_YYYYMMDD.json. Until one exists there is no paper-vs-shadow series to plot — and no verdict either way."
              hint={resource.data?.note ?? undefined}
            />
          ) : (
            <Chart
              title={`${accountName(label)} — weekly divergence`}
              takeaway={takeawayFor(weeks, threshold)}
              mechanics={`Bars are (paper week return − shadow week return) in basis points, one per weekly review on file. The shaded band is the ±${threshold.toFixed(0)} bps policy threshold: inside it an account reads TRACKING, outside it DIVERGING. Amber is deliberate — a DIVERGING week is a question to investigate, not an emergency, and in the one case so far the answer was a measurement artifact rather than a trading fault.`}
              rawHref={`/api/divergence?label=${label}`}
              annotation={
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    {weeks.map((week) => (
                      <span
                        key={`${week.label}-${week.week_ending}`}
                        className="flex items-center gap-2"
                      >
                        <span className="font-mono text-2xs text-muted">
                          {week.week_ending}
                        </span>
                        <VerdictChip verdict={week.verdict} />
                        <span className="font-mono text-2xs tabular-nums text-ink-2">
                          paper {signedPct(week.paper_week_return)} / shadow{' '}
                          {signedPct(week.shadow_week_return)}
                        </span>
                      </span>
                    ))}
                  </div>
                  {weeks.some((w) => w.excluded_tail_days.length > 0) ? (
                    <p
                      className="text-2xs leading-relaxed text-signal-warn"
                      data-testid="excluded-annotation"
                    >
                      ✳ excluded from comparison (no shadow data yet):{' '}
                      {weeks
                        .flatMap((w) =>
                          w.excluded_tail_days.map((d) => `${d} (week ${w.week_ending})`),
                        )
                        .join(', ')}
                      . A paper mark taken before its own session's bar existed has no
                      shadow counterpart, so it is left out of both the weekly and
                      cumulative figures rather than compared against nothing.
                    </p>
                  ) : null}
                </div>
              }
            >
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <CartesianGrid stroke="#e6dcc7" strokeDasharray="2 4" vertical={false} />
                  {/*
                    The ±threshold band. x1/x2 are given explicitly: on a category
                    x-axis a ReferenceArea with only y-bounds computes no x range and
                    silently renders nothing, which is how it went missing the first
                    time. ifOverflow="extendDomain" keeps the band visible even when
                    every bar is small enough to sit inside it.
                  */}
                  {chartData.length > 0 ? (
                    <ReferenceArea
                      x1={chartData[0]!.week}
                      x2={chartData[chartData.length - 1]!.week}
                      y1={-threshold}
                      y2={threshold}
                      fill="#1e5141"
                      fillOpacity={0.06}
                      ifOverflow="extendDomain"
                    />
                  ) : null}
                  <ReferenceLine y={threshold} stroke="#8f5113" strokeDasharray="3 3" />
                  <ReferenceLine y={-threshold} stroke="#8f5113" strokeDasharray="3 3" />
                  <ReferenceLine y={0} stroke="#c9bda3" />
                  <XAxis
                    dataKey="week"
                    tick={{ fill: '#645f4e', fontSize: 11 }}
                    stroke="#c9bda3"
                    tickFormatter={(value: string, index: number) => {
                      const row = chartData[index]
                      return row && row.excluded.length > 0 ? `${value} ✳` : value
                    }}
                  />
                  <YAxis
                    tick={{ fill: '#645f4e', fontSize: 11 }}
                    stroke="#c9bda3"
                    label={{
                      value: 'bps',
                      angle: -90,
                      position: 'insideLeft',
                      fill: '#645f4e',
                      fontSize: 11,
                    }}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#fffdf8',
                      border: '1px solid #3a4150',
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                    labelStyle={{ color: '#221f18' }}
                    formatter={(value: number | string) => [
                      `${Number(value).toFixed(2)} bps`,
                      'divergence',
                    ]}
                  />
                  <Bar dataKey="divergence" radius={[2, 2, 0, 0]}>
                    {chartData.map((row, index) => (
                      <Cell
                        key={index}
                        fill={VERDICT_FILL[row.verdict] ?? VERDICT_FILL.INSUFFICIENT}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Chart>
          )}

          {corrections.length > 0 ? (
            <section>
              <h2 className="mb-3 text-2xs font-medium uppercase tracking-widest text-muted">
                Published figures later re-ruled
              </h2>
              <div className="space-y-3">
                {corrections.map((correction) => (
                  <CorrectionCallout
                    key={`${correction.label}-${correction.week_ending}`}
                    correction={correction}
                  />
                ))}
              </div>
              <p className="mt-3 max-w-3xl text-2xs leading-relaxed text-muted">
                The published reports are left exactly as they were written. A number
                that turned out to be wrong is more useful next to its correction than
                deleted — that pairing is the audit trail.
              </p>
            </section>
          ) : null}

          {structural ? (
            <section>
              <h2 className="mb-2 text-2xs font-medium uppercase tracking-widest text-muted">
                Structural drift for this asset class
              </h2>
              <p
                className="max-w-4xl text-xs leading-relaxed text-muted"
                data-testid="structural-note"
              >
                {structural}
              </p>
            </section>
          ) : null}
        </div>
      )}
    </div>
  )
}
