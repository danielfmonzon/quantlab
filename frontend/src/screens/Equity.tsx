/**
 * EQUITY — the curve, with every mark's provenance visible.
 *
 * The legend is not decoration. A series of marks spaced 10 to 33 hours apart looks
 * exactly like clean daily data on a chart, and that resemblance is what produced a
 * false DIVERGING verdict in week 2026-07-24. Colouring each point by how it was
 * produced is the fix, and the legend explains why it matters.
 */

import { useState } from 'react'
import {
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { api } from '../lib/api'
import type { EquityResponse, Provenance } from '../lib/api'
import { ACCOUNTS } from '../lib/api'
import { accountName, money, stamp } from '../lib/format'
import { useApi } from '../lib/useApi'
import { Chart } from '../components/Chart'
import { EmptyState, PROVENANCE_LABEL, SectionHeading } from '../components/primitives'

const PROVENANCE_COLOR: Record<Provenance, string> = {
  on_schedule: '#1e5141',
  catch_up: '#8f5113',
  leaked: '#1d4e6b',
}

export function Equity() {
  const [label, setLabel] = useState<string>(ACCOUNTS[0])
  const resource = useApi<EquityResponse>(() => api.equity(label), [label])

  const series = resource.data?.series.find((s) => s.label === label)
  const points = series?.points ?? []
  const counts = series?.provenance_counts ?? {}
  const offSchedule = (counts.catch_up ?? 0) + (counts.leaked ?? 0)

  const data = points.map((point, index) => ({
    index,
    day: point.timestamp.slice(0, 10),
    at: point.timestamp,
    equity: point.equity,
    provenance: point.provenance,
  }))

  const rationaleFor = (provenance: Provenance): string =>
    points.find((p) => p.provenance === provenance)?.provenance_rationale ?? ''

  const first = points[0]
  const last = points[points.length - 1]
  const totalReturn =
    first && last && first.equity !== 0 ? last.equity / first.equity - 1 : null

  return (
    <div>
      <SectionHeading
        eyebrow="equity"
        title="The curve, and how each point was taken"
        lede="Every point is one equity snapshot written by a paper run. They are not evenly spaced, and the colour tells you which ones fired on schedule."
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
        <EmptyState title="Could not read /api/equity." detail={resource.error} />
      ) : resource.loading ? (
        <p className="text-xs text-muted">reading /api/equity…</p>
      ) : points.length === 0 ? (
        <EmptyState
          title="No equity snapshots for this account yet."
          detail="The paper runner appends one snapshot per run to data/equity_history_<label>.parquet. Until a run completes there is no curve to draw."
          hint={resource.data?.note ?? undefined}
        />
      ) : (
        <div className="space-y-5">
          <Chart
            title={`${accountName(label)} — paper equity`}
            takeaway={
              totalReturn === null
                ? `${points.length} marks on file for ${accountName(label)}.`
                : `${accountName(label)} is ${totalReturn >= 0 ? 'up' : 'down'} ${(Math.abs(totalReturn) * 100).toFixed(2)}% across ${points.length} marks, of which ${offSchedule} did not fire on schedule.`
            }
            mechanics={`Each point is one equity snapshot, plotted in the order it was written — the x-axis is snapshot sequence, not evenly spaced time, because the marks themselves are not evenly spaced. Colour is the provenance the API assigned by comparing each timestamp against the scheduled run time for this asset class.`}
            rawHref={`/api/equity?label=${label}`}
            annotation={
              <div className="space-y-2" data-testid="provenance-legend">
                <div className="flex flex-wrap gap-x-5 gap-y-2">
                  {(['on_schedule', 'catch_up', 'leaked'] as Provenance[]).map((p) => (
                    <span key={p} className="flex items-baseline gap-2">
                      <span
                        className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full"
                        style={{ background: PROVENANCE_COLOR[p] }}
                        aria-hidden
                      />
                      <span className="text-2xs text-ink-2">
                        {PROVENANCE_LABEL[p]}
                        <span className="ml-1 font-mono tabular-nums text-muted">
                          ×{counts[p] ?? 0}
                        </span>
                      </span>
                    </span>
                  ))}
                </div>
                <p className="max-w-4xl text-2xs leading-relaxed text-muted">
                  <span className="text-ink-2">Why provenance matters: </span>
                  {rationaleFor('catch_up') ||
                    'A catch-up run produces a real mark whose spacing from its neighbours is not one uniform session, so a "daily" return computed from it covers the wrong window.'}
                </p>
              </div>
            }
          >
            <ResponsiveContainer width="100%" height={260}>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                <CartesianGrid stroke="#e6dcc7" strokeDasharray="2 4" />
                <XAxis
                  dataKey="index"
                  type="number"
                  domain={[0, Math.max(0, data.length - 1)]}
                  tick={{ fill: '#645f4e', fontSize: 11 }}
                  stroke="#c9bda3"
                  tickFormatter={(i: number) => data[i]?.day ?? ''}
                />
                <YAxis
                  dataKey="equity"
                  type="number"
                  domain={['dataMin - 500', 'dataMax + 500']}
                  tick={{ fill: '#645f4e', fontSize: 11 }}
                  stroke="#c9bda3"
                  tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}k`}
                />
                <ZAxis range={[46, 46]} />
                <Tooltip
                  contentStyle={{
                    background: '#fffdf8',
                    border: '1px solid #3a4150',
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  formatter={(value: number | string, name: string) =>
                    name === 'equity' ? [money(Number(value)), 'equity'] : [String(value), name]
                  }
                  labelFormatter={(i) => stamp(data[Number(i)]?.at)}
                />
                {/* One line through every point, then coloured points on top. */}
                <Line
                  data={data}
                  dataKey="equity"
                  type="linear"
                  stroke="#c9bda3"
                  strokeWidth={1}
                  dot={false}
                  isAnimationActive={false}
                  legendType="none"
                />
                {(['on_schedule', 'catch_up', 'leaked'] as Provenance[]).map((p) => (
                  <Scatter
                    key={p}
                    name={PROVENANCE_LABEL[p]}
                    data={data.filter((d) => d.provenance === p)}
                    fill={PROVENANCE_COLOR[p]}
                    isAnimationActive={false}
                  />
                ))}
              </ScatterChart>
            </ResponsiveContainer>
          </Chart>

          <details className="rounded-brand border border-ink/[0.16] bg-cream-2 px-5 py-3">
            <summary className="cursor-pointer text-2xs font-medium uppercase tracking-widest text-muted hover:text-ink-2">
              every mark, with its provenance ({points.length})
            </summary>
            <table className="mt-3 w-full text-left font-mono text-2xs tabular-nums">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-4 font-normal">snapshot (UTC)</th>
                  <th className="py-1 pr-4 font-normal">equity</th>
                  <th className="py-1 font-normal">provenance</th>
                </tr>
              </thead>
              <tbody className="text-ink-2">
                {points.map((point) => (
                  <tr key={point.timestamp} className="border-t border-ink/[0.10]">
                    <td className="py-1 pr-4">{stamp(point.timestamp)}</td>
                    <td className="py-1 pr-4">{money(point.equity)}</td>
                    <td className="py-1" style={{ color: PROVENANCE_COLOR[point.provenance] }}>
                      {PROVENANCE_LABEL[point.provenance]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}
    </div>
  )
}
