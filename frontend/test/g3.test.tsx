/**
 * G3: pagination and the pre-expanded newest run, the build-process panel, the "I" copy
 * fix, and the prerendered index.html.
 *
 * The prerender test reads `dist/index.html` off disk rather than mocking anything: the
 * requirement is about what a client that never runs JavaScript receives, and only the
 * real build artifact can answer that.
 */

import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { RouterProvider } from '../src/lib/router'
import { Runs } from '../src/screens/Runs'
import { Story } from '../src/screens/Story'
import { BUILD_PROCESS, DISCLAIMER, STORY_CTA, STORY_HERO } from '../src/content/copy'
import { POPULATED, mockApi } from './fixtures'
import type { RunView } from '../src/lib/api'

const mount = (element: React.ReactElement, path_ = '/') =>
  render(<RouterProvider initialPath={path_}>{element}</RouterProvider>)

/** 25 synthetic runs, newest first, so pagination has something to page. */
function manyRuns(n: number): RunView[] {
  const base = POPULATED.runs.runs[0]!
  return Array.from({ length: n }, (_, i) => ({
    ...base,
    run_id: `run_voltarget_2026072${(9 - (i % 9)).toString()}T14000${i % 10}Z`,
    timestamp: new Date(Date.UTC(2026, 6, 26, 14, 0, 0) - i * 86_400_000).toISOString(),
  }))
}

// --------------------------------------------------------------------------- //
// ITEM 4 — reading experience on /decisions                                   //
// --------------------------------------------------------------------------- //

describe('/decisions pagination', () => {
  const withRuns = (n: number) =>
    mockApi({ ...POPULATED, runs: { ...POPULATED.runs, count: n, runs: manyRuns(n) } })

  it('renders only the 10 most recent runs', async () => {
    withRuns(25)
    mount(<Runs />, '/decisions')
    await screen.findByTestId('runs-count')
    expect(screen.getAllByTestId(/^run-run_/)).toHaveLength(10)
    expect(screen.getByTestId('runs-count')).toHaveTextContent('showing 10 of 25')
  })

  it('appends the next 10 on Show more', async () => {
    withRuns(25)
    mount(<Runs />, '/decisions')
    await screen.findByTestId('show-more-runs')

    await userEvent.click(screen.getByTestId('show-more-runs'))
    expect(screen.getAllByTestId(/^run-run_/)).toHaveLength(20)
    expect(screen.getByTestId('runs-count')).toHaveTextContent('showing 20 of 25')

    // The last page is partial, and the button says how many are left.
    expect(screen.getByTestId('show-more-runs')).toHaveTextContent('Show 5 more')
    await userEvent.click(screen.getByTestId('show-more-runs'))
    expect(screen.getAllByTestId(/^run-run_/)).toHaveLength(25)
    expect(screen.queryByTestId('show-more-runs')).not.toBeInTheDocument()
    expect(screen.getByTestId('runs-all-shown')).toBeInTheDocument()
  })

  it('shows no Show-more button when everything already fits', async () => {
    withRuns(4)
    mount(<Runs />, '/decisions')
    await screen.findByTestId('runs-count')
    expect(screen.queryByTestId('show-more-runs')).not.toBeInTheDocument()
    expect(screen.getByTestId('runs-all-shown')).toBeInTheDocument()
  })

  it('renders the NEWEST run expanded, with its narration visible', async () => {
    /**
     * The narration is the product — the thing this site exists to demonstrate. Requiring
     * a click meant the most important feature was invisible on arrival.
     */
    withRuns(25)
    mount(<Runs />, '/decisions')
    const narration = await screen.findByTestId('narration')
    expect(narration).toHaveTextContent('$98,821.82')
    // Exactly one is open: the rest still offer their button.
    expect(screen.getAllByTestId('narration')).toHaveLength(1)
    expect(screen.getAllByText('Explain this run')).toHaveLength(9)
  })

  it('the expanded run is the first card, not an arbitrary one', async () => {
    withRuns(25)
    mount(<Runs />, '/decisions')
    await screen.findByTestId('narration')
    const cards = screen.getAllByTestId(/^run-run_/)
    expect(within(cards[0]!).getByTestId('narration')).toBeInTheDocument()
    expect(within(cards[1]!).queryByTestId('narration')).not.toBeInTheDocument()
  })

  it('resets to the first page when the filter changes', async () => {
    withRuns(25)
    mount(<Runs />, '/decisions')
    await userEvent.click(await screen.findByTestId('show-more-runs'))
    expect(screen.getAllByTestId(/^run-run_/)).toHaveLength(20)

    await userEvent.click(screen.getByRole('button', { name: 'voltarget' }))
    // Keeping a deep offset across filters shows rows nobody asked to scroll past.
    expect(screen.getAllByTestId(/^run-run_/)).toHaveLength(10)
  })

  it('keeps the filter chips', async () => {
    withRuns(25)
    mount(<Runs />, '/decisions')
    await screen.findByTestId('runs-count')
    for (const name of ['all accounts', 'voltarget', 'trend', 'crypto voltarget']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
  })
})

// --------------------------------------------------------------------------- //
// ITEM 3 — the copy fix                                                       //
// --------------------------------------------------------------------------- //

describe('CTA copy is first person singular', () => {
  it('uses the ruled wording verbatim', () => {
    expect(STORY_CTA.body[0]).toBe(
      'Glass Box is a MonzonAutomation project. I build automation for businesses that ' +
        'need to trust what a system did while nobody was watching — and this is the ' +
        'standard I hold my own work to: every action logged, every claim traceable, every ' +
        'failure published.',
    )
  })

  it('contains no first-person-plural claim', () => {
    const text = STORY_CTA.body.join(' ')
    expect(text).toContain('I build automation')
    expect(text).toContain('standard I hold my own work to')
    expect(text).not.toMatch(/\bWe build\b/)
    expect(text).not.toMatch(/\bwe hold\b/)
  })

  it('leaves the second paragraph unchanged', () => {
    expect(STORY_CTA.body[1]).toContain('twelve reviewed batches')
    expect(STORY_CTA.body[1]).toContain('The record of both is in the ledger.')
  })
})

// --------------------------------------------------------------------------- //
// ITEM 5 — the path to the builder                                            //
// --------------------------------------------------------------------------- //

describe('How this was built', () => {
  it('renders on Story with all four facts', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    const panel = await screen.findByTestId('story-build-process')
    expect(panel).toHaveTextContent(BUILD_PROCESS.title)
    expect(BUILD_PROCESS.facts).toHaveLength(4)
    for (const fact of BUILD_PROCESS.facts) {
      expect(panel).toHaveTextContent(fact.label)
    }
  })

  it('names the process facts a recruiter would check', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    const panel = await screen.findByTestId('story-build-process')
    expect(panel).toHaveTextContent('Twelve reviewed batches')
    expect(panel).toHaveTextContent(/human gate/i)
    expect(panel).toHaveTextContent(/self-caught|Two self-caught/i)
  })

  it('links to GitHub and to the ledger', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    const panel = await screen.findByTestId('story-build-process')
    expect(within(panel).getByRole('link', { name: /GitHub/ })).toHaveAttribute(
      'href',
      'https://github.com/danielfmonzon',
    )
    expect(within(panel).getByRole('link', { name: /dated ledger/ })).toHaveAttribute(
      'href',
      '/ledger',
    )
  })

  it('uses a definition list so the facts are structured, not prose', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    const panel = await screen.findByTestId('story-build-process')
    expect(panel.querySelector('dl')).not.toBeNull()
    expect(panel.querySelectorAll('dt')).toHaveLength(4)
  })

  it('sits before the MonzonAutomation CTA, not after it', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    await screen.findByTestId('story-build-process')
    const all = [...document.querySelectorAll('[data-testid]')].map((n) =>
      n.getAttribute('data-testid'),
    )
    expect(all.indexOf('story-build-process')).toBeLessThan(all.indexOf('story-cta'))
  })
})

// --------------------------------------------------------------------------- //
// ITEM 2 — prerender (reads the real build artifact)                          //
// --------------------------------------------------------------------------- //

const DIST = path.resolve(__dirname, '..', 'dist')
const INDEX = path.join(DIST, 'index.html')
const built = fs.existsSync(INDEX)

describe.skipIf(!built)('prerendered index.html', () => {
  const html = () => fs.readFileSync(INDEX, 'utf8')

  it('contains the Story h1 as literal text', () => {
    expect(html()).toContain(STORY_HERO.headline)
  })

  it('contains the disclaimer as literal text', () => {
    expect(html()).toContain('quantlab trades simulated money')
    expect(html()).toContain(DISCLAIMER.slice(0, 60))
  })

  it('contains the hero paragraphs, with {N} substituted', () => {
    const text = html()
    expect(text).toContain('an autonomous trading-research system')
    expect(text).toMatch(/running unattended for \d+ days/)
    expect(text).not.toContain('{N}')
  })

  it('marks #root as prerendered for / and gives it real children', () => {
    const text = html()
    expect(text).toContain('data-prerendered="/"')
    const inner = /<div id="root"[^>]*>([\s\S]*?)<\/div>\s*<script type="application\/json"/.exec(
      text,
    )
    expect(inner?.[1]?.length ?? 0).toBeGreaterThan(2000)
  })

  it('ships the preload payload as a non-executable JSON block', () => {
    // `type="application/json"` is a data block, not a script, so the strict
    // `script-src 'self'` CSP does not block it. An inline assignment would have.
    expect(html()).toContain('<script type="application/json" id="glassbox-preload">')
  })

  it('carries a noscript block with the headline and disclaimer', () => {
    const noscript = /<noscript>([\s\S]*?)<\/noscript>/.exec(html())?.[1] ?? ''
    expect(noscript).toContain(STORY_HERO.headline)
    expect(noscript).toContain('quantlab trades simulated money')
    expect(noscript).toMatch(/running unattended for \d+ days/)
  })

  it('gives every route its own html file with the right title', () => {
    const routes = ['live', 'decisions', 'tracking', 'limits', 'equity', 'ledger', 'ignores']
    for (const route of routes) {
      // FLAT files: Netlify serves /live from live.html with a 200, whereas a directory
      // index makes it 301 to /live/ first.
      const file = path.join(DIST, `${route}.html`)
      expect(fs.existsSync(file), `${route}.html`).toBe(true)
      const text = fs.readFileSync(file, 'utf8')
      expect(text).toContain('<noscript>')
      // Non-Story routes are shells: lazy screens cannot be server-rendered usefully.
      expect(text).toContain('<div id="root"></div>')
      expect(text).not.toContain('data-prerendered')
    }
    expect(fs.readFileSync(path.join(DIST, 'decisions.html'), 'utf8')).toContain(
      '<title>Decisions — Glass Box</title>',
    )
  })

  it('has a body a non-JS client can actually read', () => {
    const visible = html()
      .replace(/<script[\s\S]*?<\/script>/g, '')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    // Before prerendering this was under 100 characters of head-only content.
    expect(visible.length).toBeGreaterThan(3000)
  })
})
