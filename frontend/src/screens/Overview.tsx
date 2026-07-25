/**
 * OVERVIEW — the front door. Its thesis sentence is the product's whole claim, so
 * it gets the largest type on the page and nothing competes with it.
 */

import { api } from '../lib/api'
import type { OverviewResponse, TimelineResponse } from '../lib/api'
import { accountName, money, stamp } from '../lib/format'
import { useApi } from '../lib/useApi'
import {
  ClockBar,
  EmptyState,
  KillSwitchBadge,
  Metric,
  Panel,
  ProvenanceBadge,
  TierBadge,
} from '../components/primitives'
import { Link } from '../lib/router'

export const HERO_SENTENCE =
  'Every decision this system makes is arithmetic you can check.'

const isToday = (iso: string | null): boolean => {
  if (!iso) return false
  const today = new Date().toISOString().slice(0, 10)
  return iso.slice(0, 10) === today
}

export function Overview() {
  const overview = useApi<OverviewResponse>(() => api.overview())
  const timeline = useApi<TimelineResponse>(() => api.timeline(500))

  const accounts = overview.data?.accounts ?? []
  const todays = (timeline.data?.events ?? []).filter((e) => isToday(e.at))

  return (
    <div className="space-y-8">
      {/* Hero. The claim, then the qualifier that makes it checkable. */}
      <header className="border-b border-ink-600 pb-8">
        <p className="text-2xs font-medium uppercase tracking-[0.2em] text-signal-idle">
          quantlab glass box
        </p>
        <h1
          className="mt-3 max-w-4xl text-3xl font-semibold leading-tight tracking-tight text-slate-50 sm:text-4xl"
          data-testid="hero"
        >
          {HERO_SENTENCE}
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-slate-400">
          Paper trading only. Every figure below is read from a file this system
          wrote — no estimates, no commentary, and nothing that cannot be traced to
          a run report, a weekly review, or a config file.
        </p>
      </header>

      {/* What changed today. */}
      <Panel
        title="What changed today"
        subtitle={
          todays.length > 0
            ? `${todays.length} event${todays.length === 1 ? '' : 's'} recorded today`
            : undefined
        }
        actions={
          <Link
            to="/ledger"
            className="font-mono text-2xs text-signal-info underline decoration-dotted underline-offset-4"
          >
            full ledger ↗
          </Link>
        }
      >
        {timeline.loading ? (
          <p className="text-xs text-signal-idle">reading /api/timeline…</p>
        ) : todays.length === 0 ? (
          <EmptyState
            title="Nothing has happened today."
            detail="No orders, alerts, weekly verdicts, or decisions carry today's date. On a weekend or before the 10:00 ET run, that is the expected state."
          />
        ) : (
          <ul className="divide-y divide-ink-600" data-testid="today-strip">
            {todays.slice(0, 8).map((event, i) => (
              <li
                key={`${event.kind}-${i}`}
                className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 first:pt-0 last:pb-0"
              >
                <span className="w-16 shrink-0 font-mono text-2xs uppercase text-signal-idle">
                  {event.kind === 'weekly_verdict' ? 'weekly' : event.kind}
                </span>
                <span className="min-w-0 flex-1 text-sm text-slate-200">{event.title}</span>
                {event.label ? (
                  <span className="font-mono text-2xs text-signal-idle">{event.label}</span>
                ) : null}
                <span className="font-mono text-2xs tabular-nums text-signal-idle/70">
                  {event.at ? stamp(event.at).slice(11) : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {/* Accounts. */}
      <section>
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-2xs font-medium uppercase tracking-widest text-signal-idle">
            Accounts
          </h2>
          {overview.data?.week_ending ? (
            <p className="font-mono text-2xs text-signal-idle">
              clocks as of week ending {overview.data.week_ending}
            </p>
          ) : null}
        </div>

        {overview.error ? (
          <EmptyState
            title="Could not read /api/overview."
            detail={overview.error}
            hint="Is `quantlab glassbox serve` running?"
          />
        ) : accounts.length === 0 && !overview.loading ? (
          <EmptyState
            title="No accounts configured."
            detail="The approved roster is empty, so there is nothing to report."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {accounts.map((account) => (
              <article
                key={account.label}
                className="rounded-lg border border-ink-500 bg-ink-800 p-5"
                data-testid={`account-card-${account.label}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-medium tracking-tight text-slate-100">
                      {accountName(account.label)}
                    </h3>
                    <p className="mt-0.5 font-mono text-2xs uppercase tracking-wider text-signal-idle">
                      {account.asset_class}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <TierBadge
                      tier={account.validation_tier}
                      rationale={account.validation_tier_rationale}
                      upgradeCondition={account.validation_tier_upgrade_condition}
                    />
                    <KillSwitchBadge
                      halted={account.risk.halted}
                      reason={account.risk.reason}
                      requiresManualReset={account.risk.requires_manual_reset}
                    />
                  </div>
                </div>

                <dl className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <Metric
                    label="equity"
                    value={
                      account.latest_equity === null ? (
                        <span className="text-signal-idle">no marks yet</span>
                      ) : (
                        money(account.latest_equity)
                      )
                    }
                  />
                  <Metric
                    label="last mark"
                    value={
                      <span className="text-xs">{stamp(account.latest_snapshot_at)}</span>
                    }
                  />
                  <Metric
                    label="marks"
                    value={account.snapshot_count}
                    hint={`${account.snapshot_count} snapshot${account.snapshot_count === 1 ? '' : 's'} on file`}
                  />
                </dl>

                <div className="mt-4">
                  <ProvenanceBadge
                    provenance={account.latest_snapshot_provenance}
                    title="How the most recent equity mark was produced."
                  />
                </div>

                {account.clock ? (
                  <div className="mt-5 border-t border-ink-600 pt-4">
                    <p className="mb-2 text-2xs uppercase tracking-widest text-signal-idle">
                      readiness clock ({account.clock.asset_class})
                    </p>
                    <ClockBar clock={account.clock} />
                    {account.clock.start_note ? (
                      <p className="mt-2 text-2xs leading-relaxed text-signal-warn/80">
                        {account.clock.start_note}
                      </p>
                    ) : null}
                    {account.clock.blockers.length > 0 ? (
                      <ul
                        className="mt-3 space-y-1"
                        data-testid={`blockers-${account.label}`}
                      >
                        {account.clock.blockers.map((blocker) => (
                          <li
                            key={blocker}
                            className="flex gap-2 text-2xs leading-relaxed text-signal-warn"
                          >
                            <span aria-hidden>▸</span>
                            <span>{blocker}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-3 text-2xs text-signal-ok/80">
                        no blockers recorded for this account
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="mt-5 border-t border-ink-600 pt-4">
                    <p className="text-2xs leading-relaxed text-signal-idle">
                      No readiness clock yet — a weekly review has to run before the
                      90-day gate can be measured.
                    </p>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
