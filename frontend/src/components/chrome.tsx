/**
 * Persistent chrome: the snapshot banner, the footer, and the per-route head manager.
 *
 * The banner exists because a static capture that looks live is a lie of omission. It
 * renders on EVERY screen in snapshot mode and never in live mode, states the capture
 * instant, and links to the manifest so the claim is checkable rather than decorative.
 */

import { useEffect } from 'react'
import { DATA_MODE, MANIFEST_URL, loadManifest } from '../lib/transport'
import type { SnapshotManifest } from '../lib/transport'
import { useApi } from '../lib/useApi'
import { BUILT_BY, DISCLAIMER, NAV_COPY, PLACEHOLDER_DISCLAIMER } from '../content/copy'

// --------------------------------------------------------------------------- //
// Snapshot banner                                                             //
// --------------------------------------------------------------------------- //

const stampUtc = (iso: string): string => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`
}

export function SnapshotBanner() {
  // In live mode this component renders nothing at all and never fetches.
  const enabled = DATA_MODE === 'snapshot'
  const manifest = useApi<SnapshotManifest | null>(
    () => (enabled ? loadManifest() : Promise.resolve(null)),
    [enabled],
  )

  if (!enabled) return null

  const m = manifest.data
  return (
    <div
      className="border-b border-signal-warn/25 bg-signal-warn/[0.07] px-6 py-1.5 lg:px-10"
      data-testid="snapshot-banner"
      role="status"
    >
      <p className="text-2xs leading-relaxed text-signal-warn/90">
        {m ? (
          <>
            <span className="font-medium">Snapshot of {stampUtc(m.generated_at)}</span>
            <span className="text-signal-warn/50"> · </span>
            quantlab {m.quantlab_version} @{' '}
            <span className="font-mono">{m.git_commit}</span>
            <span className="text-signal-warn/50"> · </span>
            refreshed manually
            <span className="text-signal-warn/50"> · </span>
            <a
              href={MANIFEST_URL}
              className="underline decoration-dotted underline-offset-2 hover:text-slate-100"
              data-testid="snapshot-manifest-link"
            >
              manifest.json
            </a>
          </>
        ) : manifest.error ? (
          <>Static snapshot build — manifest unreadable ({manifest.error}).</>
        ) : (
          <>Static snapshot build — reading manifest…</>
        )}
      </p>
    </div>
  )
}

// --------------------------------------------------------------------------- //
// Footer                                                                      //
// --------------------------------------------------------------------------- //

export function Footer({
  version,
  commit,
}: {
  version: string | null
  commit: string | null
}) {
  return (
    <footer
      className="mt-16 border-t border-ink-600 px-6 py-8 lg:px-10"
      data-testid="footer"
    >
      {PLACEHOLDER_DISCLAIMER ? (
        <p
          className="mb-3 text-2xs font-medium uppercase tracking-widest text-signal-warn/80"
          data-testid="placeholder-disclaimer-warning"
        >
          ⚠ placeholder disclaimer — not the canonical F15 text
        </p>
      ) : null}

      <p
        className="max-w-4xl text-2xs leading-relaxed text-signal-idle"
        data-testid="disclaimer"
      >
        {DISCLAIMER}
      </p>

      <div className="mt-6 flex flex-wrap items-baseline justify-between gap-4">
        <p className="text-2xs text-signal-idle">
          {BUILT_BY.prefix}{' '}
          <span className="text-slate-300">{BUILT_BY.name}</span>
          <span className="text-signal-idle/50"> · </span>
          {BUILT_BY.links.map((link, index) => (
            <span key={link.label}>
              {index > 0 ? <span className="text-signal-idle/50"> · </span> : null}
              <a
                href={link.href}
                className="underline decoration-dotted underline-offset-2 hover:text-slate-200"
                data-testid={`built-by-${link.label.toLowerCase()}`}
              >
                {link.label}
              </a>
            </span>
          ))}
        </p>
        <p className="font-mono text-2xs text-signal-idle/70" data-testid="footer-version">
          {version ? `quantlab ${version}` : 'quantlab'}
          {commit ? ` @ ${commit}` : ''}
          <span className="text-signal-idle/40"> · {DATA_MODE} mode</span>
        </p>
      </div>
    </footer>
  )
}

// --------------------------------------------------------------------------- //
// Head manager                                                                //
// --------------------------------------------------------------------------- //

/**
 * Set a meta tag's content, creating the tag if it is absent.
 *
 * `index.html` ships all of these, but creating on demand means the manager works in
 * any host document — and a silent no-op when a tag is missing is the kind of gap
 * that only shows up as a wrong share card weeks later.
 */
const setMeta = (kind: 'name' | 'property', key: string, value: string): void => {
  let el = document.head.querySelector(`meta[${kind}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(kind, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', value)
}

/**
 * Per-route `<title>` and `<meta description>`, plus the matching OG/Twitter values.
 *
 * A tiny effect rather than a library: eight routes with static copy do not need one,
 * and a client-rendered title is enough here because the audience is human readers,
 * not crawlers that refuse to run JavaScript. The static `index.html` still carries a
 * sensible default for anything that does not execute the bundle.
 */
export function useDocumentHead(route: string): void {
  useEffect(() => {
    const copy = NAV_COPY[route] ?? NAV_COPY['/']
    if (!copy) return
    document.title = copy.title
    setMeta('name', 'description', copy.description)
    setMeta('property', 'og:title', copy.title)
    setMeta('property', 'og:description', copy.description)
    setMeta('name', 'twitter:title', copy.title)
    setMeta('name', 'twitter:description', copy.description)
  }, [route])
}
