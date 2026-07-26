/**
 * App shell: snapshot banner, nav rail with teaching subtitles, routed screen, footer.
 *
 * Dark-first and dense, but calm: one accent (`signal-info`) marks the active route,
 * hierarchy comes from type weight rather than boxes, and the only transitions are on
 * state change (route switch, disclosure open).
 */

import { api } from './lib/api'
import type { OverviewResponse } from './lib/api'
import { useApi } from './lib/useApi'
import { DATA_MODE, loadManifest } from './lib/transport'
import type { SnapshotManifest } from './lib/transport'
import { ROUTES, Link, resolveRoute, useRouter } from './lib/router'
import { NAV_COPY, PLACEHOLDER_NAV_COPY } from './content/copy'
import { Footer, SnapshotBanner, useDocumentHead } from './components/chrome'
import { Divergence } from './screens/Divergence'
import { Equity } from './screens/Equity'
import { Glass } from './screens/Glass'
import { Ledger } from './screens/Ledger'
import { Overview } from './screens/Overview'
import { Risk } from './screens/Risk'
import { Runs } from './screens/Runs'
import { Story } from './screens/Story'

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

export function App() {
  const { path } = useRouter()
  const route = resolveRoute(path)
  const Screen = SCREENS[route]
  useDocumentHead(route)

  // Version/commit for the footer. In snapshot mode they come from the manifest (the
  // build's own provenance); in live mode the API does not publish them, so the footer
  // simply omits them rather than inventing a value.
  const manifest = useApi<SnapshotManifest | null>(
    () => (DATA_MODE === 'snapshot' ? loadManifest() : Promise.resolve(null)),
    [],
  )
  // Touch the overview once so a cold snapshot build warms the same cache the screens
  // use; harmless in live mode.
  useApi<OverviewResponse>(() => api.overview())

  return (
    <div className="flex min-h-screen flex-col bg-ink-900 text-slate-200 antialiased">
      <SnapshotBanner />

      <div className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col lg:flex-row">
        <nav className="shrink-0 border-b border-ink-600 px-6 py-4 lg:sticky lg:top-0 lg:h-screen lg:w-64 lg:overflow-y-auto lg:border-b-0 lg:border-r lg:py-8">
          <Link to="/" className="block">
            <p className="font-mono text-2xs uppercase tracking-[0.2em] text-signal-idle">
              quantlab
            </p>
            <p className="mt-0.5 text-sm font-semibold tracking-tight text-slate-100">
              Glass Box
            </p>
          </Link>

          <ul className="mt-6 flex flex-wrap gap-x-1 gap-y-1 lg:flex-col lg:gap-y-0.5">
            {ROUTES.map((entry) => {
              const copy = NAV_COPY[entry.path]
              const active = entry.path === route
              return (
                <li key={entry.path}>
                  <Link
                    to={entry.path}
                    aria-current={active ? 'page' : undefined}
                    className={`block rounded px-2.5 py-1.5 transition-colors ${
                      active
                        ? 'bg-signal-info/10 text-slate-100'
                        : 'text-signal-idle hover:bg-ink-800 hover:text-slate-200'
                    }`}
                  >
                    <span className="flex items-baseline text-sm">
                      <span
                        aria-hidden
                        className={`mr-2 inline-block h-1 w-1 shrink-0 rounded-full ${
                          active ? 'bg-signal-info' : 'bg-transparent'
                        }`}
                      />
                      {copy?.label ?? entry.path}
                    </span>
                    {/* Teaching subtitle: the nav explains itself rather than
                        assuming the reader knows the vocabulary. */}
                    {copy?.subtitle ? (
                      <span className="ml-3 hidden text-2xs leading-snug text-signal-idle/60 lg:block">
                        {copy.subtitle}
                      </span>
                    ) : null}
                  </Link>
                </li>
              )
            })}
          </ul>

          {PLACEHOLDER_NAV_COPY ? (
            <p
              className="mt-6 hidden max-w-[13rem] text-2xs leading-relaxed text-signal-warn/70 lg:block"
              data-testid="placeholder-nav-warning"
            >
              ⚠ nav labels and subtitles are placeholders, not the canonical F2 names.
            </p>
          ) : null}

          <p className="mt-6 hidden max-w-[13rem] text-2xs leading-relaxed text-signal-idle/60 lg:block">
            Paper trading only. Read-only view: this interface cannot place, cancel, or
            halt anything.
          </p>
        </nav>

        <main className="min-w-0 flex-1 px-6 py-8 lg:px-10">
          <Screen />
        </main>
      </div>

      <Footer
        version={manifest.data?.quantlab_version ?? null}
        commit={manifest.data?.git_commit ?? null}
      />
    </div>
  )
}
