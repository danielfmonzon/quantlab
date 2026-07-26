/**
 * Glass Box design tokens — MonzonAutomation brand.
 *
 * Every colour and both typefaces are taken from `danielfmonzon/dma-website`
 * (`src/styles/global.css`). See `docs/brand.md` for the extraction, the measured
 * contrast ratios, and the three deliberate additions (semantic status colours, a
 * system mono stack, and the light-not-dark decision).
 *
 * Do not add a colour here without running `node scripts/contrast.mjs`. Every
 * foreground/background pair the UI renders is measured there and the script exits
 * non-zero on an AA failure.
 *
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // ---- brand, verbatim ------------------------------------------------
        cream: {
          DEFAULT: '#f7f2e9', // page background, warm bone
          2: '#fffdf8', // cards / raised
          3: '#efe7d6', // alt sections
          4: '#e6dcc7', // deeper panel edges
        },
        ink: {
          DEFAULT: '#221f18', // primary text, warm espresso
          2: '#4f4a3e', // secondary text
        },
        muted: '#645f4e', // tertiary / captions
        green: {
          DEFAULT: '#1e5141', // primary brand
          2: '#2c6b55', // hover / gradient
          deep: '#163b30', // deep panels
        },
        honey: {
          DEFAULT: '#d49a4e', // warm accent (decorative only — too light for text)
          2: '#e8bd7c',
        },
        clay: '#8f5113', // warm accent TEXT (readable)

        // ---- Glass Box semantic status (docs/brand.md §5a) -------------------
        // Each is dark enough to be TEXT on cream, not merely decorative. Measured
        // ratios on #f7f2e9: ok 8.16, warn 5.61, info 8.00, danger 7.42, idle 5.73.
        signal: {
          ok: '#1e5141', // = green. TRACKING, on-schedule, not-halted
          warn: '#8f5113', // = clay. DIVERGING, catch-up — amber-not-red survives
          info: '#1d4e6b', // leaked marks, links, active nav
          danger: '#8c2f1d', // live KILL only
          idle: '#645f4e', // = muted. captions, unknown values
        },
      },
      fontFamily: {
        // Self-hosted via Fontsource — no external request, so the strict CSP holds.
        display: ['"Fraunces Variable"', 'Georgia', 'serif'],
        sans: ['"Hanken Grotesk Variable"', 'system-ui', '-apple-system', 'sans-serif'],
        // Not a brand face: tabular figures are worth the bytes, a branded mono is not.
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        // 12px, not 11px. At 11px this size covered ~59% of the text on a phone and
        // Lighthouse flagged the page as illegible on mobile — a real complaint, not a
        // metric artifact. 12px is the documented floor for body-adjacent text.
        '2xs': ['0.75rem', { lineHeight: '1.1rem', letterSpacing: '0.01em' }],
      },
      letterSpacing: {
        eyebrow: '0.18em', // brand .eyebrow
      },
      maxWidth: {
        measure: '58ch', // brand .lead cap
        shell: '1180px', // brand --maxw
      },
      borderRadius: {
        brand: '18px', // brand --r
        'brand-lg': '28px', // brand --r-lg
      },
      boxShadow: {
        // brand --shadow-sm / -md / -lg
        'brand-sm': '0 4px 16px -10px rgba(60,45,20,.40)',
        'brand-md': '0 20px 46px -24px rgba(60,45,20,.45)',
        'brand-lg': '0 44px 90px -42px rgba(50,38,16,.55)',
      },
      minHeight: {
        touch: '44px', // WCAG 2.2 target size
      },
      minWidth: {
        touch: '44px',
      },
    },
  },
  plugins: [],
}
