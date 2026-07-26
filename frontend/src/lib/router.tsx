/**
 * Hash-free client-side routing over the History API.
 *
 * No router dependency: eight static routes need path matching, a link component, and
 * a redirect table — nothing more. The server serves `index.html` for unknown paths
 * (see `_SpaStaticFiles` locally, `_redirects` on Netlify), so deep links survive a
 * reload.
 *
 * ROUTE RENAMES. The paths changed in G1: `/` is now the Story landing page and the
 * operational Overview moved to `/live`. Old paths are kept working through
 * `LEGACY_REDIRECTS` — a client-side equivalent of a 301, which replaces the history
 * entry rather than pushing one so Back does not bounce the reader through the dead
 * URL.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

export const ROUTES = [
  { path: '/' },
  { path: '/live' },
  { path: '/decisions' },
  { path: '/tracking' },
  { path: '/limits' },
  { path: '/equity' },
  { path: '/ledger' },
  { path: '/ignores' },
] as const

export type RoutePath = (typeof ROUTES)[number]['path']

/** Pre-G1 paths → their current home. Old links must not rot. */
export const LEGACY_REDIRECTS: Record<string, RoutePath> = {
  '/runs': '/decisions',
  '/divergence': '/tracking',
  '/risk': '/limits',
  '/glass': '/ignores',
  // `/overview` was never shipped as a path, but it is the obvious guess for the
  // screen that used to live at `/`, so it is honoured too.
  '/overview': '/live',
}

interface RouterValue {
  path: string
  navigate: (to: string, options?: { replace?: boolean }) => void
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

  const navigate = useCallback((to: string, options?: { replace?: boolean }) => {
    if (typeof window !== 'undefined') {
      if (options?.replace) window.history.replaceState({}, '', to)
      else window.history.pushState({}, '', to)
    }
    setPath(to)
  }, [])

  // A legacy path resolves to its new home and rewrites the URL in place, so the
  // address bar and the rendered screen never disagree.
  const legacy = LEGACY_REDIRECTS[normalise(path)]
  useEffect(() => {
    if (legacy) navigate(legacy, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [legacy])

  return (
    <RouterContext.Provider value={{ path, navigate }}>{children}</RouterContext.Provider>
  )
}

export const useRouter = (): RouterValue => useContext(RouterContext)

export function Link({
  to,
  children,
  className,
  onClick,
  ...rest
}: {
  to: string
  children: ReactNode
  className?: string
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href' | 'className'>) {
  const { navigate } = useRouter()
  return (
    <a
      href={to}
      className={className}
      // `rest` is spread BEFORE onClick, and the caller's handler is composed rather
      // than replaced. Spreading after would let a caller-supplied `onClick` — even an
      // `undefined` one, which is what a component passing an optional callback sends —
      // silently overwrite the navigation handler. That produced links that looked
      // correct, had the right href, and did nothing when clicked.
      {...rest}
      onClick={(event) => {
        onClick?.(event)
        if (event.defaultPrevented) return
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

/** Strip trailing slashes; `''` becomes `/`. */
export function normalise(path: string): string {
  return path.replace(/\/+$/, '') || '/'
}

/**
 * Resolve a path to a known route, following one legacy redirect, defaulting to Story.
 */
export function resolveRoute(path: string): RoutePath {
  const trimmed = normalise(path)
  const redirected = LEGACY_REDIRECTS[trimmed]
  if (redirected) return redirected
  const match = ROUTES.find((r) => r.path === trimmed)
  return match ? match.path : '/'
}
