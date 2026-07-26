/**
 * STORY — the landing page, and the only screen written for someone who has not
 * seen the system before.
 *
 * All prose comes from `content/copy.ts`; nothing is hardcoded here. `{N}` is
 * substituted with the paper-tracking day count read from the **equity** readiness
 * clock, so the page cannot claim a longer track record than the clock supports. If
 * the clock is unavailable the token renders as an em dash rather than a zero — an
 * unknown day count and a day count of zero are different claims.
 */

import { api } from '../lib/api'
import type { OverviewResponse } from '../lib/api'
import { useApi } from '../lib/useApi'
import { Link } from '../lib/router'
import {
  PLACEHOLDER_STORY_COPY,
  STORY_HERO,
  STORY_SECTIONS,
  withDayCount,
} from '../content/copy'

/** Days elapsed on the us_equity clock — the longest-running paper track. */
export function equityClockDays(overview: OverviewResponse | null): number | null {
  if (!overview) return null
  const clocks = overview.accounts
    .map((a) => a.clock)
    .filter((c): c is NonNullable<typeof c> => c !== null && c.asset_class === 'us_equity')
  if (clocks.length === 0) return null
  return Math.max(...clocks.map((c) => c.calendar_days_elapsed))
}

export function Story() {
  const overview = useApi<OverviewResponse>(() => api.overview())
  const days = equityClockDays(overview.data)

  return (
    <div className="space-y-14">
      {PLACEHOLDER_STORY_COPY ? (
        <div
          className="rounded border border-signal-warn/40 bg-signal-warn/5 px-4 py-2 text-2xs leading-relaxed text-signal-warn"
          data-testid="placeholder-copy-warning"
        >
          <strong className="font-semibold">Placeholder copy.</strong> The prose on this
          screen is not the canonical F4 audit text, which was not available when this
          build was made. Replace <code className="font-mono">src/content/copy.ts</code>{' '}
          before any public deploy.
        </div>
      ) : null}

      <header data-testid="story-hero">
        <p className="text-2xs font-medium uppercase tracking-[0.2em] text-signal-idle">
          {STORY_HERO.eyebrow}
        </p>
        <h1 className="mt-4 max-w-4xl text-4xl font-semibold leading-[1.1] tracking-tight text-slate-50 sm:text-5xl">
          {STORY_HERO.headline}
        </h1>
        <p
          className="mt-6 max-w-3xl text-lg leading-relaxed text-slate-300"
          data-testid="story-subhead"
        >
          {withDayCount(STORY_HERO.subhead, days)}
        </p>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-signal-idle">
          {STORY_HERO.standfirst}
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            to="/live"
            className="rounded border border-signal-info/50 bg-signal-info/10 px-4 py-2 text-sm text-slate-100 transition-colors hover:bg-signal-info/20"
          >
            See the live state →
          </Link>
          <Link
            to="/decisions"
            className="rounded border border-ink-500 bg-ink-800 px-4 py-2 text-sm text-signal-idle transition-colors hover:text-slate-200"
          >
            Read a single decision
          </Link>
        </div>
      </header>

      <div className="space-y-12 border-t border-ink-600 pt-12">
        {STORY_SECTIONS.map((section, index) => (
          <section
            key={section.id}
            id={section.id}
            data-testid={`story-section-${section.id}`}
            className="grid gap-x-10 gap-y-4 lg:grid-cols-[8rem_1fr]"
          >
            <div>
              <p className="font-mono text-2xs uppercase tracking-[0.2em] text-signal-idle">
                {section.eyebrow}
              </p>
              <p
                aria-hidden
                className="mt-1 font-mono text-2xs tabular-nums text-ink-400"
              >
                {String(index + 1).padStart(2, '0')}
              </p>
            </div>
            <div className="max-w-3xl">
              <h2 className="text-xl font-medium tracking-tight text-slate-100">
                {section.title}
              </h2>
              <div className="mt-3 space-y-3">
                {section.body.map((paragraph, i) => (
                  <p key={i} className="text-sm leading-relaxed text-slate-400">
                    {withDayCount(paragraph, days)}
                  </p>
                ))}
              </div>
              {section.link ? (
                <Link
                  to={section.link.to}
                  className="mt-4 inline-block font-mono text-2xs text-signal-info underline decoration-dotted underline-offset-4 hover:text-slate-100"
                >
                  {section.link.label} ↗
                </Link>
              ) : null}
            </div>
          </section>
        ))}
      </div>

      {/* The day count is a claim, so its provenance is stated. */}
      <p className="border-t border-ink-600 pt-6 text-2xs leading-relaxed text-signal-idle/70">
        {days === null
          ? 'Day count unavailable — no readiness clock has been recorded yet.'
          : `Day count (${days}) is the us_equity readiness clock's elapsed days, read from ` +
            'the most recent weekly review. It is not a performance figure.'}
      </p>
    </div>
  )
}
