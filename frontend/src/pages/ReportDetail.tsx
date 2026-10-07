import { type FormEvent, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import type { Marker, ReportObservations, ReportStatus } from '../api/schemas'
import { openReportFile, type ReviewedValue, useMarkers, useReport, useReview } from '../api/queries'
import { StatusBadge } from '../components/StatusBadge'
import { errorText, formatDate, issueText } from '../format'

const REVIEWABLE: ReadonlySet<ReportStatus> = new Set(['needs_review', 'extracted', 'failed'])

type Row = { key: number; marker_code: string; value: string; unit: string }

let nextKey = 0

/** Start the review from verified/stored values if any, otherwise from what extraction found. */
function initialRows(data: ReportObservations, markers: Map<string, Marker>): Row[] {
  const source = data.observations.length
    ? data.observations.map((o) => ({ marker: o.marker_code, value: o.value, unit: o.unit }))
    : (data.extraction?.results ?? []).map((r) => ({ marker: r.marker, value: r.value, unit: r.unit }))
  return source.map(({ marker, value, unit }) => {
    const known = markers.get(marker)
    return {
      key: nextKey++,
      marker_code: known ? marker : '',
      value: String(value),
      unit: known && known.units.includes(unit) ? unit : (known?.unit ?? ''),
    }
  })
}

function ReviewForm({ data, markers }: { data: ReportObservations; markers: Marker[] }) {
  const byCode = useMemo(() => new Map(markers.map((m) => [m.code, m])), [markers])
  const review = useReview(data.report.id)
  const [rows, setRows] = useState<Row[]>(() => initialRows(data, byCode))
  const [collectedOn, setCollectedOn] = useState(data.report.collected_on ?? data.extraction?.collected_on ?? '')

  function update(key: number, patch: Partial<Row>) {
    setRows((current) => current.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const observations: ReviewedValue[] = rows.map((r) => ({
      marker_code: r.marker_code,
      value: Number(r.value),
      unit: r.unit,
    }))
    review.mutate({ collected_on: collectedOn, observations })
  }

  return (
    <form className="card" onSubmit={onSubmit} aria-labelledby="review-title">
      <div className="stack">
        <h2 id="review-title">Review values</h2>
        <p className="small muted">
          Check each value against the PDF. Saving replaces this report's results with your verified values.
        </p>
      </div>

      <label style={{ maxWidth: 220 }}>
        Sample collected on
        <input type="date" value={collectedOn} onChange={(e) => setCollectedOn(e.target.value)} required />
      </label>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Test</th>
              <th className="num">Value</th>
              <th>Unit</th>
              <th>
                <span className="visually-hidden">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const marker = byCode.get(row.marker_code)
              return (
                <tr key={row.key}>
                  <td>
                    <select
                      aria-label={`Test for row ${i + 1}`}
                      value={row.marker_code}
                      required
                      onChange={(e) => {
                        const next = byCode.get(e.target.value)
                        update(row.key, { marker_code: e.target.value, unit: next?.unit ?? '' })
                      }}
                    >
                      <option value="" disabled>
                        Choose a test…
                      </option>
                      {markers.map((m) => (
                        <option key={m.code} value={m.code}>
                          {m.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="num">
                    <input
                      aria-label={`Value for row ${i + 1}`}
                      type="number"
                      step="any"
                      inputMode="decimal"
                      value={row.value}
                      required
                      style={{ width: 110, textAlign: 'right' }}
                      onChange={(e) => update(row.key, { value: e.target.value })}
                    />
                  </td>
                  <td>
                    <select
                      aria-label={`Unit for row ${i + 1}`}
                      value={row.unit}
                      required
                      disabled={!marker}
                      onChange={(e) => update(row.key, { unit: e.target.value })}
                    >
                      {(marker?.units ?? ['']).map((u) => (
                        <option key={u} value={u}>
                          {u || '—'}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link"
                      onClick={() => setRows((current) => current.filter((r) => r.key !== row.key))}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="row">
        <button
          type="button"
          onClick={() => setRows((current) => [...current, { key: nextKey++, marker_code: '', value: '', unit: '' }])}
        >
          Add a test
        </button>
        <button type="submit" className="primary" disabled={review.isPending || rows.length === 0}>
          {review.isPending ? 'Saving…' : 'Save verified values'}
        </button>
      </div>
      {review.isError && (
        <p className="alert error" role="alert">
          {errorText(review.error)}
        </p>
      )}
      {review.isSuccess && (
        <p className="small muted" role="status">
          Saved {review.data.length} verified values.
        </p>
      )}
    </form>
  )
}

export function ReportDetail() {
  const { id = '' } = useParams()
  const report = useReport(id)
  const markers = useMarkers()
  const [downloadError, setDownloadError] = useState<string | null>(null)

  if (report.isPending || markers.isPending) return <p className="muted">Loading report…</p>
  if (report.isError || markers.isError) {
    return (
      <p className="alert error" role="alert">
        {errorText(report.error ?? markers.error)}
      </p>
    )
  }

  const { report: meta, extraction, observations } = report.data
  const names = new Map(markers.data.map((m) => [m.code, m.name]))
  const flagged = extraction?.results.filter((r) => r.issues.length) ?? []

  return (
    <>
      <div className="page-head">
        <div>
          <p className="small">
            <Link to="/">← All reports</Link>
          </p>
          <h1>{meta.original_filename}</h1>
          <div className="row small muted" style={{ marginTop: 6 }}>
            <StatusBadge status={meta.status} />
            {meta.collected_on && <span>Collected {formatDate(meta.collected_on)}</span>}
            <span>{meta.center ?? 'Self-uploaded'}</span>
          </div>
        </div>
        {meta.status !== 'awaiting_upload' && meta.status !== 'rejected' && (
          <button
            type="button"
            onClick={() => openReportFile(meta.id).catch((err: unknown) => setDownloadError(errorText(err)))}
          >
            Open PDF
          </button>
        )}
      </div>

      {downloadError && (
        <p className="alert error" role="alert">
          {downloadError}
        </p>
      )}
      {meta.error && (
        <p className="alert error" role="alert">
          {meta.error}
        </p>
      )}
      {extraction?.skipped === 'no_llm_consent' && (
        <p className="alert info" role="status">
          Automatic reading is off for this account, so values need to be entered below. You can turn it on in
          Account.
        </p>
      )}

      {flagged.length > 0 && (
        <section className="card" aria-labelledby="flagged-title">
          <h2 id="flagged-title">Needs a closer look</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>As printed</th>
                  <th className="num">Value</th>
                  <th>Unit</th>
                  <th>Why it was held back</th>
                </tr>
              </thead>
              <tbody>
                {flagged.map((r, i) => (
                  <tr key={i}>
                    <td>{r.printed_name}</td>
                    <td className="num">{r.value}</td>
                    <td>{r.unit}</td>
                    <td>{r.issues.map(issueText).join('; ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {observations.length > 0 && (
        <section className="card" aria-labelledby="results-title">
          <h2 id="results-title">Stored results</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Test</th>
                  <th>LOINC</th>
                  <th className="num">Value</th>
                  <th>Unit</th>
                  <th>Verified</th>
                </tr>
              </thead>
              <tbody>
                {observations.map((o) => (
                  <tr key={o.id}>
                    <td>
                      <Link to={`/trends?marker=${o.marker_code}`}>{names.get(o.marker_code) ?? o.marker_code}</Link>
                    </td>
                    <td className="muted">{o.loinc}</td>
                    <td className="num">{o.canonical_value}</td>
                    <td>{o.canonical_unit}</td>
                    <td>{o.verified ? 'Yes' : <span className="muted">Not yet</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {REVIEWABLE.has(meta.status) && (
        <ReviewForm key={meta.id} data={report.data} markers={markers.data} />
      )}
      {!REVIEWABLE.has(meta.status) && meta.status !== 'rejected' && (
        <p className="muted" role="status">
          This report is still being processed. This page updates on its own.
        </p>
      )}
    </>
  )
}
