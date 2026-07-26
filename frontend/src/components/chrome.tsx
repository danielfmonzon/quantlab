/**
 * Persistent chrome: brand mark, snapshot banner, footer, and the per-route head manager.
 *
 * The banner exists because a static capture that looks live is a lie of omission. It
 * renders on EVERY screen in snapshot mode and never in live mode, states the capture
 * instant, and links to the manifest so the claim is checkable rather than decorative.
 */

import { useEffect } from 'react'
import { DATA_MODE, MANIFEST_URL, loadManifest } from '../lib/transport'
import type { SnapshotManifest } from '../lib/transport'
import { useApi } from '../lib/useApi'
import { BUILT_BY, DISCLAIMER, NAV_COPY } from '../content/copy'

// --------------------------------------------------------------------------- //
// Brand mark                                                                  //
// --------------------------------------------------------------------------- //

/**
 * The MonzonAutomation mark, reproduced from `dma-website`: display-serif wordmark, an
 * 11px honey dot with a glow ring, and a tracked uppercase sub-line. Typographic rather
 * than an image asset, exactly as on the marketing site — see docs/brand.md §3.
 */
export function BrandMark({ sub = 'Glass Box' }: { sub?: string }) {
  return (
    <span className="flex items-center gap-[0.65em]" data-testid="brand-mark">
      <span
        aria-hidden
        className="h-[11px] w-[11px] flex-none rounded-full bg-honey"
        style={{ boxShadow: '0 0 0 4px rgba(212,154,78,.22)' }}
      />
      <span className="leading-tight">
        <span className="block font-display text-[1.1rem] font-semibold tracking-[-0.02em] text-ink">
          MonzonAutomation
        </span>
        <span className="mt-px block font-sans text-[0.6rem] font-semibold uppercase tracking-[0.16em] text-muted">
          {sub}
        </span>
      </span>
    </span>
  )
}

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
      className="border-b border-clay/25 bg-honey/[0.14] px-5 py-1.5 lg:px-10"
      data-testid="snapshot-banner"
      role="status"
    >
      <p className="text-2xs leading-relaxed text-clay">
        {m ? (
          <>
            <span aria-hidden className="mr-1.5">
              ◷
            </span>
            <span className="font-semibold">Snapshot of {stampUtc(m.generated_at)}</span>
            <span className="text-clay"> · </span>
            quantlab {m.quantlab_version} @{' '}
            <span className="font-mono">{m.git_commit}</span>
            <span className="text-clay"> · </span>
            refreshed manually
            <span className="text-clay"> · </span>
            <a
              href={MANIFEST_URL}
              className="underline decoration-dotted underline-offset-2 hover:text-ink"
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
      className="mt-16 border-t border-ink/[0.10] bg-cream-3/50 px-5 py-10 lg:px-10"
      data-testid="footer"
    >
      <div className="mx-auto max-w-shell">
        <div className="max-w-measure">
          <BrandMark sub="Glass Box" />
        </div>

        <p
          className="mt-6 max-w-[70ch] text-2xs leading-relaxed text-muted"
          data-testid="disclaimer"
        >
          {DISCLAIMER}
        </p>

        <div className="mt-7 flex flex-wrap items-baseline justify-between gap-4 border-t border-ink/[0.10] pt-5">
          <p className="text-2xs text-muted">
            {BUILT_BY.prefix}{' '}
            <a
              href={BUILT_BY.orgHref}
              className="text-ink-2 underline decoration-dotted underline-offset-2 hover:text-clay"
              data-testid="built-by-name"
            >
              {BUILT_BY.name}
            </a>
            <span className="text-muted"> · </span>
            {BUILT_BY.links.map((link, index) => (
              <span key={link.label}>
                {index > 0 ? <span className="text-muted"> · </span> : null}
                <a
                  href={link.href}
                  className="underline decoration-dotted underline-offset-2 hover:text-clay"
                  data-testid={`built-by-${link.label.toLowerCase()}`}
                >
                  {link.label}
                </a>
              </span>
            ))}
          </p>
          <p className="font-mono text-2xs text-muted" data-testid="footer-version">
            {version ? `quantlab ${version}` : 'quantlab'}
            {commit ? ` @ ${commit}` : ''}
            <span> · {DATA_MODE} mode</span>
          </p>
        </div>
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
 * `index.html` ships all of these, but creating on demand means the manager works in any
 * host document — and a silent no-op when a tag is missing is the kind of gap that only
 * shows up as a wrong share card weeks later.
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

const setLink = (rel: string, href: string): void => {
  let el = document.head.querySelector(`link[rel="${rel}"]`)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

/**
 * Absolute URL for a route, from the origin the page is actually served from.
 *
 * Reading `location.origin` rather than a baked-in constant means a Netlify preview
 * deploy self-references correctly instead of pointing its canonical at production.
 */
const absolute = (route: string): string => {
  const origin = typeof window === 'undefined' ? '' : window.location.origin
  return `${origin}${route === '/' ? '/' : route}`
}

/** Per-route `<title>`, description, canonical, and the matching OG/Twitter values. */
export function useDocumentHead(route: string): void {
  useEffect(() => {
    const copy = NAV_COPY[route] ?? NAV_COPY['/']
    if (!copy) return
    document.title = copy.title
    setMeta('name', 'description', copy.description)
    setMeta('property', 'og:title', copy.title)
    setMeta('property', 'og:description', copy.description)
    setMeta('property', 'og:url', absolute(route))
    setMeta('name', 'twitter:title', copy.title)
    setMeta('name', 'twitter:description', copy.description)
    // Absolute, not path-relative: Lighthouse rejects a relative canonical, and a
    // relative one is ambiguous across the apex/subdomain split anyway.
    setLink('canonical', absolute(route))
  }, [route])
}
