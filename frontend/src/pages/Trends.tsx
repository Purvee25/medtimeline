import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useMarkers, useTrend } from '../api/queries'
import { useUser } from '../authContext'
import { TrendChart } from '../components/TrendChart'
import { errorText, formatDate } from '../format'

export function Trends() {
  const user = useUser()
  const markers = useMarkers()
  const [params, setParams] = useSearchParams()
  const [showTable, setShowTable] = useState(false)
  const isStaff = user.role === 'center_staff'

  const marker = params.get('marker') ?? markers.data?.[0]?.code ?? ''
  const patient = params.get('patient') ?? ''
  const verifiedOnly = params.get('verified') === '1'
  const trend = useTrend(marker, patient, verifiedOnly, Boolean(marker) && (!isStaff || Boolean(patient)))

  function set(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Trends</h1>
          <p>One test over time, across every center, converted to the same unit.</p>
        </div>
      </div>

      <section className="card">
        <div className="row" style={{ alignItems: 'end' }}>
          <label>
            Test
            <select value={marker} onChange={(e) => set('marker', e.target.value)} disabled={!markers.data}>
              {markers.data?.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          {isStaff && (
            <form
              className="row"
              style={{ alignItems: 'end' }}
              onSubmit={(e) => {
                e.preventDefault()
                set('patient', String(new FormData(e.currentTarget).get('patient') ?? '').trim())
              }}
            >
              <label>
                Patient username
                <input key={patient} name="patient" defaultValue={patient} autoComplete="off" />
              </label>
              <button type="submit">Show</button>
            </form>
          )}
          <label className="check" style={{ paddingBottom: 9 }}>
            <input
              type="checkbox"
              checked={verifiedOnly}
              onChange={(e) => set('verified', e.target.checked ? '1' : '')}
            />
            <span>Verified results only</span>
          </label>
        </div>

        {isStaff && !patient && <p className="muted">Enter a patient username to see their trend.</p>}
        {trend.isLoading && <p className="muted">Loading trend…</p>}
        {trend.isError && (
          <p className="alert error" role="alert">
            {errorText(trend.error)}
          </p>
        )}
        {trend.data && trend.data.points.length === 0 && (
          <p className="muted">No results for {trend.data.name} yet.</p>
        )}
        {trend.data && trend.data.points.length > 0 && (
          <>
            <div className="stack">
              <h2>
                {trend.data.name} <span className="muted small">({trend.data.unit})</span>
              </h2>
              <p className="small muted">LOINC {trend.data.loinc}</p>
            </div>
            <TrendChart trend={trend.data} />
            <button type="button" className="link" onClick={() => setShowTable((v) => !v)} aria-expanded={showTable}>
              {showTable ? 'Hide' : 'Show'} data table
            </button>
            {showTable && (
              <div className="table-wrap">
                <table>
                  <caption className="visually-hidden">{trend.data.name} results</caption>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th className="num">Value ({trend.data.unit})</th>
                      <th>Center</th>
                      <th>Verified</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trend.data.points.map((p) => (
                      <tr key={`${p.report_id}-${p.date}`}>
                        <td>{formatDate(p.date)}</td>
                        <td className="num">{p.value}</td>
                        <td>{p.center ?? 'Self-uploaded'}</td>
                        <td>{p.verified ? 'Yes' : 'Not yet'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        <p className="small muted">
          The shaded band is a general adult range, not the range printed by each lab. Talk to your doctor about what
          your results mean.
        </p>
      </section>
    </>
  )
}
