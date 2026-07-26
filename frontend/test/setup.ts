import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup, configure } from '@testing-library/react'

/**
 * Headroom for `findBy*`, which vitest's `testTimeout` does NOT govern.
 *
 * This is the setting that actually matters for the G4 flake. Testing Library's async
 * helpers use their own `asyncUtilTimeout`, defaulting to 1000ms, and a `findBy*` that
 * exhausts it throws at 1s — long before vitest's per-test timeout is in play. Raising
 * `testTimeout` alone (see `vite.config.ts`) would have looked like a fix and changed
 * nothing about the suspected failure mode.
 *
 * 5s, not 15s: this bound exists so a genuinely hung query still fails the run in reasonable
 * time. Only a query that would otherwise fail waits longer, so passing tests pay nothing.
 */
configure({ asyncUtilTimeout: 5_000 })

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

/**
 * Recharts measures its container to lay out; jsdom reports 0×0, which makes
 * ResponsiveContainer render nothing. Give every element a real box so charts
 * actually produce SVG in tests.
 */
Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
  configurable: true,
  value: 900,
})
Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
  configurable: true,
  value: 300,
})
Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
  configurable: true,
  value: () => ({
    width: 900,
    height: 300,
    top: 0,
    left: 0,
    right: 900,
    bottom: 300,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }),
})

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (ResizeObserverStub as never)
