/**
 * G1: data modes, the Story landing page, route renames, and footer chrome.
 *
 * The mode tests matter most. A static build that silently fell back to live mode
 * would fetch `/api/*` against a host that has no API and render every screen as an
 * error, so both transports are exercised against the SAME fixture payloads: the
 * screens must be indistinguishable, and only the banner may differ.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from '../src/App'
import { RouterProvider, LEGACY_REDIRECTS, resolveRoute } from '../src/lib/router'
import { Story, equityClockDays } from '../src/screens/Story'
import { canonicalKey, getJson, resetManifestCache } from '../src/lib/transport'
import { DISCLAIMER, NAV_COPY, STORY_SECTIONS, withDayCount } from '../src/content/copy'
import { EMPTY, POPULATED, mockApi } from './fixtures'

const mount = (element: React.ReactElement, path = '/') =>
  render(<RouterProvider initialPath={path}>{element}</RouterProvider>)

/**
 * Re-import the module graph under a given data mode.
 *
 * `vi.resetModules()` means the freshly imported `App` gets its OWN copy of
 * `lib/router`, and therefore its own RouterContext. Pairing it with the statically
 * imported `RouterProvider` would supply a different context, so `useRouter` would
 * fall back to its default and every click would silently do nothing — a test that
 * looks like it navigates and does not. Both must come from the same fresh graph.
 */
async function freshApp(mode: 'live' | 'snapshot') {
  vi.stubEnv('VITE_DATA_MODE', mode)
  vi.resetModules()
  const [{ App: FreshApp }, { RouterProvider: FreshProvider }] = await Promise.all([
    import('../src/App'),
    import('../src/lib/router'),
  ])
  return { FreshApp, FreshProvider }
}

beforeEach(() => {
  resetManifestCache()
})
afterEach(() => {
  resetManifestCache()
  vi.unstubAllEnvs()
})

// --------------------------------------------------------------------------- //
// canonicalKey — must mirror glassbox/snapshot.py exactly                     //
// --------------------------------------------------------------------------- //

describe('canonicalKey', () => {
  it('matches the Python contract', () => {
    // These cases are duplicated verbatim in
    // tests/test_glassbox_snapshot.py::test_canonical_key_sorts_params_and_drops_limit.
    expect(canonicalKey('/api/overview')).toBe('/api/overview')
    expect(canonicalKey('/api/runs?limit=5000')).toBe('/api/runs')
    expect(canonicalKey('/api/runs?label=trend&limit=50')).toBe('/api/runs?label=trend')
    expect(canonicalKey('/api/x?b=2&a=1')).toBe('/api/x?a=1&b=2')
    expect(canonicalKey('/api/x?a=1&b=2')).toBe('/api/x?a=1&b=2')
    expect(canonicalKey('/api/x?label=')).toBe('/api/x')
  })
})

// --------------------------------------------------------------------------- //
// Transport: snapshot mode                                                    //
// --------------------------------------------------------------------------- //

const MANIFEST = {
  generated_at: '2026-07-26T14:38:14.155365Z',
  git_commit: '29f888e',
  quantlab_version: '1.0.0',
  endpoint_count: 2,
  note: 'Static capture.',
  endpoints: [
    {
      key: '/api/overview',
      file: 'api-overview.json',
      path: '/api/overview',
      params: {},
      status: 200,
      bytes: 100,
    },
    {
      key: '/api/timeline',
      file: 'api-timeline.json',
      path: '/api/timeline',
      params: {},
      status: 200,
      bytes: 50,
    },
  ],
}

/** Serve a manifest plus snapshot files, exactly as a static host would. */
function mockSnapshotHost(overrides: Record<string, unknown> = {}): void {
  const files: Record<string, unknown> = {
    '/snapshot/manifest.json': MANIFEST,
    '/snapshot/api-overview.json': POPULATED.overview,
    '/snapshot/api-timeline.json': POPULATED.timeline,
    ...overrides,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url in files) {
        return new Response(JSON.stringify(files[url]), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
    }),
  )
}

describe('transport — snapshot mode', () => {
  it('resolves an API url to its captured file through the manifest', async () => {
    mockSnapshotHost()
    const data = await getJson<typeof POPULATED.overview>('/api/overview', 'snapshot')
    expect(data.accounts[0]?.label).toBe('voltarget')
  })

  it('ignores limit when addressing a capture', async () => {
    mockSnapshotHost()
    // The manifest has no `?limit=` entry; the request must still resolve.
    const data = await getJson<typeof POPULATED.timeline>('/api/timeline?limit=500', 'snapshot')
    expect(data.events.length).toBeGreaterThan(0)
  })

  it('explains an uncaptured endpoint rather than failing opaquely', async () => {
    mockSnapshotHost()
    await expect(getJson('/api/risk', 'snapshot')).rejects.toThrow(
      /no snapshot capture for \/api\/risk/,
    )
  })

  it('surfaces a missing manifest as a readable error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 404 })))
    await expect(getJson('/api/overview', 'snapshot')).rejects.toThrow(
      /manifest unavailable \(404\)/,
    )
  })

  it('never calls /api/* in snapshot mode', async () => {
    mockSnapshotHost()
    await getJson('/api/overview', 'snapshot')
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    const urls = calls.map((c) => String(c[0]))
    expect(urls.every((u) => u.startsWith('/snapshot/'))).toBe(true)
  })
})

describe('transport — live mode', () => {
  it('fetches the API url directly', async () => {
    mockApi(POPULATED)
    const data = await getJson<typeof POPULATED.overview>('/api/overview', 'live')
    expect(data.accounts[0]?.label).toBe('voltarget')
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    expect(String(calls[0]?.[0])).toBe('/api/overview')
  })

  it('reports a non-200 with its status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('err', { status: 503 })))
    await expect(getJson('/api/overview', 'live')).rejects.toThrow(/returned 503/)
  })
})

// --------------------------------------------------------------------------- //
// Both modes render the same screen from the same data                        //
// --------------------------------------------------------------------------- //

describe('data modes render identically', () => {
  it('renders OVERVIEW from live data with NO snapshot banner', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'live')
    vi.resetModules()
    const { Overview } = await import('../src/screens/Overview')
    mockApi(POPULATED)
    mount(<Overview />, '/live')

    const card = await screen.findByTestId('account-card-voltarget')
    expect(card).toHaveTextContent('$98,821.82')
    expect(screen.queryByTestId('snapshot-banner')).not.toBeInTheDocument()
  })

  it('renders OVERVIEW from snapshot data WITH the banner', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'snapshot')
    vi.resetModules()
    const { Overview } = await import('../src/screens/Overview')
    const { SnapshotBanner } = await import('../src/components/chrome')
    mockSnapshotHost()
    mount(
      <>
        <SnapshotBanner />
        <Overview />
      </>,
      '/live',
    )

    // Same figure, same fixture, different transport.
    const card = await screen.findByTestId('account-card-voltarget')
    expect(card).toHaveTextContent('$98,821.82')

    const banner = await screen.findByTestId('snapshot-banner')
    expect(banner).toHaveTextContent('Snapshot of 2026-07-26 14:38 UTC')
    expect(banner).toHaveTextContent('quantlab 1.0.0 @ 29f888e')
    expect(banner).toHaveTextContent('refreshed manually')
    expect(within(banner).getByTestId('snapshot-manifest-link')).toHaveAttribute(
      'href',
      '/snapshot/manifest.json',
    )
  })

  it('banner renders on every screen in snapshot mode', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'snapshot')
    vi.resetModules()
    const { SnapshotBanner } = await import('../src/components/chrome')
    mockSnapshotHost()
    // The banner is shell-level, so one mount proves it is not screen-specific; the
    // App-shell test below proves it is actually in the shell.
    mount(<SnapshotBanner />)
    expect(await screen.findByTestId('snapshot-banner')).toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------- //
// Story                                                                       //
// --------------------------------------------------------------------------- //

describe('Story', () => {
  it('renders the hero and exactly three sections', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    expect(await screen.findByTestId('story-hero')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(STORY_SECTIONS).toHaveLength(3)
    for (const section of STORY_SECTIONS) {
      expect(screen.getByTestId(`story-section-${section.id}`)).toBeInTheDocument()
    }
  })

  it('substitutes {N} from the us_equity readiness clock', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    const subhead = await screen.findByTestId('story-subhead')
    // The fixture's equity clock reads 15 elapsed days.
    expect(subhead).toHaveTextContent('15 days')
    expect(subhead.textContent).not.toContain('{N}')
  })

  it('leaves no {N} token unsubstituted anywhere on the page', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    await screen.findByTestId('story-hero')
    expect(document.body.textContent).not.toContain('{N}')
  })

  it('renders from empty data with an em dash rather than a fabricated zero', async () => {
    mockApi(EMPTY)
    mount(<Story />)
    const subhead = await screen.findByTestId('story-subhead')
    expect(subhead).toHaveTextContent('— days')
    expect(subhead.textContent).not.toContain('0 days')
    expect(screen.getByText(/Day count unavailable/)).toBeInTheDocument()
  })

  it('renders from snapshot data', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'snapshot')
    vi.resetModules()
    const { Story: SnapStory } = await import('../src/screens/Story')
    mockSnapshotHost()
    mount(<SnapStory />)
    expect(await screen.findByTestId('story-hero')).toBeInTheDocument()
    expect(screen.getByTestId('story-subhead')).toHaveTextContent('15 days')
  })

  it('states where the day count came from', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    expect(
      await screen.findByText(/us_equity readiness clock's elapsed days/),
    ).toBeInTheDocument()
  })

  it('flags that the copy is a placeholder, not canonical F4 text', async () => {
    mockApi(POPULATED)
    mount(<Story />)
    expect(await screen.findByTestId('placeholder-copy-warning')).toHaveTextContent(
      /not the canonical F4 audit text/,
    )
  })

  it('equityClockDays reads only the us_equity clock', () => {
    expect(equityClockDays(null)).toBeNull()
    expect(equityClockDays(POPULATED.overview)).toBe(15)
    expect(equityClockDays(EMPTY.overview)).toBeNull()
    // A crypto-only roster has no equity clock to read.
    expect(
      equityClockDays({
        ...POPULATED.overview,
        accounts: POPULATED.overview.accounts.filter((a) => a.asset_class === 'crypto'),
      }),
    ).toBeNull()
  })

  it('withDayCount is total: no token survives', () => {
    expect(withDayCount('a {N} b {N}', 7)).toBe('a 7 b 7')
    expect(withDayCount('a {N}', null)).toBe('a —')
    expect(withDayCount('no token', 7)).toBe('no token')
  })
})

// --------------------------------------------------------------------------- //
// Routes and legacy redirects                                                 //
// --------------------------------------------------------------------------- //

describe('routing', () => {
  it('lands on Story at /', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    expect(await screen.findByTestId('story-hero')).toBeInTheDocument()
  })

  it('serves the operational Overview at /live', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/live">
        <App />
      </RouterProvider>,
    )
    expect(await screen.findByTestId('hero')).toBeInTheDocument()
    expect(await screen.findByTestId('account-card-voltarget')).toBeInTheDocument()
  })

  it.each(Object.entries(LEGACY_REDIRECTS))(
    'redirects the old path %s to %s',
    (from, to) => {
      expect(resolveRoute(from)).toBe(to)
    },
  )

  it('renders the new screen when mounted at a legacy path', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/glass">
        <App />
      </RouterProvider>,
    )
    // /glass -> /ignores, which is the Glass screen.
    expect(
      await screen.findByRole('heading', { level: 1, name: /refuses to know/ }),
    ).toBeInTheDocument()
  })

  it('rewrites the address bar for a legacy path instead of leaving it stale', async () => {
    mockApi(POPULATED)
    window.history.replaceState({}, '', '/runs')
    render(
      <RouterProvider initialPath="/runs">
        <App />
      </RouterProvider>,
    )
    await waitFor(() => expect(window.location.pathname).toBe('/decisions'))
  })

  it('every route has nav copy with a label, subtitle, title and description', () => {
    for (const [path, copy] of Object.entries(NAV_COPY)) {
      expect(copy.label, path).toBeTruthy()
      expect(copy.subtitle, path).toBeTruthy()
      expect(copy.title, path).toBeTruthy()
      expect(copy.description.length, path).toBeGreaterThan(40)
    }
  })

  it('renders teaching subtitles in the nav', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    const nav = screen.getByRole('navigation')
    expect(nav).toHaveTextContent('What each account holds right now')
    expect(nav).toHaveTextContent('Each rebalance, and the rule behind it')
    expect(nav).toHaveTextContent('The inputs it deliberately refuses')
  })

  it('sets a per-route document title', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/limits">
        <App />
      </RouterProvider>,
    )
    await waitFor(() => expect(document.title).toBe(NAV_COPY['/limits']!.title))
    expect(
      document.head.querySelector('meta[name="description"]')?.getAttribute('content'),
    ).toBe(NAV_COPY['/limits']!.description)
  })
})

// --------------------------------------------------------------------------- //
// Footer                                                                      //
// --------------------------------------------------------------------------- //

describe('footer', () => {
  it('carries the disclaimer, the byline links and the build stamp', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    const footer = await screen.findByTestId('footer')
    expect(within(footer).getByTestId('disclaimer')).toHaveTextContent(DISCLAIMER)
    expect(footer).toHaveTextContent('Built by Daniel Monzon')
    expect(within(footer).getByTestId('built-by-github')).toBeInTheDocument()
    expect(within(footer).getByTestId('built-by-linkedin')).toBeInTheDocument()
    expect(within(footer).getByTestId('built-by-contact')).toBeInTheDocument()
    expect(within(footer).getByTestId('footer-version')).toHaveTextContent('live mode')
  })

  it('flags that the disclaimer is a placeholder, not canonical F15 text', async () => {
    mockApi(POPULATED)
    render(
      <RouterProvider initialPath="/">
        <App />
      </RouterProvider>,
    )
    expect(
      await screen.findByTestId('placeholder-disclaimer-warning'),
    ).toHaveTextContent(/not the canonical F15 text/)
  })

  it('the disclaimer covers the substance a paper-trading site must state', () => {
    // Substance, not phrasing: canonical F15 text will word these differently, and
    // this test must survive that swap.
    const text = DISCLAIMER.toLowerCase()
    expect(text).toContain('paper')
    expect(text).toContain('investment advice')
    expect(text).toContain('no real capital')
    expect(text).toContain('simulated')
    expect(text).toMatch(/does not indicate future|past performance/)
  })

  it('appears on every route', async () => {
    mockApi(POPULATED)
    for (const path of ['/', '/live', '/decisions', '/tracking', '/limits', '/ignores']) {
      const view = render(
        <RouterProvider initialPath={path}>
          <App />
        </RouterProvider>,
      )
      expect(await screen.findByTestId('footer')).toBeInTheDocument()
      view.unmount()
    }
  })
})

// --------------------------------------------------------------------------- //
// Shell in snapshot mode                                                      //
// --------------------------------------------------------------------------- //

describe('App shell in snapshot mode', () => {
  it('shows the banner in the shell and the build stamp in the footer', async () => {
    const { FreshApp, FreshProvider } = await freshApp('snapshot')
    mockSnapshotHost()
    render(
      <FreshProvider initialPath="/">
        <FreshApp />
      </FreshProvider>,
    )
    expect(await screen.findByTestId('snapshot-banner')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByTestId('footer-version')).toHaveTextContent('snapshot mode'),
    )
    expect(screen.getByTestId('footer-version')).toHaveTextContent('1.0.0 @ 29f888e')
  })

  it('navigates in snapshot mode without reaching for /api', async () => {
    const { FreshApp, FreshProvider } = await freshApp('snapshot')
    mockSnapshotHost()
    render(
      <FreshProvider initialPath="/">
        <FreshApp />
      </FreshProvider>,
    )
    await screen.findByTestId('story-hero')
    await userEvent.click(screen.getByRole('link', { name: /Live State/ }))
    await screen.findByTestId('hero')

    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    expect(calls.map((c) => String(c[0])).some((u) => u.startsWith('/api/'))).toBe(false)
  })
})
