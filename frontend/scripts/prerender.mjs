/**
 * Post-build prerender.
 *
 * WHY. Before this ran, anything that did not execute JavaScript received an empty shell:
 * head tags and `<div id="root"></div>`. For a page whose entire argument is "you can
 * check this", being unreadable without JS was the wrong first impression — and it left
 * the landing copy invisible to any client that does not run scripts.
 *
 * WHAT. Builds an SSR bundle of `src/entry-server.tsx`, renders the Story route against
 * the snapshot JSON already sitting in `dist/`, and injects the markup into
 * `dist/index.html` along with:
 *
 *   · a `<script type="application/json">` data block carrying the same overview payload,
 *     so the client's first render matches the markup and hydration keeps it. That type is
 *     not executed, so the strict `script-src 'self'` CSP does not block it;
 *   · `data-prerendered="/"` on #root, which `main.tsx` checks before hydrating;
 *   · a `<noscript>` block, on EVERY route, carrying the headline, the two hero
 *     paragraphs and the disclaimer.
 *
 * Non-Story routes get their own flat `dist/<route>.html` containing the correct per-route
 * head tags and the noscript block, but no prerendered body — those screens are
 * `React.lazy`, so `renderToString` would emit the Suspense fallback rather than content.
 * Netlify serves the per-route file ahead of the SPA fallback, so a crawler gets the right
 * title and description for every URL.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(root, 'dist')
const ssrOut = path.join(root, '.ssr-tmp')

const ROUTES = ['/', '/live', '/decisions', '/tracking', '/limits', '/equity', '/ledger', '/ignores']

const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'))

function fail(message) {
  console.error(`prerender: ${message}`)
  process.exit(1)
}

// ---------------------------------------------------------------- inputs
const indexPath = path.join(dist, 'index.html')
if (!fs.existsSync(indexPath)) fail('dist/index.html missing — run the client build first')

const overviewPath = path.join(dist, 'snapshot', 'api-overview.json')
const manifestPath = path.join(dist, 'snapshot', 'manifest.json')
if (!fs.existsSync(overviewPath)) {
  // Prerendering with no data would bake em dashes into the static HTML and quietly
  // publish a page claiming the system has run for "—" days.
  fail('dist/snapshot/api-overview.json missing — capture a snapshot before building')
}
const overview = readJson(overviewPath)
const manifest = fs.existsSync(manifestPath) ? readJson(manifestPath) : {}

// ------------------------------------------------------------ ssr bundle
await build({
  root,
  mode: 'public',
  logLevel: 'warn',
  build: {
    ssr: path.join(root, 'src', 'entry-server.tsx'),
    outDir: '.ssr-tmp',
    emptyOutDir: true,
    ssrEmitAssets: false,
    // The SSR bundle is a build artifact used once, in-process; a source map and a
    // minifier pass would only slow the build down.
    minify: false,
    sourcemap: false,
  },
})

const entry = path.join(ssrOut, 'entry-server.js')
if (!fs.existsSync(entry)) fail(`SSR bundle not produced at ${entry}`)
const { render } = await import(`file://${entry}`)

// -------------------------------------------------------------- render
const { html: body } = render({ overview })
if (!body || body.length < 500) fail(`rendered body implausibly small (${body?.length ?? 0} bytes)`)

// -------------------------------------------------------------- noscript
const escape = (s) =>
  String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

// Read the canonical strings straight out of the rendered markup's source of truth by
// importing the copy module from the SSR bundle's dependency graph would be circular;
// instead the copy is re-imported from the same built bundle.
const copy = await import(`file://${path.join(ssrOut, 'entry-server.js')}`)
  .then(() => import(`file://${entry}`))
  .then((m) => m)
// entry-server does not re-export copy; read it from source instead (single source of truth
// is copy.ts, and this script must not restate the sentences).
const copySrc = fs.readFileSync(path.join(root, 'src', 'content', 'copy.ts'), 'utf8')
const headline = /headline:\s*'([^']+)'/.exec(copySrc)?.[1]
if (!headline) fail('could not read STORY_HERO.headline out of copy.ts')

const days = (() => {
  const clocks = (overview.accounts ?? [])
    .map((a) => a.clock)
    .filter((c) => c && c.asset_class === 'us_equity')
  return clocks.length ? Math.max(...clocks.map((c) => c.calendar_days_elapsed)) : null
})()

// The disclaimer and hero paragraphs are pulled from the RENDERED body so the noscript
// block cannot drift from what the page says. Strip tags, collapse whitespace.
const textOf = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
const bodyText = textOf(body)
const disclaimerStart = bodyText.indexOf('quantlab trades simulated money')
if (disclaimerStart === -1) fail('disclaimer not found in the rendered body')
const disclaimer = bodyText.slice(disclaimerStart, bodyText.indexOf('at risk.', disclaimerStart) + 8)

const noscript = `<noscript><div style="max-width:44rem;margin:0 auto;padding:2rem 1.25rem;font-family:Georgia,serif;color:#221f18;background:#f7f2e9"><p style="font-size:.75rem;letter-spacing:.18em;text-transform:uppercase;color:#8f5113">A MonzonAutomation project</p><h1 style="font-size:2rem;line-height:1.1;margin:1rem 0">${escape(headline)}</h1><p style="line-height:1.6">Glass Box is the public window into quantlab — an autonomous trading-research system that trades simulated money using rules written down before it ever saw a result, then publishes every decision it makes, every mistake it catches, and everything it deliberately refuses to know.</p><p style="line-height:1.6">It has been running unattended for ${days ?? '—'} days. Nothing here is investment advice, and no real money is at risk.</p><p style="line-height:1.6"><a href="/" style="color:#1e5141">The full story, with figures, needs JavaScript enabled.</a></p><hr style="border:0;border-top:1px solid rgba(34,31,24,.16);margin:1.5rem 0"><p style="font-size:.75rem;line-height:1.6;color:#645f4e">${escape(disclaimer)}</p></div></noscript>`

// -------------------------------------------------------------- write
const template = fs.readFileSync(indexPath, 'utf8')
if (!template.includes('<div id="root"></div>')) fail('index.html has no empty #root to fill')

const dataBlock =
  `<script type="application/json" id="glassbox-preload">${JSON.stringify({ overview })
    .replace(/</g, '\\u003c')}</script>`

const storyHtml = template.replace(
  '<div id="root"></div>',
  `<div id="root" data-prerendered="/">${body}</div>\n    ${dataBlock}\n    ${noscript}`,
)
fs.writeFileSync(indexPath, storyHtml)

// Per-route shells: correct head tags, noscript, empty #root (lazy screens render client-side).
const NAV = (() => {
  const out = {}
  const re = /'(\/[a-z]*)':\s*\{\s*label:[^}]*?title:\s*'([^']+)',\s*description:\s*\n?\s*((?:'[^']*'\s*\+?\s*)+)/g
  let m
  while ((m = re.exec(copySrc)) !== null) {
    const desc = m[3].split(/'\s*\+\s*/).map((x) => x.replace(/^'|'$/g, '')).join('')
    out[m[1]] = { title: m[2], description: desc }
  }
  return out
})()

let written = 1
for (const route of ROUTES) {
  if (route === '/') continue
  const meta = NAV[route]
  let page = template.replace('<div id="root"></div>', `<div id="root"></div>\n    ${noscript}`)
  if (meta) {
    page = page
      .replace(/<title>[^<]*<\/title>/, `<title>${escape(meta.title)}</title>`)
      .replace(
        /(<meta\s+name="description"\s+content=")[^"]*(")/,
        `$1${escape(meta.description)}$2`,
      )
  }
  // FLAT `<route>.html`, not `<route>/index.html`. Netlify serves `/live` from
  // `live.html` with a 200; a directory index makes it 301 to `/live/` first, which adds
  // a redirect hop to every internal link and to every crawler request.
  fs.writeFileSync(path.join(dist, `${route.replace(/^\//, '')}.html`), page)
  written += 1
}

fs.rmSync(ssrOut, { recursive: true, force: true })

// -------------------------------------------------------------- verify
const final = fs.readFileSync(indexPath, 'utf8')
const checks = [
  ['headline present as literal text', final.includes(headline)],
  ['disclaimer present as literal text', final.includes('quantlab trades simulated money')],
  ['preload data block injected', final.includes('id="glassbox-preload"')],
  ['root marked prerendered', final.includes('data-prerendered="/"')],
  ['noscript block present', final.includes('<noscript>')],
]
for (const [name, ok] of checks) {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}`)
  if (!ok) process.exitCode = 1
}
console.log(
  `  prerendered ${written} html file(s); story body ${body.length} bytes, ` +
    `day count ${days ?? 'unknown'}`,
)
if (process.exitCode) fail('post-conditions not met')
