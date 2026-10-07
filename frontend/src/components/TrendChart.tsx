import { type KeyboardEvent, type PointerEvent, type RefObject, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { Trend, TrendPoint } from '../api/schemas'
import { formatValue } from '../format'

const DEFAULT_WIDTH = 720
const HEIGHT = 280
const MARGIN = { top: 16, right: 72, bottom: 32, left: 44 }
const PLOT_H = HEIGHT - MARGIN.top - MARGIN.bottom
const Y_TICKS = 5
const MAX_X_TICKS = 6
const MIN_PX_PER_X_TICK = 72
const DAY_MS = 86_400_000
const POINT_R = 4.5

const dateFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
const axisDateFmt = new Intl.DateTimeFormat(undefined, { month: 'short', year: '2-digit' })

function parseDay(iso: string): number {
  return Date.parse(`${iso}T00:00:00`)
}

/** Round step sizes (1, 2, 2.5, 5 × 10^n) so axis labels read cleanly. */
function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || Math.abs(max) || 1
  const raw = span / count
  const power = 10 ** Math.floor(Math.log10(raw))
  const step = ([1, 2, 2.5, 5, 10].find((m) => m * power >= raw) ?? 10) * power
  const start = Math.floor(min / step) * step
  const ticks: number[] = []
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toFixed(10)))
  return ticks
}

type Props = { trend: Trend }

/**
 * Track the container's width so the chart is laid out at real pixel size: text stays legible
 * on phones instead of the whole SVG (and its 12px labels) being scaled down.
 */
function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(DEFAULT_WIDTH)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.round(entry.contentRect.width))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return width
}

/**
 * One marker over time. Filled points are human-verified, hollow points are not yet reviewed;
 * the grey band is a generic, approximate reference range. Hover, or focus and use the arrow
 * keys, for exact values; the table below the chart carries the same data.
 */
export function TrendChart({ trend }: Props) {
  const titleId = useId()
  const figureRef = useRef<HTMLElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const width = Math.max(useWidth(figureRef), MARGIN.left + MARGIN.right + 1)
  const plotW = width - MARGIN.left - MARGIN.right
  const [active, setActive] = useState<number | null>(null)
  // Screen-reader announcement, set only by keyboard navigation so mouse movement stays silent.
  const [announcement, setAnnouncement] = useState('')
  const { points, reference_range: range, unit } = trend

  const geometry = useMemo(() => {
    const times = points.map((p) => parseDay(p.date))
    const tMin = Math.min(...times)
    const tMax = Math.max(...times)
    const tPad = tMax === tMin ? 30 * DAY_MS : 0
    const x = (t: number) => MARGIN.left + ((t - (tMin - tPad)) / (tMax + tPad - (tMin - tPad))) * plotW

    const values = points.map((p) => p.value)
    const yTicks = niceTicks(Math.min(...values, range.low), Math.max(...values, range.high), Y_TICKS)
    const yMin = yTicks[0] ?? 0
    const yMax = yTicks[yTicks.length - 1] ?? 1
    const y = (v: number) => MARGIN.top + PLOT_H - ((v - yMin) / (yMax - yMin || 1)) * PLOT_H

    const xs = times.map(x)
    const maxTicks = Math.max(2, Math.min(MAX_X_TICKS, Math.floor(plotW / MIN_PX_PER_X_TICK)))
    const tickIdx =
      points.length <= maxTicks
        ? points.map((_, i) => i)
        : [...new Set(Array.from({ length: maxTicks }, (_, i) => Math.round((i * (points.length - 1)) / (maxTicks - 1))))]
    return { xs, y, yTicks, tickIdx }
  }, [points, range.low, range.high, plotW])

  const { xs, y, yTicks, tickIdx } = geometry
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${xs[i]},${y(p.value)}`).join('')
  const last = points[points.length - 1]

  function nearest(clientX: number): number | null {
    const svg = svgRef.current
    if (!svg || !points.length) return null
    const box = svg.getBoundingClientRect()
    const vx = clientX - box.left
    let best = 0
    xs.forEach((px, i) => {
      if (Math.abs(px - vx) < Math.abs((xs[best] ?? 0) - vx)) best = i
    })
    return best
  }

  function onKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const step = event.key === 'ArrowRight' ? 1 : -1
    const next = Math.min(points.length - 1, Math.max(0, (active ?? (step > 0 ? -1 : points.length)) + step))
    setActive(next)
    const p = points[next]
    if (p) {
      const source = p.center ?? 'Self-uploaded'
      const state = p.verified ? 'Verified' : 'Not yet reviewed'
      setAnnouncement(`${formatValue(p.value)} ${unit}, ${dateFmt.format(parseDay(p.date))}, ${source}, ${state}`)
    }
  }

  const activePoint: TrendPoint | undefined = active === null ? undefined : points[active]
  const activeX = active === null ? 0 : (xs[active] ?? 0)

  return (
    <figure ref={figureRef} className="chart" style={{ margin: 0 }}>
      <svg
        ref={svgRef}
        width={width}
        height={HEIGHT}
        viewBox={`0 0 ${width} ${HEIGHT}`}
        role="img"
        aria-labelledby={titleId}
        tabIndex={0}
        onPointerMove={(e: PointerEvent<SVGSVGElement>) => setActive(nearest(e.clientX))}
        onPointerLeave={() => setActive(null)}
        onBlur={() => setActive(null)}
        onKeyDown={onKeyDown}
      >
        <title id={titleId}>
          {`${trend.name} over time, ${points.length} results in ${unit}. Use left and right arrow keys to read values.`}
        </title>

        <rect
          className="band"
          x={MARGIN.left}
          width={plotW}
          y={y(range.high)}
          height={Math.max(0, y(range.low) - y(range.high))}
        />

        <g className="grid">
          {yTicks.map((t) => (
            <line key={t} x1={MARGIN.left} x2={MARGIN.left + plotW} y1={y(t)} y2={y(t)} />
          ))}
        </g>
        {yTicks.map((t) => (
          <text key={t} className="tick" x={MARGIN.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
            {formatValue(t)}
          </text>
        ))}
        {tickIdx.map((i) => {
          const p = points[i]
          return p ? (
            <text key={i} className="tick" x={xs[i]} y={HEIGHT - 8} textAnchor="middle">
              {axisDateFmt.format(parseDay(p.date))}
            </text>
          ) : null
        })}

        {activePoint && (
          <line className="crosshair" x1={activeX} x2={activeX} y1={MARGIN.top} y2={MARGIN.top + PLOT_H} />
        )}

        <path className="series" d={path} />
        {points.map((p, i) => (
          <circle
            key={`${p.report_id}-${p.date}`}
            className={`point${p.verified ? '' : ' unverified'}`}
            cx={xs[i]}
            cy={y(p.value)}
            r={active === i ? POINT_R + 1.5 : POINT_R}
          />
        ))}

        {last && (
          <text className="end-label" x={(xs[xs.length - 1] ?? 0) + 10} y={y(last.value)} dy="0.32em">
            {`${formatValue(last.value)} ${unit}`}
          </text>
        )}
      </svg>

      {activePoint && (
        <div
          className="tooltip"
          style={{ left: activeX, top: y(activePoint.value) }}
          aria-hidden="true"
        >
          <strong>
            {formatValue(activePoint.value)} {unit}
          </strong>
          <div>{dateFmt.format(parseDay(activePoint.date))}</div>
          <div className="muted">
            {activePoint.center ?? 'Self-uploaded'} · {activePoint.verified ? 'Verified' : 'Not yet reviewed'}
          </div>
        </div>
      )}

      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>

      <figcaption className="legend">
        <span>
          <svg width="16" height="10" aria-hidden="true">
            <circle cx="8" cy="5" r="4" fill="var(--accent)" />
          </svg>
          Verified
        </span>
        <span>
          <svg width="16" height="10" aria-hidden="true">
            <circle cx="8" cy="5" r="3.5" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
          </svg>
          Not yet reviewed
        </span>
        <span>
          <svg width="16" height="10" aria-hidden="true">
            <rect width="16" height="10" rx="2" fill="var(--band)" />
          </svg>
          Approximate reference range ({formatValue(range.low)}–{formatValue(range.high)} {unit})
        </span>
      </figcaption>
    </figure>
  )
}
