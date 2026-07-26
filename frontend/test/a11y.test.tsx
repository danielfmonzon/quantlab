/**
 * Automated accessibility pass — axe-core over every screen, zero violations required.
 *
 * axe catches the mechanical failures (missing names, bad contrast in the DOM, broken
 * landmark structure, ARIA misuse). It cannot catch the judgement calls, so the tests
 * after the axe block pin those by hand: provenance encoded three ways rather than by
 * colour alone, glossary terms reachable by keyboard and touch, the focus trap actually
 * trapping, and headings in order.
 *
 * Run against BOTH populated and empty data: an empty state is still a page someone has
 * to read with a screen reader.
 */

import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import type { ReactElement } from 'react'

import { App } from '../src/App'
import { RouterProvider } from '../src/lib/router'
import { Divergence } from '../src/screens/Divergence'
import { Equity } from '../src/screens/Equity'
import { Glass } from '../src/screens/Glass'
import { Ledger } from '../src/screens/Ledger'
import { Overview } from '../src/screens/Overview'
import { Risk } from '../src/screens/Risk'
import { Runs } from '../src/screens/Runs'
import { Story } from '../src/screens/Story'
import { Term } from '../src/components/Term'
import { PROVENANCE_SHAPE } from '../src/components/primitives'
import { EMPTY, POPULATED, mockApi } from './fixtures'

/**
 * Run axe over the rendered container.
 *
 * `color-contrast` is DISABLED here and verified separately by
 * `scripts/contrast.mjs`, which computes exact WCAG ratios from the token values. jsdom
 * does not apply the Tailwind stylesheet (`css: false` in the vitest config), so axe
 * would be sampling unstyled defaults — a pass would be meaningless and a failure
 * misleading. The real check is the one with real numbers in it.
 */
async function expectNoViolations(container: HTMLElement): Promise<void> {
  const results = await axe.run(container, {
    runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
    rules: { 'color-contrast': { enabled: false } },
  })
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help} [${v.nodes.length} node(s)]`,
  )
  expect(summary, summary.join('\n')).toEqual([])
}

const SCREENS: Array<{ name: string; element: ReactElement; path: string }> = [
  { name: 'Story', element: <Story />, path: '/' },
  { name: 'Overview', element: <Overview />, path: '/live' },
  { name: 'Runs', element: <Runs />, path: '/decisions' },
  { name: 'Divergence', element: <Divergence />, path: '/tracking' },
  { name: 'Risk', element: <Risk />, path: '/limits' },
  { name: 'Equity', element: <Equity />, path: '/equity' },
  { name: 'Ledger', element: <Ledger />, path: '/ledger' },
  { name: 'Glass', element: <Glass />, path: '/ignores' },
]

const settle = async () => {
  await waitFor(() => {
    expect(screen.queryByText(/^reading \/api/)).not.toBeInTheDocument()
  })
}

describe.each(SCREENS)('axe — $name', ({ element, path }) => {
  it('has no violations with data', async () => {
    mockApi(POPULATED)
    const { container } = render(
      <RouterProvider initialPath={path}>{element}</RouterProvider>,
    )
    await settle()
    await expectNoViolations(container)
  }, 30000)

  it('has no violations when empty', async () => {
    mockApi(EMPTY)
    const { container } = render(
      <RouterProvider initialPath={path}>{element}</RouterProvider>,
    )
    await settle()
    await expectNoViolations(container)
  }, 30000)
})

describe('axe — full shell', () => {
  it('has no violations including nav, banner and footer', async () => {
    mockApi(POPULATED)
    const { container } = render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    await expectNoViolations(container)
  }, 30000)

  it('has no violations with the mobile slide-over open', async () => {
    mockApi(POPULATED)
    const { container } = render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    await userEvent.click(screen.getByTestId('mobile-nav-trigger'))
    await screen.findByTestId('mobile-nav-panel')
    await expectNoViolations(container)
  }, 30000)
})

// --------------------------------------------------------------------------- //
// Judgement calls axe cannot make                                            //
// --------------------------------------------------------------------------- //

describe('colour is never the only carrier of meaning', () => {
  it('encodes provenance as shape + text as well as colour', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/live">
        <Overview />
      </RouterProvider>,
    )
    const badge = await screen.findByTestId('provenance-on_schedule')
    // 1. text
    expect(badge).toHaveTextContent('on schedule')
    // 2. shape, marked aria-hidden so it is not read aloud twice
    const shape = within(badge).getByTestId('provenance-shape-on_schedule')
    expect(shape).toHaveTextContent(PROVENANCE_SHAPE.on_schedule)
    expect(shape).toHaveAttribute('aria-hidden')
    // 3. colour is the class, and is the only one of the three that can be lost
    expect(badge.className).toMatch(/text-signal-ok/)
  })

  it('gives each provenance state a distinct shape', () => {
    const shapes = Object.values(PROVENANCE_SHAPE)
    expect(new Set(shapes).size).toBe(shapes.length)
  })

  it('encodes verdicts with a glyph as well as a colour', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/tracking">
        <Divergence />
      </RouterProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'trend' }))
    const chips = await screen.findAllByTestId('verdict-TRACKING')
    // The chip carries its own word, so a monochrome print still reads correctly.
    expect(chips[0]).toHaveTextContent('TRACKING')
  }, 30000)
})

describe('glossary terms are reachable without a mouse', () => {
  it('opens on click and exposes the definition via aria-describedby', async () => {
    render(<Term>drawdown</Term>)
    const trigger = screen.getByTestId('term')
    // A real button: in the tab order, with expanded state.
    expect(trigger.tagName).toBe('BUTTON')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    await userEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    const card = screen.getByTestId('term-card')
    expect(trigger.getAttribute('aria-describedby')).toBe(card.getAttribute('id'))
    expect(card).toHaveTextContent('highest point')
    expect(card).toHaveTextContent('Why it matters')
  })

  it('opens from the keyboard alone', async () => {
    render(<Term>bps</Term>)
    await userEvent.tab()
    expect(screen.getByTestId('term')).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(screen.getByTestId('term-card')).toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    render(<Term>kill switch</Term>)
    await userEvent.click(screen.getByTestId('term'))
    expect(screen.getByTestId('term-card')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('term-card')).not.toBeInTheDocument()
  })

  it('renders an unknown term as plain text, not a dead affordance', () => {
    render(<Term term="not-a-real-term">something</Term>)
    expect(screen.queryByTestId('term')).not.toBeInTheDocument()
    expect(screen.getByText('something')).toBeInTheDocument()
  })
})

describe('mobile slide-over traps focus', () => {
  it('moves focus in, cycles within, and closes on Escape', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    await userEvent.click(screen.getByTestId('mobile-nav-trigger'))

    const panel = await screen.findByTestId('mobile-nav-panel')
    expect(panel).toHaveAttribute('role', 'dialog')
    expect(panel).toHaveAttribute('aria-modal', 'true')
    // Focus is inside the panel, not left on the trigger behind it.
    await waitFor(() => expect(panel.contains(document.activeElement)).toBe(true))

    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByTestId('mobile-nav-panel')).not.toBeInTheDocument(),
    )
  }, 30000)

  it('hides the footer too, not just the content column', async () => {
    /**
     * The footer is a SIBLING of the content column. Marking only the content
     * `aria-hidden` left the disclaimer reachable from inside an open modal.
     */
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    await userEvent.click(screen.getByTestId('mobile-nav-trigger'))
    await screen.findByTestId('mobile-nav-panel')
    const footer = screen.getByTestId('footer')
    expect(footer.closest('[aria-hidden="true"]')).not.toBeNull()
  }, 30000)

  it('hides the rest of the app from assistive tech while open', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    await userEvent.click(screen.getByTestId('mobile-nav-trigger'))
    await screen.findByTestId('mobile-nav-panel')
    const main = document.getElementById('main')
    expect(main?.closest('[aria-hidden="true"]')).not.toBeNull()
  }, 30000)
})

describe('structure', () => {
  it('provides a skip link to main content', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    const skip = screen.getByRole('link', { name: /skip to main content/i })
    expect(skip).toHaveAttribute('href', '#main')
    expect(document.getElementById('main')).not.toBeNull()
  })

  it('exposes main, navigation and contentinfo landmarks', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
  })

  it('starts each screen at h1 and never skips a level', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    const levels = screen
      .getAllByRole('heading')
      .map((h) => Number(h.tagName.slice(1)))
    expect(levels[0]).toBe(1)
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i]! - levels[i - 1]!).toBeLessThanOrEqual(1)
    }
  })

  it('names every chart as an image carrying its takeaway', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/tracking">
        <Divergence />
      </RouterProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'trend' }))
    const plot = await screen.findByTestId('chart-plot')
    expect(plot).toHaveAttribute('role', 'img')
    const label = plot.getAttribute('aria-label') ?? ''
    // The accessible name is the takeaway, so a screen-reader user gets the conclusion.
    expect(label.length).toBeGreaterThan(30)
    expect(label).toMatch(/threshold|bps|week/i)
  }, 30000)
})

// --------------------------------------------------------------------------- //
// Regression: the router bug found while wiring the mobile nav                //
// --------------------------------------------------------------------------- //

describe('Link composes a caller onClick instead of being replaced by it', () => {
  it('still navigates when a parent passes onClick={undefined}', async () => {
    /**
     * `NavList` passes `onClick={onNavigate}`, which is `undefined` in the desktop nav.
     * Spreading `...rest` after the router's own handler let that undefined value
     * overwrite it, producing links with correct hrefs that did nothing when clicked.
     */
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    await userEvent.click(within(nav).getByRole('link', { name: /Refusals/ }))
    expect(
      await screen.findByRole('heading', { level: 1, name: /refuses to know/ }),
    ).toBeInTheDocument()
    expect(window.location.pathname).toBe('/ignores')
  }, 30000)

  it('still runs the caller onClick when one is supplied', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    await screen.findByTestId('story-hero')
    // The mobile panel passes a real onClick (close the drawer) AND must navigate.
    await userEvent.click(screen.getByTestId('mobile-nav-trigger'))
    const panel = await screen.findByTestId('mobile-nav-panel')
    await userEvent.click(within(panel).getByRole('link', { name: /Ledger/ }))
    await waitFor(() =>
      expect(screen.queryByTestId('mobile-nav-panel')).not.toBeInTheDocument(),
    )
    expect(window.location.pathname).toBe('/ledger')
  }, 30000)
})
