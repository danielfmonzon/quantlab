/**
 * App shell: skip link, snapshot banner, navigation, routed screen, footer.
 *
 * ROUTE-LEVEL CODE SPLITTING. The charting library is ~549 kB — larger than everything
 * else combined — and only three routes draw a chart. Every screen is therefore lazy, so
 * the Story landing page (the one a first-time reader actually hits) never downloads
 * Recharts. Story itself is eagerly imported: it is the default route, and making the
 * landing page wait on a second round trip to render its own headline would trade a real
 * first-paint win for a theoretical one.
 */

import { Suspense, lazy, useEffect, useState } from 'react'
import { api } from './lib/api'
import type { OverviewResponse } from './lib/api'
import { useApi } from './lib/useApi'
import { DATA_MODE, loadManifest } from './lib/transport'
import type { SnapshotManifest } from './lib/transport'
import { resolveRoute, useRouter } from './lib/router'
import { Footer, SnapshotBanner, useDocumentHead } from './components/chrome'
import { DesktopNav, MobileBar } from './components/Nav'
import { Story } from './screens/Story'

// Chart-bearing routes are split out; Recharts lands in a chunk only they pull.
const Overview = lazy(() =>
  import('./screens/Overview').then((m) => ({ default: m.Overview })),
)
const Runs = lazy(() => import('./screens/Runs').then((m) => ({ default: m.Runs })))
const Divergence = lazy(() =>
  import('./screens/Divergence').then((m) => ({ default: m.Divergence })),
)
const Risk = lazy(() => import('./screens/Risk').then((m) => ({ default: m.Risk })))
const Equity = lazy(() => import('./screens/Equity').then((m) => ({ default: m.Equity })))
const Ledger = lazy(() => import('./screens/Ledger').then((m) => ({ default: m.Ledger })))
const Glass = lazy(() => import('./screens/Glass').then((m) => ({ default: m.Glass })))

const SCREENS = {
  '/': Story,
  '/live': Overview,
  '/decisions': Runs,
  '/tracking': Divergence,
  '/limits': Risk,
  '/equity': Equity,
  '/ledger': Ledger,
  '/ignores': Glass,
} as const

function ScreenFallback() {
  return (
    <p className="text-xs text-muted" role="status" aria-live="polite">
      loading…
    </p>
  )
}

export function App() {
  const { path } = useRouter()
  const route = resolveRoute(path)
  const Screen = SCREENS[route]
  useDocumentHead(route)

  const [navOpen, setNavOpen] = useState(false)
  // A route change closes the slide-over; leaving it open over new content is disorienting.
  useEffect(() => {
    setNavOpen(false)
  }, [route])

  // Version/commit for the footer. In snapshot mode they come from the manifest (the
  // build's own provenance); in live mode the API does not publish them, so the footer
  // omits them rather than inventing a value.
  const manifest = useApi<SnapshotManifest | null>(
    () => (DATA_MODE === 'snapshot' ? loadManifest() : Promise.resolve(null)),
    [],
  )
  // Warm the overview cache once; harmless in live mode, and Story needs it for {N}.
  useApi<OverviewResponse>(() => api.overview())

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>

      <SnapshotBanner />
      <MobileBar
        route={route}
        open={navOpen}
        onOpen={() => setNavOpen(true)}
        onClose={() => setNavOpen(false)}
      />

      {/*
        Both the content column AND the footer are hidden from assistive tech while the
        drawer is open. Marking only the content div left the footer — a sibling — still
        reachable, so a screen-reader user could tab out of a modal into the disclaimer.
      */}
      <div
        className="mx-auto flex w-full max-w-shell flex-1 flex-col md:flex-row"
        aria-hidden={navOpen || undefined}
      >
        <DesktopNav route={route} />

        {/*
          `min-h-[70vh]` sits on <main>, not on the Suspense fallback. A fixed-height
          fallback reserves a box the real screen never matches, which relocates the
          layout shift instead of removing it — measured CLS went from 0.17 to 0.96 when
          the reservation was on the fallback. A floor on main keeps the footer below a
          stable line from first paint.
        */}
        <main
          id="main"
          className="min-h-[70vh] min-w-0 flex-1 px-5 py-8 lg:px-10 lg:py-12"
          tabIndex={-1}
        >
          <Suspense fallback={<ScreenFallback />}>
            <Screen />
          </Suspense>
        </main>
      </div>

      <div aria-hidden={navOpen || undefined}>
        <Footer
          version={manifest.data?.quantlab_version ?? null}
          commit={manifest.data?.git_commit ?? null}
        />
      </div>
    </div>
  )
}
