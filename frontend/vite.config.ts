import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build output lands in `dist/`, which `quantlab glassbox serve` mounts at the
// server root. Asset URLs are therefore ABSOLUTE (`/assets/...`): a relative base
// would resolve against the current route's directory, so a deep link with a
// trailing slash (`/divergence/`) would look for `/divergence/assets/...`, miss, and
// get the SPA fallback HTML back in place of its JavaScript.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    // Recharts + d3 are ~550 kB on their own and are one third-party dependency in
    // a long-lived, separately-cached chunk; app code is ~50 kB. Splitting the
    // vendor chunk further would not help a localhost-only tool, so the warning
    // threshold is raised deliberately rather than left firing on every build.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Charting changes far less often than app code: give it its own chunk so a
        // UI edit does not invalidate 550 kB of cache.
        manualChunks: { charts: ['recharts'] },
      },
    },
  },
  server: {
    // `npm run dev` proxies /api to a locally running `quantlab glassbox serve`.
    proxy: { '/api': 'http://127.0.0.1:8600' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./test/setup.ts'],
    globals: true,
    include: ['test/**/*.test.tsx', 'test/**/*.test.ts'],
    css: false,
  },
})
