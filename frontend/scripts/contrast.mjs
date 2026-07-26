/**
 * WCAG 2.2 contrast audit over the Glass Box token set.
 *
 * Exact sRGB relative-luminance math (WCAG 2.x definition), not an approximation, so
 * the ratios printed here are the ratios a checker will report. Exits non-zero on any
 * failure, so it can gate a build.
 *
 *   node scripts/contrast.mjs            # table + verdict
 *   node scripts/contrast.mjs --md       # markdown table for the report
 */

const TOKENS = {
  // Brand — adopted unchanged from dma-website/src/styles/global.css
  cream: '#f7f2e9',
  'cream-2': '#fffdf8',
  'cream-3': '#efe7d6',
  'cream-4': '#e6dcc7',
  ink: '#221f18',
  'ink-2': '#4f4a3e',
  muted: '#645f4e',
  green: '#1e5141',
  'green-2': '#2c6b55',
  'green-deep': '#163b30',
  honey: '#d49a4e',
  'honey-2': '#e8bd7c',
  clay: '#8f5113',
  // Glass Box semantic additions (see docs/brand.md §5a)
  'signal-ok': '#1e5141',
  'signal-warn': '#8f5113',
  'signal-info': '#1d4e6b',
  'signal-danger': '#8c2f1d',
  'signal-idle': '#645f4e',
}

const BACKGROUNDS = ['cream', 'cream-2', 'cream-3']

/** Foreground/background pairs the UI actually renders, with their context. */
const PAIRS = [
  ['ink', 'cream', 'body text, headings'],
  ['ink', 'cream-2', 'text on raised cards'],
  ['ink', 'cream-3', 'text on alt sections'],
  ['ink-2', 'cream', 'secondary paragraph text'],
  ['ink-2', 'cream-2', 'secondary text on cards'],
  ['muted', 'cream', 'captions, chart mechanics'],
  ['muted', 'cream-2', 'captions on cards'],
  ['muted', 'cream-3', 'captions on alt sections'],
  ['green', 'cream', 'links, active nav, TRACKING'],
  ['green', 'cream-2', 'links on cards'],
  ['green', 'cream-3', 'links on alt sections'],
  ['clay', 'cream', 'eyebrow, DIVERGING, catch-up'],
  ['clay', 'cream-2', 'warning text on cards'],
  ['clay', 'cream-3', 'warning text on alt sections'],
  ['signal-info', 'cream', 'leaked marks, raw links'],
  ['signal-info', 'cream-2', 'source paths on cards'],
  ['signal-danger', 'cream', 'live KILL'],
  ['signal-danger', 'cream-2', 'live KILL on cards'],
  ['signal-idle', 'cream-2', 'unknown values'],
  // Inverted: text on filled brand surfaces
  ['cream', 'green', 'primary button label'],
  ['cream', 'green-deep', 'text on deep panels'],
  ['ink', 'honey', 'honey button label'],
  ['ink', 'honey-2', 'honey hover label'],
]

const srgbToLinear = (c) => {
  const v = c / 255
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
}

const luminance = (hex) => {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return (
    0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b)
  )
}

export const ratio = (fg, bg) => {
  const a = luminance(fg)
  const b = luminance(bg)
  const [hi, lo] = a > b ? [a, b] : [b, a]
  return (hi + 0.05) / (lo + 0.05)
}

const AA_NORMAL = 4.5
const AA_LARGE = 3.0
const AAA_NORMAL = 7.0

const rows = PAIRS.map(([fg, bg, context]) => {
  const value = ratio(TOKENS[fg], TOKENS[bg])
  return {
    fg,
    bg,
    context,
    ratio: value,
    aa: value >= AA_NORMAL,
    aaLarge: value >= AA_LARGE,
    aaa: value >= AAA_NORMAL,
  }
})

const failures = rows.filter((r) => !r.aa)
const md = process.argv.includes('--md')

if (md) {
  console.log('| foreground | background | measured | AA (4.5:1) | AAA (7:1) | used for |')
  console.log('| --- | --- | --- | --- | --- | --- |')
  for (const r of rows) {
    console.log(
      `| \`${r.fg}\` ${TOKENS[r.fg]} | \`${r.bg}\` ${TOKENS[r.bg]} | **${r.ratio.toFixed(2)}:1** | ${
        r.aa ? 'PASS' : r.aaLarge ? 'large-only' : 'FAIL'
      } | ${r.aaa ? 'PASS' : '—'} | ${r.context} |`,
    )
  }
} else {
  const w = Math.max(...rows.map((r) => r.fg.length))
  const wb = Math.max(...rows.map((r) => r.bg.length))
  console.log('WCAG 2.2 contrast audit — Glass Box tokens\n')
  for (const r of rows) {
    const verdict = r.aa ? 'AA  ' : r.aaLarge ? 'large' : 'FAIL '
    const aaa = r.aaa ? ' AAA' : ''
    console.log(
      `  ${r.fg.padEnd(w)} on ${r.bg.padEnd(wb)}  ${r.ratio.toFixed(2).padStart(5)}:1  ${verdict}${aaa}   ${r.context}`,
    )
  }
  console.log(
    `\n${rows.length} pairs · ${rows.filter((r) => r.aa).length} AA · ` +
      `${rows.filter((r) => r.aaa).length} AAA · ${failures.length} failing`,
  )
}

if (failures.length > 0) {
  console.error(
    '\nFAIL: ' +
      failures.map((f) => `${f.fg} on ${f.bg} (${f.ratio.toFixed(2)}:1)`).join(', '),
  )
  process.exit(1)
}
export { TOKENS, BACKGROUNDS }
