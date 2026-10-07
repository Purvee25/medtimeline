import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Trend } from '../api/schemas'
import { formatValue } from '../format'
import { TrendChart } from './TrendChart'

const trend: Trend = {
  marker: 'crp',
  name: 'C-Reactive Protein',
  loinc: '1988-5',
  unit: 'mg/L',
  reference_range: { low: 0, high: 5, approximate: true },
  points: [
    { date: '2025-01-01', value: 3, verified: false, report_id: 'a', center: 'Apex' },
    { date: '2025-05-01', value: 9.4, verified: true, report_id: 'b', center: null },
  ],
}

describe('TrendChart', () => {
  it('draws one point per result and marks unverified ones', () => {
    const { container } = render(<TrendChart trend={trend} />)
    expect(container.querySelectorAll('circle.point')).toHaveLength(2)
    expect(container.querySelectorAll('circle.point.unverified')).toHaveLength(1)
    expect(screen.getByText('9.4 mg/L')).toBeInTheDocument()
    expect(screen.getByText(/Approximate reference range/)).toBeInTheDocument()
  })

  it('reads values with the keyboard', () => {
    render(<TrendChart trend={trend} />)
    const chart = screen.getByRole('img')
    const live = screen.getByRole('status')
    expect(live).toBeEmptyDOMElement()
    fireEvent.keyDown(chart, { key: 'ArrowRight' })
    expect(live).toHaveTextContent('3 mg/L')
    expect(live).toHaveTextContent('Apex, Not yet reviewed')
    fireEvent.keyDown(chart, { key: 'ArrowRight' })
    expect(live).toHaveTextContent('Self-uploaded, Verified')
  })

  it('handles a single result without dividing by zero', () => {
    const one = { ...trend, points: trend.points.slice(0, 1) }
    const { container } = render(<TrendChart trend={one} />)
    const cx = Number(container.querySelector('circle.point')?.getAttribute('cx'))
    expect(Number.isFinite(cx)).toBe(true)
  })
})

describe('formatValue', () => {
  it.each([
    [20, '20'],
    [0, '0'],
    [10, '10'],
    [12.5, '12.5'],
    [3.82, '3.82'],
    [9.4, '9.4'],
    [264, '264'],
    [0.40000001, '0.4'],
  ])('formats %s as %s', (value, expected) => {
    expect(formatValue(value)).toBe(expected)
  })
})

it('keeps one persistent live region and stays silent on hover', () => {
  const { container } = render(<TrendChart trend={trend} />)
  const svg = container.querySelector('svg') as SVGSVGElement
  fireEvent.pointerMove(svg, { clientX: 10 })
  expect(screen.getAllByRole('status')).toHaveLength(1)
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
  expect(container.querySelector('.tooltip')).toHaveAttribute('aria-hidden', 'true')
})
