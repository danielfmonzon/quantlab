/**
 * The no-chart-without-a-takeaway rule.
 *
 * COMPILE TIME: `takeaway` and `mechanics` are required, non-optional props on
 * `ChartProps`, so omitting either fails `tsc -b` — which `npm run build` runs
 * before Vite, meaning a chart with no stated conclusion cannot ship. The
 * `@ts-expect-error` cases below assert that statically: if the props ever became
 * optional, those lines would stop erroring and the test file would fail to compile.
 *
 * RUNTIME: the type system cannot catch an EMPTY string, so `Chart` also asserts at
 * render time. Both halves are needed; neither alone is sufficient.
 */

import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { Chart, ChartContractError, assertChartContract } from '../src/components/Chart'

const Plot = () => <svg data-testid="plot" />

describe('Chart contract — runtime', () => {
  it('renders takeaway, mechanics and a raw-data link', () => {
    render(
      <Chart
        title="divergence"
        takeaway="Every week tracked inside the threshold."
        mechanics="Bars are paper minus shadow in basis points."
        rawHref="/api/divergence"
      >
        <Plot />
      </Chart>,
    )
    expect(screen.getByTestId('chart-takeaway')).toHaveTextContent(
      'Every week tracked inside the threshold.',
    )
    expect(screen.getByTestId('chart-mechanics')).toHaveTextContent('basis points')
    expect(screen.getByTestId('chart-raw-link')).toHaveAttribute('href', '/api/divergence')
    expect(screen.getByTestId('plot')).toBeInTheDocument()
  })

  it('refuses to render a chart whose takeaway is empty', () => {
    expect(() =>
      render(
        <Chart title="empty takeaway" takeaway="" mechanics="Some mechanics." rawHref="/api/x">
          <Plot />
        </Chart>,
      ),
    ).toThrow(ChartContractError)
  })

  it('refuses to render a chart whose takeaway is only whitespace', () => {
    expect(() =>
      render(
        <Chart title="blank takeaway" takeaway="   " mechanics="Some mechanics." rawHref="/api/x">
          <Plot />
        </Chart>,
      ),
    ).toThrow(/must state its own conclusion/)
  })

  it('refuses to render a chart with no mechanics caption', () => {
    expect(() =>
      render(
        <Chart title="no mechanics" takeaway="A real takeaway." mechanics="" rawHref="/api/x">
          <Plot />
        </Chart>,
      ),
    ).toThrow(/how its numbers were produced/)
  })

  it('names the offending chart in the error', () => {
    expect(() =>
      assertChartContract({ title: 'risk gauge', takeaway: '', mechanics: 'x' }),
    ).toThrow(/"risk gauge"/)
  })

  it('accepts a well-formed contract', () => {
    expect(() =>
      assertChartContract({ title: 'ok', takeaway: 'A conclusion.', mechanics: 'A method.' }),
    ).not.toThrow()
  })
})

describe('Chart contract — compile time', () => {
  it('rejects a chart with no takeaway prop', () => {
    // @ts-expect-error takeaway is required: a chart may not ship without a conclusion.
    const missingTakeaway = <Chart title="t" mechanics="m" rawHref="/api/x"><Plot /></Chart>
    expect(missingTakeaway).toBeTruthy()
  })

  it('rejects a chart with no mechanics prop', () => {
    // @ts-expect-error mechanics is required: a chart may not ship without its method.
    const missingMechanics = <Chart title="t" takeaway="a" rawHref="/api/x"><Plot /></Chart>
    expect(missingMechanics).toBeTruthy()
  })

  it('rejects a chart with no rawHref prop', () => {
    // @ts-expect-error rawHref is required: the reader must be able to reach the numbers.
    const missingRaw = <Chart title="t" takeaway="a" mechanics="m"><Plot /></Chart>
    expect(missingRaw).toBeTruthy()
  })
})
