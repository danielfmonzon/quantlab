/**
 * App shell: persistent nav rail plus the routed screen.
 *
 * Dark-first and dense, but calm: one accent (`signal-info`) marks the active
 * route, hierarchy comes from type weight rather than boxes, and the only
 * transitions are on state change (route switch, disclosure open).
 */

import { ROUTES, Link, resolveRoute, useRouter } from './lib/router'
import { Divergence } from './screens/Divergence'
import { Equity } from './screens/Equity'
import { Glass } from './screens/Glass'
import { Ledger } from './screens/Ledger'
import { Overview } from './screens/Overview'
import { Risk } from './screens/Risk'
import { Runs } from './screens/Runs'

const SCREENS = {
  '/': Overview,
  '/runs': Runs,
  '/divergence': Divergence,
  '/risk': Risk,
  '/equity': Equity,
  '/ledger': Ledger,
  '/glass': Glass,
} as const

export function App() {
  const { path } = useRouter()
  const route = resolveRoute(path)
  const Screen = SCREENS[route]

  return (
    <div className="min-h-screen bg-ink-900 text-slate-200 antialiased">
      <div className="mx-auto flex max-w-[1400px] flex-col lg:flex-row">
        <nav className="shrink-0 border-b border-ink-600 px-6 py-4 lg:sticky lg:top-0 lg:h-screen lg:w-56 lg:border-b-0 lg:border-r lg:py-8">
          <Link to="/" className="block">
            <p className="font-mono text-2xs uppercase tracking-[0.2em] text-signal-idle">
              quantlab
            </p>
            <p className="mt-0.5 text-sm font-semibold tracking-tight text-slate-100">
              Glass Box
            </p>
          </Link>

          <ul className="mt-6 flex flex-wrap gap-x-1 gap-y-1 lg:flex-col">
            {ROUTES.map((entry) => {
              const active = entry.path === route
              return (
                <li key={entry.path}>
                  <Link
                    to={entry.path}
                    className={`block rounded px-2.5 py-1.5 text-sm transition-colors ${
                      active
                        ? 'bg-signal-info/10 text-slate-100'
                        : 'text-signal-idle hover:bg-ink-800 hover:text-slate-200'
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`mr-2 inline-block h-1 w-1 rounded-full align-middle ${
                        active ? 'bg-signal-info' : 'bg-transparent'
                      }`}
                    />
                    {entry.label}
                  </Link>
                </li>
              )
            })}
          </ul>

          <p className="mt-8 hidden max-w-[12rem] text-2xs leading-relaxed text-signal-idle/60 lg:block">
            Paper trading only. Read-only view: this interface cannot place, cancel, or
            halt anything.
          </p>
        </nav>

        <main className="min-w-0 flex-1 px-6 py-8 lg:px-10">
          <Screen />
        </main>
      </div>
    </div>
  )
}
