/**
 * Hash-free client-side routing over the History API.
 *
 * No router dependency: seven static routes need path matching and a link
 * component, nothing more. The server serves `index.html` for unknown paths (see
 * `_SpaStaticFiles`), so deep links survive a reload.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export const ROUTES = [
  { path: '/', label: 'Overview' },
  { path: '/runs', label: 'Runs' },
  { path: '/divergence', label: 'Divergence' },
  { path: '/risk', label: 'Risk' },
  { path: '/equity', label: 'Equity' },
  { path: '/ledger', label: 'Ledger' },
  { path: '/glass', label: 'Glass' },
] as const

export type RoutePath = (typeof ROUTES)[number]['path']

interface RouterValue {
  path: string
  navigate: (to: string) => void
}

const RouterContext = createContext<RouterValue>({ path: '/', navigate: () => {} })

export function RouterProvider({
  children,
  initialPath,
}: {
  children: ReactNode
  /** Injected by tests so a screen can be mounted at its route without history. */
  initialPath?: string
}) {
  const [path, setPath] = useState(
    () => initialPath ?? (typeof window === 'undefined' ? '/' : window.location.pathname),
  )

  useEffect(() => {
    if (typeof window === 'undefined') return
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to: string) => {
    if (typeof window !== 'undefined') {
      window.history.pushState({}, '', to)
    }
    setPath(to)
  }, [])

  return (
    <RouterContext.Provider value={{ path, navigate }}>{children}</RouterContext.Provider>
  )
}

export const useRouter = (): RouterValue => useContext(RouterContext)

export function Link({
  to,
  children,
  className,
}: {
  to: string
  children: ReactNode
  className?: string
}) {
  const { navigate } = useRouter()
  return (
    <a
      href={to}
      className={className}
      onClick={(event) => {
        // Let modified clicks (new tab, download) behave natively.
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
        event.preventDefault()
        navigate(to)
      }}
    >
      {children}
    </a>
  )
}

/** Normalise a path to one of the known routes, defaulting to Overview. */
export function resolveRoute(path: string): RoutePath {
  const trimmed = path.replace(/\/+$/, '') || '/'
  const match = ROUTES.find((r) => r.path === trimmed)
  return match ? match.path : '/'
}
