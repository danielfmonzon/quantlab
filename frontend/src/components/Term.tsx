/**
 * <Term> — a glossary term with a definition card.
 *
 * ACTIVATION IS CLICK/FOCUS, NEVER HOVER-ONLY. A hover-only disclosure is unreachable on
 * a touch screen and unreachable by keyboard, so the definition would be visible only to
 * readers using a mouse — the group least likely to need it. This is a real `<button>`:
 * it is in the tab order, it opens on Enter/Space/click, it closes on Escape, and the card
 * is associated with it through `aria-describedby` so a screen reader announces the
 * definition rather than only the dotted underline.
 *
 * The card is rendered inline (not portalled) so it inherits the paragraph's reading
 * order — a portalled tooltip lands at the end of the DOM, which is the wrong place for
 * a screen reader to encounter it.
 */

import { useEffect, useId, useRef, useState } from 'react'
import { lookupTerm } from '../content/glossary'

export function Term({
  children,
  term,
}: {
  children: React.ReactNode
  /** Glossary key. Defaults to the rendered text. */
  term?: string
}) {
  const key = term ?? (typeof children === 'string' ? children : '')
  const entry = lookupTerm(key)
  const [open, setOpen] = useState(false)
  const id = useId()
  const wrapRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onPointer = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onPointer)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onPointer)
    }
  }, [open])

  // An unknown term renders as plain text rather than a dead affordance.
  if (!entry) return <>{children}</>

  return (
    <span className="relative inline" ref={wrapRef}>
      <button
        type="button"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((v) => !v)}
        className="cursor-help border-b border-dotted border-clay/70 bg-transparent p-0 text-left
                   font-[inherit] text-[inherit] hover:border-clay hover:text-clay"
        data-testid="term"
        data-term={entry.term}
      >
        {children}
        <span className="sr-only"> (glossary term — activate for definition)</span>
      </button>

      {open ? (
        <span
          id={id}
          role="note"
          className="absolute left-0 top-full z-30 mt-2 block w-[min(22rem,calc(100vw-2rem))]
                     rounded-brand border border-ink/[0.16] bg-cream-2 p-4 text-left shadow-brand-md"
          data-testid="term-card"
        >
          <span className="mb-1.5 block font-display text-sm font-semibold text-ink">
            {entry.term}
          </span>
          <span className="block text-xs leading-relaxed text-ink-2">{entry.meaning}</span>
          <span className="mt-2 block border-t border-ink/[0.10] pt-2 text-xs leading-relaxed text-muted">
            <span className="font-semibold text-clay">Why it matters: </span>
            {entry.matters}
          </span>
        </span>
      ) : null}
    </span>
  )
}
