/**
 * Every screen, rendered twice: against populated fixtures and against the empty
 * responses a repo with no artifacts produces. The empty pass is the important one
 * — a blank panel is the failure mode this app exists to avoid.
 */

import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'

import { App } from '../src/App'
import { RouterProvider } from '../src/lib/router'
import { Divergence } from '../src/screens/Divergence'
import { Equity } from '../src/screens/Equity'
import { Glass } from '../src/screens/Glass'
import { Ledger } from '../src/screens/Ledger'
import { HERO_SENTENCE, Overview } from '../src/screens/Overview'
import { Risk } from '../src/screens/Risk'
import { Runs } from '../src/screens/Runs'
import { EMPTY, POPULATED, mockApi } from './fixtures'

const mount = (element: ReactElement, path = '/') =>
  render(<RouterProvider initialPath={path}>{element}</RouterProvider>)

const SCREENS: Array<{ name: string; element: ReactElement; path: string }> = [
  { name: 'Overview', element: <Overview />, path: '/' },
  { name: 'Runs', element: <Runs />, path: '/runs' },
  { name: 'Divergence', element: <Divergence />, path: '/divergence' },
  { name: 'Risk', element: <Risk />, path: '/risk' },
  { name: 'Equity', element: <Equity />, path: '/equity' },
  { name: 'Ledger', element: <Ledger />, path: '/ledger' },
  { name: 'Glass', element: <Glass />, path: '/glass' },
]

// --------------------------------------------------------------------------- //
// Smoke: every screen renders under both data conditions                      //
// --------------------------------------------------------------------------- //

describe.each(SCREENS)('$name screen', ({ element, path }) => {
  it('renders against populated fixtures', async () => {
    mockApi(POPULATED)
    mount(element, path)
    await waitFor(() => {
      expect(screen.queryByText(/^reading \/api/)).not.toBeInTheDocument()
    })
    expect(document.body.textContent?.trim().length ?? 0).toBeGreaterThan(80)
  })

  it('renders an explicit empty state against an empty tree', async () => {
    mockApi(EMPTY)
    mount(element, path)
    await waitFor(() => {
      expect(screen.queryByText(/^reading \/api/)).not.toBeInTheDocument()
    })
    // Something meaningful is on screen, and nothing threw.
    expect(document.body.textContent?.trim().length ?? 0).toBeGreaterThan(80)
  })
})

// --------------------------------------------------------------------------- //
// Overview                                                                    //
// --------------------------------------------------------------------------- //

describe('Overview', () => {
  it('leads with the thesis sentence', async () => {
    mockApi(POPULATED)
    mount(<Overview />)
    expect(await screen.findByTestId('hero')).toHaveTextContent(HERO_SENTENCE)
  })

  it('shows equity, provenance, tier and clock per account', async () => {
    mockApi(POPULATED)
    mount(<Overview />)
    const card = await screen.findByTestId('account-card-voltarget')
    expect(card).toHaveTextContent('$98,821.82')
    expect(within(card).getByTestId('provenance-on_schedule')).toBeInTheDocument()
    expect(within(card).getByTestId('clock-bar')).toHaveTextContent('day')
    expect(within(card).getByTestId('clock-bar')).toHaveTextContent('90')
    expect(within(card).getByTestId('tier-badge')).toHaveTextContent('Probable')
  })

  it('reveals the tier upgrade condition on hover', async () => {
    mockApi(POPULATED)
    mount(<Overview />)
    const card = await screen.findByTestId('account-card-voltarget')
    const badge = within(card).getByTestId('tier-badge')
    // Available without JS interaction too, via the native title.
    expect(badge).toHaveAttribute('title', expect.stringContaining('2026-10-07'))
    await userEvent.hover(badge)
    expect(within(card).getByTestId('tier-tooltip')).toHaveTextContent('2026-10-07')
    expect(within(card).getByTestId('tier-tooltip')).toHaveTextContent('To upgrade')
  })

  it('renders blockers inline and a halted account prominently', async () => {
    mockApi(POPULATED)
    mount(<Overview />)
    expect(await screen.findByTestId('blockers-voltarget')).toHaveTextContent(
      'trend: DIVERGING week',
    )
    const crypto = screen.getByTestId('account-card-crypto_voltarget')
    expect(within(crypto).getByTestId('kill-active')).toHaveTextContent(
      /manual reset required/i,
    )
  })

  it("shows today's events in the what-changed strip", async () => {
    mockApi(POPULATED)
    mount(<Overview />)
    const strip = await screen.findByTestId('today-strip')
    expect(strip).toHaveTextContent('sell SPY')
    // The 2026-07-24 weekly verdict is not today, so it is excluded.
    expect(strip).not.toHaveTextContent('week 2026-07-24')
  })

  it('says nothing happened today when no event carries today\'s date', async () => {
    mockApi(EMPTY)
    mount(<Overview />)
    expect(await screen.findByText(/Nothing has happened today/)).toBeInTheDocument()
  })

  it('reports unknown equity as such rather than as zero', async () => {
    mockApi(EMPTY)
    mount(<Overview />)
    const card = await screen.findByTestId('account-card-voltarget')
    expect(card).toHaveTextContent('no marks yet')
    expect(card).not.toHaveTextContent('$0.00')
    expect(within(card).queryByTestId('clock-bar')).not.toBeInTheDocument()
    expect(card).toHaveTextContent(/No readiness clock yet/)
  })
})

// --------------------------------------------------------------------------- //
// Runs — the three-layer disclosure                                           //
// --------------------------------------------------------------------------- //

describe('Runs', () => {
  it('lists runs with a stage checklist and abort state', async () => {
    mockApi(POPULATED)
    mount(<Runs />, '/runs')
    const good = await screen.findByTestId('run-run_voltarget_20260724T140007Z')
    expect(within(good).getByTestId('stage-checklist')).toHaveTextContent('risk_state')
    expect(within(good).getAllByTestId('stage-ok')).toHaveLength(2)

    const aborted = screen.getByTestId('run-run_trend_20260722T140028Z')
    expect(within(aborted).getByTestId('run-aborted')).toHaveTextContent('health')
    expect(within(aborted).getByTestId('stage-failed')).toBeInTheDocument()
    expect(aborted).toHaveTextContent('FREEZE_STALE_DATA')
  })

  it('renders the narration and exposes each fact source path on hover', async () => {
    mockApi(POPULATED)
    mount(<Runs />, '/runs')
    await userEvent.click(
      await screen.findByTestId('explain-run_voltarget_20260724T140007Z'),
    )

    const narration = await screen.findByTestId('narration')
    expect(narration).toHaveTextContent('$98,821.82')

    const facts = within(narration).getAllByTestId('narration-fact')
    expect(facts.length).toBeGreaterThanOrEqual(5)

    // Layer 2: each hoverable number carries the JSON path it came from.
    const sources = facts.map((f) => f.getAttribute('data-source'))
    expect(sources).toContain('report.equity')
    expect(sources).toContain('report.plan.intents[0].notional')
    expect(sources).toContain('report.plan.est_turnover')

    // textContent includes the nested tooltip, so select by source and match the
    // leading rendered value.
    const equityFact = facts.find((f) => f.getAttribute('data-source') === 'report.equity')!
    expect(equityFact.textContent).toMatch(/^\$98,821\.82/)
    expect(equityFact).toHaveAttribute('title', 'source: report.equity')
    await userEvent.hover(equityFact)
    expect(within(equityFact).getByTestId('fact-source')).toHaveTextContent('report.equity')
  })

  it('renders the counterfactual in a distinct "what it did NOT do" block', async () => {
    mockApi(POPULATED)
    mount(<Runs />, '/runs')
    await userEvent.click(
      await screen.findByTestId('explain-run_voltarget_20260724T140007Z'),
    )
    const block = await screen.findByTestId('counterfactual-block')
    expect(block).toHaveTextContent(/What it did NOT do/i)
    expect(block).toHaveTextContent('would have left the position to drift untouched')
    // Facts inside the counterfactual are annotated too.
    const sources = within(block)
      .getAllByTestId('narration-fact')
      .map((f) => f.getAttribute('data-source'))
    expect(sources).toContain('report.plan.min_trade_frac')
  })

  it('keeps the raw report behind a collapsed disclosure', async () => {
    mockApi(POPULATED)
    mount(<Runs />, '/runs')
    await userEvent.click(
      await screen.findByTestId('explain-run_voltarget_20260724T140007Z'),
    )
    const summary = await screen.findByText(/raw run report \(JSON\)/)
    const details = summary.closest('details')!
    expect(details.open).toBe(false)
  })

  it('never invents a source path for an undeclared number', async () => {
    mockApi({
      ...POPULATED,
      narrate: { ...POPULATED.narrate, narration: 'Equity was $98,821.82 and 42 widgets.', facts: [POPULATED.narrate.facts[0]!] },
    })
    mount(<Runs />, '/runs')
    await userEvent.click(
      await screen.findByTestId('explain-run_voltarget_20260724T140007Z'),
    )
    const narration = await screen.findByTestId('narration')
    const facts = within(narration).getAllByTestId('narration-fact')
    expect(facts).toHaveLength(1)
    // "42" was not declared, so it renders as plain text with no source at all.
    expect(facts[0]!.textContent).toMatch(/^\$98,821\.82/)
    expect(facts[0]!.getAttribute('data-source')).toBe('report.equity')
    expect(narration).toHaveTextContent('42 widgets')
    const annotated = facts.map((f) => f.getAttribute('data-source'))
    expect(annotated).not.toContain(null)
  })

  it('does not match a bare numeric fact inside a longer number', async () => {
    /**
     * Regression: rendering against the live API showed the bare fact `20`
     * (voltarget's lookback_days) matching inside the run id `20260724T140007Z` and
     * inside the timestamp `2026-07-24`, shredding the sentence. Bare numeric facts
     * must only match as standalone tokens.
     */
    mockApi({
      ...POPULATED,
      narrate: {
        ...POPULATED.narrate,
        narration:
          'Run run_voltarget_20260724T140007Z executed at 2026-07-24T14:00:07Z using ' +
          'a trailing 20-day window annualized on a 252-day year, capped at 100% of equity.',
        facts: [
          { rendered: '20', value: 20, source: 'rule_constant.voltarget.lookback_days' },
          { rendered: '252', value: 252, source: 'rule_constant.voltarget.periods_per_year' },
          { rendered: '100%', value: 1, source: 'rule_constant.voltarget.max_weight' },
        ],
      },
    })
    mount(<Runs />, '/runs')
    await userEvent.click(
      await screen.findByTestId('explain-run_voltarget_20260724T140007Z'),
    )
    const narration = await screen.findByTestId('narration')

    // The run id and timestamp survive intact.
    expect(narration).toHaveTextContent('run_voltarget_20260724T140007Z')
    expect(narration).toHaveTextContent('2026-07-24T14:00:07Z')

    const facts = within(narration).getAllByTestId('narration-fact')
    const rendered = facts.map((f) => f.firstChild?.textContent)
    // Exactly one `20` (the lookback), one `252`, one `100%` — none from inside
    // the id or the timestamp.
    expect(rendered.filter((r) => r === '20')).toHaveLength(1)
    expect(rendered.filter((r) => r === '252')).toHaveLength(1)
    expect(rendered.filter((r) => r === '100%')).toHaveLength(1)
    expect(facts).toHaveLength(3)
  })

  it('explains an empty run list rather than showing a blank page', async () => {
    mockApi(EMPTY)
    mount(<Runs />, '/runs')
    expect(await screen.findByTestId('empty-state')).toHaveTextContent(
      /No run reports on file/,
    )
  })
})

// --------------------------------------------------------------------------- //
// Divergence                                                                  //
// --------------------------------------------------------------------------- //

describe('Divergence', () => {
  const showTrend = async () => {
    mount(<Divergence />, '/divergence')
    await userEvent.click(await screen.findByRole('button', { name: 'trend' }))
  }

  it('renders the chart with its takeaway, mechanics and raw link', async () => {
    mockApi(POPULATED)
    await showTrend()
    const chart = await screen.findByTestId('chart')
    expect(within(chart).getByTestId('chart-takeaway').textContent?.trim().length).toBeGreaterThan(10)
    expect(within(chart).getByTestId('chart-mechanics').textContent).toMatch(/basis points/)
    expect(within(chart).getByTestId('chart-raw-link')).toHaveAttribute(
      'href',
      '/api/divergence?label=trend',
    )
  })

  it('renders BOTH the published and corrected figures with the ruling', async () => {
    mockApi(POPULATED)
    await showTrend()
    const correction = await screen.findByTestId('correction-trend-2026-07-24')
    expect(correction).toHaveTextContent('-54.33 bps')  // published
    expect(within(correction).getByTestId('corrected-value')).toHaveTextContent('-6.06 bps')
    expect(correction).toHaveTextContent('DIVERGING')
    expect(within(correction).getByTestId('verdict-TRACKING')).toBeInTheDocument()
    expect(correction).toHaveTextContent('re-ruled: see decision 2026-07-25')
    expect(correction).toHaveTextContent('2026-07-16 -> 2026-07-23')
  })

  it('annotates excluded_tail_days and captions the amber convention', async () => {
    mockApi(POPULATED)
    await showTrend()
    expect(await screen.findByTestId('excluded-annotation')).toHaveTextContent('2026-07-24')
    const chart = screen.getByTestId('chart')
    // The caption must say a DIVERGING week is a question, not an emergency.
    expect(within(chart).getByTestId('chart-mechanics')).toHaveTextContent(
      /question to investigate, not an emergency/,
    )
  })

  it('shades the ±threshold band and draws its boundary lines', async () => {
    /**
     * Regression: a ReferenceArea with only y-bounds computes no x range on a
     * category axis and renders NOTHING, so the band was silently absent while the
     * boundary lines drew fine. Assert the shaded area actually exists.
     */
    mockApi(POPULATED)
    await showTrend()
    await screen.findByTestId('chart')
    expect(document.querySelectorAll('.recharts-reference-area').length).toBe(1)
    // ±50 bps boundaries plus the zero line.
    expect(document.querySelectorAll('.recharts-reference-line').length).toBe(3)
    expect(document.querySelectorAll('.recharts-bar-rectangle').length).toBe(2)
  })

  it('shows the structural note as the chart caption context', async () => {
    mockApi(POPULATED)
    await showTrend()
    expect(await screen.findByTestId('structural-note')).toHaveTextContent(
      /does not credit cash dividends/,
    )
  })

  it('renders verdict chips in the amber/green/gray scheme', async () => {
    mockApi(POPULATED)
    await showTrend()
    expect((await screen.findAllByTestId('verdict-TRACKING')).length).toBeGreaterThan(0)
  })

  it('explains an absent weekly series', async () => {
    mockApi(EMPTY)
    mount(<Divergence />, '/divergence')
    expect(await screen.findByTestId('empty-state')).toHaveTextContent(
      /No weekly reviews for this account yet/,
    )
  })
})

// --------------------------------------------------------------------------- //
// Risk                                                                        //
// --------------------------------------------------------------------------- //

describe('Risk', () => {
  it('answers "should I be worried?" from the thresholds', async () => {
    mockApi(POPULATED)
    mount(<Risk />, '/risk')
    const calm = await screen.findByTestId('worry-voltarget')
    expect(calm).toHaveTextContent(/^Should I be worried\? No —/)
    expect(calm).toHaveTextContent('would need a further -23.22% from here to trigger the kill switch')

    // A 40% drawdown against a 50% kill limit is 80% of the budget: worried.
    const worried = screen.getByTestId('worry-crypto_voltarget')
    expect(worried).toHaveTextContent(/Yes — the kill switch is ACTIVE/)
  })

  it('renders a gauge scaled to the kill threshold', async () => {
    mockApi(POPULATED)
    mount(<Risk />, '/risk')
    const gauge = await screen.findByTestId('gauge-voltarget')
    expect(gauge).toHaveTextContent('-25.00%') // kill limit
    expect(gauge).toHaveTextContent('-1.78%') // current drawdown
    const fill = screen.getByTestId('gauge-fill-voltarget')
    // 1.781 / 25 ≈ 7.1% of the budget consumed.
    expect(fill.style.width).toMatch(/^7\.\d+%$/)
  })

  it('names the yaml each limit set came from', async () => {
    mockApi(POPULATED)
    mount(<Risk />, '/risk')
    expect(await screen.findByText(/limits read from risk\.yaml/)).toBeInTheDocument()
    expect(screen.getByText(/limits read from crypto_risk\.yaml/)).toBeInTheDocument()
  })

  it('says drawdown is unknown rather than zero when there is no history', async () => {
    mockApi(EMPTY)
    mount(<Risk />, '/risk')
    const caption = await screen.findByTestId('worry-voltarget')
    expect(caption).toHaveTextContent(/Unknown — there is not enough equity history/)
    expect(screen.getByText(/limits read from risk\.yaml \(absent\)/)).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// Equity                                                                      //
// --------------------------------------------------------------------------- //

describe('Equity', () => {
  it('colours points by provenance and explains why it matters', async () => {
    mockApi(POPULATED)
    mount(<Equity />, '/equity')
    await userEvent.click(await screen.findByRole('button', { name: 'crypto voltarget' }))

    const legend = await screen.findByTestId('provenance-legend')
    expect(legend).toHaveTextContent('on schedule')
    expect(legend).toHaveTextContent('catch-up')
    expect(legend).toHaveTextContent('leaked task')
    expect(legend).toHaveTextContent(/Why provenance matters/)
    expect(legend).toHaveTextContent(/catch-up run/i)
  })

  it('states the takeaway including how many marks were off schedule', async () => {
    mockApi(POPULATED)
    mount(<Equity />, '/equity')
    await userEvent.click(await screen.findByRole('button', { name: 'crypto voltarget' }))
    const takeaway = await screen.findByTestId('chart-takeaway')
    expect(takeaway).toHaveTextContent(/did not fire on schedule/)
  })

  it('explains an absent curve', async () => {
    mockApi(EMPTY)
    mount(<Equity />, '/equity')
    expect(await screen.findByTestId('empty-state')).toHaveTextContent(
      /No equity snapshots for this account yet/,
    )
  })
})

// --------------------------------------------------------------------------- //
// Ledger                                                                      //
// --------------------------------------------------------------------------- //

describe('Ledger', () => {
  it('merges all four event kinds and filters them', async () => {
    mockApi(POPULATED)
    mount(<Ledger />, '/ledger')
    await screen.findByTestId('ledger-list')
    expect(screen.getByTestId('ledger-order')).toBeInTheDocument()
    expect(screen.getByTestId('ledger-alert')).toHaveTextContent('WARNING')
    expect(screen.getByTestId('ledger-weekly_verdict')).toHaveTextContent('TRACKING')
    expect(screen.getByTestId('ledger-decision')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'orders' }))
    expect(screen.queryByTestId('ledger-order')).not.toBeInTheDocument()
    expect(screen.getByTestId('ledger-alert')).toBeInTheDocument()
  })

  it('expands a decision to its full body', async () => {
    mockApi(POPULATED)
    mount(<Ledger />, '/ledger')
    await userEvent.click(await screen.findByText(/read the ruling/))
    expect(screen.getByTestId('decision-body')).toHaveTextContent(
      'Narration is template-bound',
    )
  })

  it('explains an empty ledger', async () => {
    mockApi(EMPTY)
    mount(<Ledger />, '/ledger')
    expect(await screen.findByTestId('empty-state')).toHaveTextContent(
      /Nothing has been recorded yet/,
    )
  })
})

// --------------------------------------------------------------------------- //
// Glass — the trust thesis                                                    //
// --------------------------------------------------------------------------- //

describe('Glass', () => {
  it('renders both columns with rationales inline', async () => {
    mockApi(POPULATED)
    mount(<Glass />, '/glass')
    const reads = await screen.findByTestId('inputs-read')
    expect(reads).toHaveTextContent('Tiingo end-of-day bars')
    expect(reads).toHaveTextContent('Alpaca IEX end-of-day bars')
    expect(reads).toHaveTextContent(/cross-check/)

    const ignores = screen.getByTestId('inputs-ignored')
    expect(ignores).toHaveTextContent('News and headlines')
    expect(ignores).toHaveTextContent(/large-language-model judgement/)
    expect(ignores).toHaveTextContent('No strategy has a news term')
  })

  it('carries the same hero weight as Overview', async () => {
    mockApi(POPULATED)
    mount(<Glass />, '/glass')
    const heading = await screen.findByRole('heading', { level: 1 })
    expect(heading).toHaveTextContent('What it knows, and what it refuses to know.')
    expect(heading.className).toMatch(/text-3xl/)
  })

  it('renders with no declared inputs at all', async () => {
    mockApi(EMPTY)
    mount(<Glass />, '/glass')
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(screen.getAllByTestId('empty-state').length).toBe(2)
  })
})

// --------------------------------------------------------------------------- //
// Shell / routing                                                             //
// --------------------------------------------------------------------------- //

describe('App shell', () => {
  it('navigates between screens without a reload', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    expect(await screen.findByTestId('hero')).toBeInTheDocument()

    // Exact name: the brand link is "quantlab Glass Box", the nav link is "Glass".
    await userEvent.click(screen.getByRole('link', { name: 'Glass' }))
    expect(
      await screen.findByRole('heading', { level: 1, name: /refuses to know/ }),
    ).toBeInTheDocument()
  })

  it('falls back to Overview for an unknown path', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/not-a-route">
        <App />
      </RouterProvider>,
    )
    expect(await screen.findByTestId('hero')).toBeInTheDocument()
  })

  it('states that the interface is read-only', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    expect(
      await screen.findByText(/cannot place, cancel, or halt anything/),
    ).toBeInTheDocument()
  })
})
