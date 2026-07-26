import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'

/** Production host. Override per-deploy with VITE_SITE_URL. */
const SITE_URL_DEFAULT = 'https://monzonautomation-glassbox.netlify.app'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Inject `<link rel="preload">` for the font files Vite actually emitted.
 *
 * The brand faces are self-hosted through Fontsource, so Vite content-hashes them out of
 * node_modules and their filenames are not knowable when writing index.html. Hand-written
 * preload paths were therefore links to files that never existed — a 404 and a console
 * warning, strictly worse than no preload. This reads the real bundle instead.
 *
 * Only the two upright latin faces the first paint uses are preloaded. Preloading the
 * italics and the extended ranges too would compete with the JS bundle for bandwidth to
 * fetch glyphs the landing page never renders.
 */
/**
 * Replace `%SITE_URL%` in index.html and in the emitted robots.txt / sitemap.xml.
 *
 * robots.txt `Sitemap:` and sitemap `<loc>` must be ABSOLUTE per spec — Lighthouse
 * reported "Invalid sitemap URL" and "canonical is not an absolute URL" for the relative
 * versions. The value comes from VITE_SITE_URL so a preview deploy can override it
 * instead of shipping a canonical pointing at production.
 */
function siteUrl(url: string, outDir: string): Plugin {
  const clean = url.replace(/\/$/, '')
  return {
    name: 'glassbox-site-url',
    transformIndexHtml(html) {
      return html.split('%SITE_URL%').join(clean)
    },
    // `public/` files are COPIED verbatim, never bundled, so generateBundle never sees
    // them — the substitution has to happen on disk after the write.
    closeBundle() {
      for (const name of ['robots.txt', 'sitemap.xml']) {
        const file = path.resolve(outDir, name)
        if (!fs.existsSync(file)) continue
        const text = fs.readFileSync(file, 'utf8')
        if (!text.includes('%SITE_URL%')) continue
        fs.writeFileSync(file, text.split('%SITE_URL%').join(clean))
      }
    },
  }
}

function fontPreload(): Plugin {
  const WANTED = [
    /fraunces-latin-standard-normal/,
    /hanken-grotesk-latin-wght-normal/,
  ]
  let emitted: string[] = []
  return {
    name: 'glassbox-font-preload',
    apply: 'build',
    generateBundle(_options, bundle) {
      emitted = Object.keys(bundle).filter(
        (name) => name.endsWith('.woff2') && WANTED.some((re) => re.test(name)),
      )
    },
    transformIndexHtml() {
      return emitted.map((href) => ({
        tag: 'link',
        attrs: {
          rel: 'preload',
          href: '/' + href,
          as: 'font',
          type: 'font/woff2',
          crossorigin: '',
        },
        injectTo: 'head' as const,
      }))
    },
  }
}

// Build output lands in `dist/`, which `quantlab glassbox serve` mounts at the
// server root. Asset URLs are therefore ABSOLUTE (`/assets/...`): a relative base
// would resolve against the current route's directory, so a deep link with a
// trailing slash (`/divergence/`) would look for `/divergence/assets/...`, miss, and
// get the SPA fallback HTML back in place of its JavaScript.
export default defineConfig(({ mode }) => ({
  plugins: [react(), fontPreload(), siteUrl(process.env.VITE_SITE_URL ?? SITE_URL_DEFAULT, 'dist')],
  // `public/` is copied verbatim into `dist/`, which meant the LIVE (localhost) build
  // also shipped ~800 kB of snapshot JSON it never reads. Only the public build needs
  // it, so the live build points `publicDir` at a directory without it.
  publicDir: mode === 'public' ? 'public' : 'public-live',
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    // Recharts + d3 are ~550 kB on their own and are one third-party dependency in
    // a long-lived, separately-cached chunk; app code is ~50 kB. Splitting the
    // vendor chunk further would not help a localhost-only tool, so the warning
    // threshold is raised deliberately rather than left firing on every build.
    // Recharts is ~550 kB and is reached only through the lazy chart routes. NO
    // manualChunks entry: naming it made it a static dependency of the entry graph,
    // which made Vite modulepreload the whole thing from index.html — the landing page
    // then downloaded a charting library it never renders. Rollup's own splitting from
    // the dynamic imports keeps it out of the initial load.
    chunkSizeWarningLimit: 600,
    // Never inline a font as a data: URI. Vite inlines assets under 4 kB by default,
    // and an inlined font forced the CSP to allow `font-src data:` — Chrome logged a
    // CSP violation for it. Emitting every font as a real file keeps the policy tight.
    assetsInlineLimit: (filePath) => (/\.(woff2?|ttf|otf|eot)$/i.test(filePath) ? false : undefined),
  },
  server: {
    // `npm run dev` proxies /api to a locally running `quantlab glassbox serve`.
    proxy: { '/api': 'http://127.0.0.1:8600' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.ts'],
    globals: true,
    include: ['test/**/*.test.tsx', 'test/**/*.test.ts'],
    css: false,
  },
}))
