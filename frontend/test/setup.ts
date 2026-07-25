import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

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
