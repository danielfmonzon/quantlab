import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import { App } from './App'
import { RouterProvider } from './lib/router'
import './index.css'

const root = document.getElementById('root')
if (!root) throw new Error('#root missing from index.html')

const tree = (
  <StrictMode>
    <RouterProvider>
      <App />
    </RouterProvider>
  </StrictMode>
)

/**
 * Hydrate only when this exact route was prerendered.
 *
 * `data-prerendered` carries the path the static markup was rendered for. Hydrating
 * markup rendered for a different route would be a guaranteed mismatch — every non-Story
 * page is served the same shell by the SPA fallback — so those mount fresh instead.
 */
const prerenderedFor = root.dataset.prerendered
const matchesRoute =
  prerenderedFor !== undefined &&
  prerenderedFor === (window.location.pathname.replace(/\/+$/, '') || '/')

if (matchesRoute && root.hasChildNodes()) {
  hydrateRoot(root, tree)
} else {
  // Clear any prerendered markup for a different route before mounting.
  root.innerHTML = ''
  createRoot(root).render(tree)
}
