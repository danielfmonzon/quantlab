/**
 * Prerender data handoff.
 *
 * The build prerenders `/` to static HTML so the landing page is readable without
 * JavaScript. That render needs the same overview data the client fetches, and the client
 * needs the identical value on its first render or hydration would throw the prerendered
 * markup away.
 *
 * The data travels in a `<script type="application/json">` data block. That type is NOT
 * executed, so the strict `script-src 'self'` CSP does not block it — an inline
 * `<script>` assigning to `window` would have needed a nonce or a CSP hole.
 */

export const PRELOAD_ELEMENT_ID = 'glassbox-preload'

export interface PreloadPayload {
  overview?: unknown
}

/** Set by the server renderer before `renderToString`; unused in the browser. */
let serverPreload: PreloadPayload | null = null

export function setServerPreload(payload: PreloadPayload | null): void {
  serverPreload = payload
}

/** Read the prerender payload, from the SSR global or the injected data block. */
export function readPreload(): PreloadPayload {
  if (serverPreload) return serverPreload
  if (typeof document === 'undefined') return {}
  const el = document.getElementById(PRELOAD_ELEMENT_ID)
  if (!el?.textContent) return {}
  try {
    return JSON.parse(el.textContent) as PreloadPayload
  } catch {
    // A malformed block is not worth a blank page: fall back to fetching.
    return {}
  }
}

export function preloaded<T>(key: keyof PreloadPayload): T | null {
  const value = readPreload()[key]
  return (value ?? null) as T | null
}
