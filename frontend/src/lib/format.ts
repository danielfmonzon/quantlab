/** Formatting helpers. Every one renders a null as an explicit dash, never 0. */

export const money = (v: number | null | undefined): string =>
  v === null || v === undefined
    ? '—'
    : v.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export const pct = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`

export const signedPct = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(digits)}%`

export const bps = (v: number | null | undefined, digits = 0): string =>
  v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(digits)} bps`

/** Compact UTC stamp: `2026-07-24 14:00:07Z`. Times matter here, so seconds stay. */
export const stamp = (iso: string | null | undefined): string => {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 19)}Z`
}

export const dayOf = (iso: string | null | undefined): string =>
  !iso ? '—' : iso.slice(0, 10)

/** Account label as displayed: underscores read badly in a heading. */
export const accountName = (label: string): string => label.replace(/_/g, ' ')
