/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark-first surface ramp. Near-black rather than pure black so elevation
        // reads through subtle steps instead of borders everywhere.
        ink: {
          900: '#0a0b0d', 800: '#101216', 700: '#161920',
          600: '#1e222b', 500: '#2a2f3a', 400: '#3a4150',
        },
        // Muted, non-alarming semantics. Amber (not red) carries DIVERGING: a
        // diverging week is a question, not an emergency.
        signal: {
          ok: '#4ade80', warn: '#fbbf24', idle: '#8b93a7', info: '#60a5fa',
          // Paper is the bright line (what happened); shadow is the muted
          // reference (what should have happened).
          paper: '#e2e8f0', shadow: '#7c88a1',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
      },
    },
  },
  plugins: [],
}
