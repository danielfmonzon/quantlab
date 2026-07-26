/**
 * Server entry for build-time prerendering.
 *
 * Only `/` (Story) is prerendered to markup. The other routes are lazy-loaded through
 * `React.lazy`, which does not resolve synchronously during `renderToString` — a server
 * render of `/decisions` would emit the Suspense fallback, and the client would then have
 * to discard it. Those routes get a shell with correct head tags instead; Story is the page
 * a first-time reader lands on and the one the requirement names.
 */

import { renderToString } from 'react-dom/server'
import { App } from './App'
import { RouterProvider } from './lib/router'
import { setServerPreload } from './lib/preload'
import type { PreloadPayload } from './lib/preload'

export interface RenderResult {
  html: string
}

/**
 * Render the Story route.
 *
 * This renders the SAME `<App />` the client hydrates, not a hand-composed subset.
 * An earlier version assembled nav + main + footer directly, reasoning that App's drawer
 * state, banner fetch and Suspense boundary had no meaningful server form. That was wrong:
 * hydration compares the WHOLE tree, so the missing skip link and mobile bar produced
 * React #418/#423 on every page load and the prerendered markup was thrown away — the
 * static HTML still served crawlers, but every real visitor paid for a full re-render and
 * saw six console errors.
 *
 * Every stateful piece of App happens to render identically on both sides: `navOpen` starts
 * false, the snapshot banner starts in its "reading manifest" state, and Story is eagerly
 * imported so its Suspense boundary resolves synchronously. Rendering App is therefore both
 * correct and simpler than composing a subset.
 */
export function render(preload: PreloadPayload): RenderResult {
  setServerPreload(preload)
  const html = renderToString(
    <RouterProvider initialPath="/">
      <App />
    </RouterProvider>,
  )
  setServerPreload(null)
  return { html }
}
