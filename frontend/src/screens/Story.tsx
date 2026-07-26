/**
 * STORY — the landing page, and the only screen written for someone who has not seen the
 * system before.
 *
 * All prose comes from `content/copy.ts` (canonical, Quant-Lead-approved). `{N}` is
 * substituted with the paper-tracking day count read from the **equity** readiness clock,
 * so the page cannot claim a longer track record than the clock supports. If the clock is
 * unavailable the token renders as an em dash rather than a zero — an unknown day count
 * and a day count of zero are different claims.
 *
 * Glossary terms are marked up with <Term>, which opens on click/focus rather than hover
 * so the definitions are reachable by keyboard and on touch.
 */

import { api } from '../lib/api'
import type { OverviewResponse } from '../lib/api'
import { useApi } from '../lib/useApi'
import { Link } from '../lib/router'
import { Term } from '../components/Term'
import {
  STORY_CTA,
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

/**
 * Wrap known glossary terms in a paragraph with <Term>.
 *
 * Deliberately conservative: only whole-word, case-insensitive matches from a short
 * hand-picked list, and each term is linked at most once per paragraph. Marking up every
 * occurrence would turn the prose into a field of dotted underlines and make the page
 * harder to read than the jargon it was explaining.
 */
const STORY_TERMS = [
  'paper trading',
  'backtest',
  'realized volatility',
  'drawdown',
  'provenance',
] as const

function withTerms(text: string, key: string): React.ReactNode {
  const used = new Set<string>()
  const pattern = new RegExp(`\\b(${STORY_TERMS.join('|')})\\b`, 'gi')
  const parts: React.ReactNode[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    const found = match[0]
    const canonical = found.toLowerCase()
    if (used.has(canonical)) continue
    used.add(canonical)
    if (match.index > cursor) parts.push(text.slice(cursor, match.index))
    parts.push(
      <Term key={`${key}-${match.index}`} term={canonical}>
        {found}
      </Term>,
    )
    cursor = match.index + found.length
  }
  if (parts.length === 0) return text
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts
}

export function Story() {
  const overview = useApi<OverviewResponse>(() => api.overview())
  const days = equityClockDays(overview.data)

  return (
    <div className="space-y-16">
      {/* ---------------------------------------------------------------- hero */}
      <header data-testid="story-hero">
        <p className="eyebrow">{STORY_HERO.eyebrow}</p>
        <h1 className="mt-5 max-w-[22ch] text-[clamp(2.4rem,5.6vw,4rem)] leading-[1.02]">
          {STORY_HERO.headline}
        </h1>
        <div className="mt-7 space-y-4" data-testid="story-hero-body">
          {STORY_HERO.paragraphs.map((paragraph, index) => (
            <p
              key={index}
              className="max-w-measure text-[1.06rem] leading-relaxed text-ink-2"
              data-testid={index === 0 ? 'story-para-1' : 'story-para-2'}
            >
              {withDayCount(paragraph, days)}
            </p>
          ))}
        </div>

        <div className="mt-9 flex flex-wrap gap-3">
          {STORY_HERO.ctas.map((cta) => (
            <Link
              key={cta.to}
              to={cta.to}
              className={`btn ${cta.primary ? 'btn-primary' : 'btn-ghost'}`}
            >
              {cta.label}
            </Link>
          ))}
        </div>
      </header>

      {/* ------------------------------------------------------------ sections */}
      {STORY_SECTIONS.map((section, index) => (
        <section
          key={section.id}
          id={section.id}
          data-testid={`story-section-${section.id}`}
          className="border-t border-ink/[0.10] pt-10"
          aria-labelledby={`${section.id}-heading`}
        >
          <div className="grid gap-x-10 gap-y-4 lg:grid-cols-[5rem_1fr]">
            <p
              aria-hidden
              className="font-mono text-2xs tabular-nums text-clay lg:pt-2"
            >
              {String(index + 1).padStart(2, '0')}
            </p>
            <div>
              <h2
                id={`${section.id}-heading`}
                className="max-w-[30ch] text-[clamp(1.5rem,2.6vw,2.1rem)]"
              >
                {section.title}
              </h2>

              <div className="mt-4 space-y-4">
                {section.body.map((paragraph, i) => (
                  <p key={i} className="max-w-measure leading-relaxed text-ink-2">
                    {withTerms(withDayCount(paragraph, days), `${section.id}-${i}`)}
                  </p>
                ))}
              </div>

              {section.bullets ? (
                <ul className="mt-5 max-w-measure space-y-3">
                  {section.bullets.map((bullet) => (
                    <li key={bullet.term} className="flex gap-3 leading-relaxed">
                      <span aria-hidden className="mt-[0.45em] flex-none text-honey">
                        ·
                      </span>
                      <span className="text-ink-2">
                        <span className="font-display font-semibold text-ink">
                          {bullet.term}
                        </span>{' '}
                        — {withTerms(bullet.rest, bullet.term)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}

              {section.after ? (
                <div className="mt-5 space-y-4">
                  {section.after.map((paragraph, i) => (
                    <p key={i} className="max-w-measure leading-relaxed text-ink-2">
                      {withTerms(paragraph, `${section.id}-after-${i}`)}
                    </p>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      ))}

      {/* ----------------------------------------------------- MonzonAutomation */}
      <section
        id={STORY_CTA.id}
        aria-labelledby="why-this-exists-heading"
        data-testid="story-cta"
        className="rounded-brand-lg bg-green-deep px-7 py-10 sm:px-10 sm:py-12"
      >
        <p
          className="inline-flex items-center gap-[0.7em] font-sans text-2xs font-bold uppercase text-honey-2"
          style={{ letterSpacing: '0.18em' }}
        >
          <span aria-hidden className="h-0.5 w-6 rounded-sm bg-honey" />
          MonzonAutomation
        </p>
        <h2
          id="why-this-exists-heading"
          className="mt-4 max-w-[26ch] text-cream-2 text-[clamp(1.5rem,2.6vw,2.1rem)]"
        >
          {STORY_CTA.title}
        </h2>
        <div className="mt-5 space-y-4">
          {STORY_CTA.body.map((paragraph, i) => (
            <p key={i} className="max-w-measure leading-relaxed text-cream-3">
              {paragraph}
            </p>
          ))}
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          {STORY_CTA.ctas.map((cta) =>
            cta.external ? (
              <a
                key={cta.href}
                href={cta.href}
                className="btn bg-honey text-ink hover:bg-honey-2"
              >
                {cta.label}
              </a>
            ) : (
              <Link
                key={cta.href}
                to={cta.href}
                className="btn border-cream-3/40 bg-transparent text-cream-2 hover:border-cream-2"
              >
                {cta.label}
              </Link>
            ),
          )}
        </div>
      </section>

      {/* The day count is a claim, so its provenance is stated. */}
      <p className="border-t border-ink/[0.10] pt-6 text-2xs leading-relaxed text-muted">
        {days === null
          ? 'Day count unavailable — no readiness clock has been recorded yet.'
          : `Day count (${days}) is the us_equity readiness clock's elapsed days, read from ` +
            'the most recent weekly review. It is not a performance figure.'}
      </p>
    </div>
  )
}
