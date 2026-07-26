/**
 * Navigation: a sidebar on desktop, a top bar + slide-over below 768px.
 *
 * FOCUS TRAP. An open slide-over that leaks focus to the page behind it is worse than no
 * slide-over: a keyboard user tabs into content they cannot see and has no way back. So
 * while open, Tab cycles within the panel, Escape closes it, focus moves to the panel on
 * open and returns to the trigger on close, and the rest of the app is marked
 * `aria-hidden`. The trigger is ≥44px square (WCAG 2.2 target size).
 */

import { useEffect, useRef } from 'react'
import { ROUTES, Link } from '../lib/router'
import { NAV_COPY } from '../content/copy'
import { BrandMark } from './chrome'

const FOCUSABLE =
  'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"]), input, select'

function NavList({ route, onNavigate }: { route: string; onNavigate?: () => void }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {ROUTES.map((entry) => {
        const copy = NAV_COPY[entry.path]
        const active = entry.path === route
        return (
          <li key={entry.path}>
            <Link
              to={entry.path}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              className={`block min-h-touch rounded px-3 py-2 transition-colors ${
                active
                  ? 'bg-green/[0.09] text-ink'
                  : 'text-ink-2 hover:bg-cream-3 hover:text-ink'
              }`}
            >
              <span className="flex items-baseline text-sm font-medium">
                <span
                  aria-hidden
                  className={`mr-2 inline-block h-1.5 w-1.5 flex-none rounded-full ${
                    active ? 'bg-honey' : 'bg-transparent'
                  }`}
                />
                {copy?.label ?? entry.path}
              </span>
              {copy?.subtitle ? (
                <span className="ml-3.5 block text-2xs leading-snug text-muted">
                  {copy.subtitle}
                </span>
              ) : null}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

export function DesktopNav({ route }: { route: string }) {
  return (
    <nav
      aria-label="Primary"
      className="hidden shrink-0 border-r border-ink/[0.10] px-5 py-8 md:block md:w-60 lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto"
    >
      <Link to="/" className="block">
        <BrandMark sub="Glass Box" />
      </Link>
      <div className="mt-7">
        <NavList route={route} />
      </div>
      <p className="mt-7 max-w-[13rem] text-2xs leading-relaxed text-muted">
        Simulated money only. This interface is read-only — it cannot place, cancel, or
        halt anything.
      </p>
    </nav>
  )
}

export function MobileBar({
  route,
  open,
  onOpen,
  onClose,
}: {
  route: string
  open: boolean
  onOpen: () => void
  onClose: () => void
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement as HTMLElement | null
    // Move focus into the panel so the next Tab lands inside it.
    panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const nodes = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE)
      if (!nodes || nodes.length === 0) return
      const first = nodes[0]!
      const last = nodes[nodes.length - 1]!
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      // Return focus where the user left it, not to the top of the document.
      ;(previous ?? triggerRef.current)?.focus?.()
    }
  }, [open, onClose])

  return (
    <>
      <div className="flex items-center justify-between border-b border-ink/[0.10] bg-cream/95 px-5 py-3 md:hidden">
        <Link to="/">
          <BrandMark sub="Glass Box" />
        </Link>
        <button
          ref={triggerRef}
          type="button"
          onClick={onOpen}
          aria-expanded={open}
          aria-controls="mobile-nav-panel"
          className="inline-flex h-touch w-touch items-center justify-center rounded border border-ink/[0.16] bg-cream-2 text-ink"
          data-testid="mobile-nav-trigger"
        >
          <span className="sr-only">Open navigation menu</span>
          <span aria-hidden className="text-lg leading-none">
            ☰
          </span>
        </button>
      </div>

      {open ? (
        <div className="fixed inset-0 z-50 md:hidden" data-testid="mobile-nav-overlay">
          <button
            type="button"
            aria-label="Close navigation menu"
            onClick={onClose}
            className="absolute inset-0 h-full w-full bg-ink/40"
            tabIndex={-1}
          />
          <div
            ref={panelRef}
            id="mobile-nav-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 right-0 flex w-[min(20rem,88vw)] flex-col overflow-y-auto border-l border-ink/[0.16] bg-cream px-5 py-5 shadow-brand-lg"
            data-testid="mobile-nav-panel"
          >
            <div className="mb-6 flex items-center justify-between">
              <BrandMark sub="Glass Box" />
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-touch w-touch items-center justify-center rounded border border-ink/[0.16] bg-cream-2 text-ink"
                data-testid="mobile-nav-close"
              >
                <span className="sr-only">Close navigation menu</span>
                <span aria-hidden className="text-lg leading-none">
                  ✕
                </span>
              </button>
            </div>
            <NavList route={route} onNavigate={onClose} />
            <p className="mt-7 text-2xs leading-relaxed text-muted">
              Simulated money only. This interface is read-only.
            </p>
          </div>
        </div>
      ) : null}
    </>
  )
}
