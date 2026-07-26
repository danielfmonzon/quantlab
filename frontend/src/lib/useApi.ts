/**
 * Minimal async-resource hook. No data-fetching library: nine GET endpoints on
 * localhost do not justify one, and a hand-rolled hook keeps the failure states
 * explicit — which is the whole point of this app.
 */

import { useCallback, useEffect, useState } from 'react'

export interface Resource<T> {
  data: T | null
  error: string | null
  loading: boolean
  reload: () => void
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  /**
   * Synchronous starting value, used for prerendering.
   *
   * `renderToString` never runs effects, so a server render sees only the initial state —
   * which for a data-driven page is the loading state. Seeding lets the prerendered HTML
   * carry real figures, and lets the client's first render match that HTML so hydration
   * does not discard it.
   */
  seed: T | null = null,
): Resource<T> {
  const [data, setData] = useState<T | null>(seed)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(seed === null)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    // The seed is a starting value, not a cache: the effect still refetches so a
    // long-open tab is not stuck on prerendered numbers.
    fetcher()
      .then((result) => {
        if (!cancelled) {
          setData(result)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, error, loading, reload }
}
