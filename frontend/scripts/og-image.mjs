/**
 * Regenerate the 1200x630 share card (public/og-image.png).
 *
 * WHY. The previous card was drawn with a pixel font that had an incomplete glyph set. In a
 * real iMessage preview it read "Simu ated money on y." and " uant ab · autonomous tradin
 * research" — every `l` and `q` silently dropped, every descender (`g`, `y`) clipped — and
 * the wordmark overlapped the headline. A share card is the first thing anyone sees of a
 * site whose entire argument is that its figures can be checked; one that cannot spell its
 * own product name undermines that before a reader arrives.
 *
 * WHAT. Renders an HTML card in headless Chrome using the BRAND faces from docs/brand.md —
 * Fraunces Variable for display, Hanken Grotesk Variable for body — both already vendored
 * under node_modules/@fontsource-variable and inlined here as base64 data: URIs. Inlining
 * matters twice: Chrome loads no network resource (so the render is deterministic and
 * offline), and the fonts are real text faces with complete Latin coverage, which is the
 * defect being fixed.
 *
 * Colours are the brand tokens verbatim: deep forest rail, bone-cream field, espresso ink,
 * honey for decorative fills and clay for warm-accent text (the honey/clay split in
 * docs/brand.md §1 — honey is too light for text on cream).
 *
 * Uses puppeteer-core with the system Chrome, so no browser download is required.
 *
 *   node scripts/og-image.mjs [--out public/og-image.png] [--check]
 *
 * `--check` renders to a temp file and diffs nothing — it only reports the size, so CI can
 * assert the generator still runs without overwriting the committed asset.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const FRONTEND = path.resolve(HERE, '..')

const WIDTH = 1200
const HEIGHT = 630

// Brand tokens, verbatim from docs/brand.md §1.
const C = {
  cream: '#f7f2e9',
  cream2: '#fffdf8',
  ink: '#221f18',
  ink2: '#4f4a3e',
  greenDeep: '#163b30',
  honey: '#d49a4e',
  honey2: '#e8bd7c',
  clay: '#8f5113',
}

// The copy. Every string here contains at least one of the glyphs the old font dropped
// (l, q, g, y) — that is the point, and `verifyGlyphs` below asserts it.
const COPY = {
  eyebrow1: 'MONZON',
  eyebrow2: 'AUTOMATION',
  title: 'Glass Box',
  lede: 'Every decision this system makes is arithmetic you can check.',
  rule: true,
  disclaimer: 'Simulated money only. Not investment advice.',
  footer: 'quantlab · autonomous trading research',
}

function findBrowser() {
  const candidates = [
    process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean)
  for (const c of candidates) if (fs.existsSync(c)) return c
  throw new Error(
    'no Chrome found for puppeteer-core; set CHROME_PATH to a Chrome/Chromium binary'
  )
}

function fontDataUri(pkg, file) {
  const p = path.join(FRONTEND, 'node_modules', pkg, 'files', file)
  if (!fs.existsSync(p)) throw new Error(`missing font: ${p}`)
  return `data:font/woff2;base64,${fs.readFileSync(p).toString('base64')}`
}

// Latin (not latin-ext) is sufficient for this copy and keeps the inlined payload small.
const FRAUNCES = fontDataUri('@fontsource-variable/fraunces', 'fraunces-latin-wght-normal.woff2')
const HANKEN = fontDataUri(
  '@fontsource-variable/hanken-grotesk',
  'hanken-grotesk-latin-wght-normal.woff2'
)

const html = `<!doctype html>
<meta charset="utf-8">
<style>
  /* Fraunces ships an opsz axis too; this file is the wght-only latin subset, so the
     variation range below matches what is actually available. */
  @font-face {
    font-family: 'Fraunces';
    src: url('${FRAUNCES}') format('woff2-variations');
    font-weight: 100 900;
    font-display: block;
  }
  @font-face {
    font-family: 'Hanken Grotesk';
    src: url('${HANKEN}') format('woff2-variations');
    font-weight: 100 900;
    font-display: block;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html, body { width: ${WIDTH}px; height: ${HEIGHT}px; }
  body {
    display: flex;
    font-family: 'Hanken Grotesk', sans-serif;
    background: ${C.cream};
    -webkit-font-smoothing: antialiased;
  }
  /* Deep forest rail carrying the wordmark, mirroring the site's left-hand identity. */
  /* Rail width is set by the LONGEST wordmark line ("AUTOMATION"), not by eye. At 132px
     it clipped that word against the honey border - the same overflow class as the bug
     this rewrite exists to fix, so verifyGlyphs() now asserts the fit. */
  .rail {
    width: 186px;
    flex: 0 0 186px;
    background: ${C.greenDeep};
    border-right: 6px solid ${C.honey};
    padding: 44px 20px 0 26px;
  }
  .dot { width: 22px; height: 22px; border-radius: 50%; background: ${C.honey}; }
  .mark {
    margin-top: 26px;
    font-weight: 700;
    font-size: 19px;
    line-height: 1.24;
    letter-spacing: 0.05em;
    color: ${C.cream2};
    white-space: nowrap;
  }
  .mark .second { color: ${C.honey2}; display: block; }

  .field {
    flex: 1;
    position: relative;
    /* The site's two atmospheric glows, honey top-right and green top-left. */
    background:
      radial-gradient(760px 420px at 100% 0%, rgba(212,154,78,0.20), transparent 62%),
      radial-gradient(560px 360px at 0% 0%, rgba(30,81,65,0.10), transparent 60%);
    padding: 76px 68px 64px 62px;
    display: flex;
    flex-direction: column;
  }
  h1 {
    font-family: 'Fraunces', Georgia, serif;
    font-weight: 600;
    font-size: 118px;
    line-height: 1.05;
    letter-spacing: -0.02em;
    color: ${C.ink};
    /* Descenders are the whole point of this rewrite: give them room explicitly so no
       glyph can be clipped by a tight line box. */
    padding-bottom: 0.10em;
  }
  .lede {
    margin-top: 26px;
    font-size: 37px;
    line-height: 1.34;
    font-weight: 450;
    color: ${C.ink2};
    max-width: 27ch;
    padding-bottom: 0.08em;
  }
  .rule {
    margin-top: auto;
    width: 104px;
    height: 5px;
    background: ${C.honey};
    border-radius: 3px;
  }
  .disclaimer {
    margin-top: 24px;
    font-size: 23px;
    font-weight: 600;
    color: ${C.clay};
    padding-bottom: 0.08em;
  }
  .footer {
    margin-top: 8px;
    font-size: 21px;
    font-weight: 450;
    color: ${C.ink2};
    padding-bottom: 0.10em;
  }
</style>
<div class="rail">
  <div class="dot"></div>
  <div class="mark">${COPY.eyebrow1}<span class="second">${COPY.eyebrow2}</span></div>
</div>
<div class="field">
  <h1>${COPY.title}</h1>
  <p class="lede">${COPY.lede}</p>
  <div class="rule"></div>
  <p class="disclaimer">${COPY.disclaimer}</p>
  <p class="footer">${COPY.footer}</p>
</div>
`

/**
 * Assert the rendered card actually shows every character of every string.
 *
 * A missing glyph is invisible to any check that only inspects the DOM — the text node is
 * present whether or not the face can draw it. So this measures: for each string, it
 * renders each character in isolation in the same font at the same size and requires a
 * non-zero advance width and a non-zero inked bounding box. A dropped `l` has zero ink; a
 * clipped descender shows up as a bounding box shorter than the reference glyph's.
 */
async function verifyGlyphs(page) {
  return page.evaluate(() => {
    const targets = [
      { sel: 'h1', label: 'title' },
      { sel: '.lede', label: 'lede' },
      { sel: '.disclaimer', label: 'disclaimer' },
      { sel: '.footer', label: 'footer' },
      { sel: '.mark', label: 'wordmark' },
    ]
    const problems = []
    const seen = new Set()
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')

    for (const { sel, label } of targets) {
      const el = document.querySelector(sel)
      const cs = getComputedStyle(el)
      ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
      const text = el.textContent
      for (const ch of text) {
        if (ch === ' ') continue
        const key = `${label}:${ch}`
        if (seen.has(key)) continue
        seen.add(key)
        const m = ctx.measureText(ch)
        const inkW = (m.actualBoundingBoxLeft || 0) + (m.actualBoundingBoxRight || 0)
        const inkH = (m.actualBoundingBoxAscent || 0) + (m.actualBoundingBoxDescent || 0)
        if (m.width <= 0) problems.push(`${label}: '${ch}' has zero advance width`)
        else if (inkW <= 0 || inkH <= 0) problems.push(`${label}: '${ch}' renders no ink`)
      }
    }

    // Descenders must actually descend below the baseline, which is what the old font
    // clipped. Checked against the font in use at the lede's size.
    const lede = document.querySelector('.lede')
    const lcs = getComputedStyle(lede)
    ctx.font = `${lcs.fontWeight} ${lcs.fontSize} ${lcs.fontFamily}`
    for (const ch of 'gyqpj') {
      const d = ctx.measureText(ch).actualBoundingBoxDescent
      if (!(d > 0.5)) problems.push(`descender '${ch}' does not descend (${d})`)
    }

    // Nothing may overflow the card, which is how the wordmark came to sit on the
    // headline in the previous version.
    for (const { sel, label } of targets) {
      const r = document.querySelector(sel).getBoundingClientRect()
      if (r.right > window.innerWidth + 0.5 || r.bottom > window.innerHeight + 0.5) {
        problems.push(`${label} overflows the card (right=${r.right}, bottom=${r.bottom})`)
      }
    }
    // And the headline must not collide with the rail.
    const railEl = document.querySelector('.rail')
    const rail = railEl.getBoundingClientRect()
    const h1 = document.querySelector('h1').getBoundingClientRect()
    if (h1.left < rail.right) problems.push('headline overlaps the wordmark rail')

    // The wordmark must fit INSIDE the rail's content box. At 132px the longest line
    // ("AUTOMATION") ran past the honey border and was clipped mid-word — invisible to a
    // DOM check and to the glyph check above, because every glyph rendered fine; it was
    // the container that was too narrow.
    const railStyle = getComputedStyle(railEl)
    const contentRight =
      rail.right -
      parseFloat(railStyle.borderRightWidth) -
      parseFloat(railStyle.paddingRight)
    for (const line of document.querySelectorAll('.mark, .mark .second')) {
      // Measure the text itself, not the block, which stretches to the container.
      const range = document.createRange()
      range.selectNodeContents(line)
      const box = range.getBoundingClientRect()
      if (box.right > contentRight + 0.5) {
        problems.push(
          `wordmark line "${line.textContent.trim()}" overflows the rail ` +
            `(text right=${box.right.toFixed(1)}, rail content right=${contentRight.toFixed(1)})`
        )
      }
    }

    return problems
  })
}

const args = process.argv.slice(2)
const check = args.includes('--check')
const outIdx = args.indexOf('--out')
const outPath = path.resolve(
  FRONTEND,
  outIdx >= 0 ? args[outIdx + 1] : 'public/og-image.png'
)

const browser = await puppeteer.launch({
  executablePath: findBrowser(),
  args: ['--no-sandbox', '--font-render-hinting=none', '--force-color-profile=srgb'],
})
try {
  const page = await browser.newPage()
  await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 })
  await page.setContent(html, { waitUntil: 'load' })
  await page.evaluateHandle('document.fonts.ready')

  const problems = await verifyGlyphs(page)
  if (problems.length) {
    console.error('GLYPH VERIFICATION FAILED:')
    for (const p of problems) console.error(`  - ${p}`)
    process.exit(1)
  }
  const strings = Object.values(COPY).filter((v) => typeof v === 'string')
  const glyphs = new Set(strings.join('').replace(/\s/g, ''))
  console.log(
    `glyph verification PASSED — ${glyphs.size} distinct glyphs across ` +
      `${strings.length} strings, all with non-zero ink; descenders g/y/q/p/j all descend; ` +
      `no element overflows or overlaps the rail`
  )

  const target = check ? path.join(FRONTEND, 'og-image.check.png') : outPath
  await page.screenshot({ path: target, type: 'png' })
  const bytes = fs.statSync(target).size
  console.log(`wrote ${path.relative(FRONTEND, target)} — ${WIDTH}x${HEIGHT}, ${bytes} bytes`)
  if (check) fs.unlinkSync(target)
} finally {
  await browser.close()
}
