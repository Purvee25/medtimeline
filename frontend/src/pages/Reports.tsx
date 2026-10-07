import { type ChangeEvent, type DragEvent, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useReports, useUpload } from '../api/queries'
import { useUser } from '../authContext'
import { StatusBadge } from '../components/StatusBadge'
import { formatDate, formatDateTime, errorText } from '../format'

function UploadCard() {
  const user = useUser()
  const upload = useUpload()
  const input = useRef<HTMLInputElement>(null)
  const [patient, setPatient] = useState('')
  const [dragging, setDragging] = useState(false)
  const needsPatient = user.role === 'center_staff'
  const blocked = needsPatient && !patient.trim()

  function send(file: File | undefined) {
    if (!file || blocked) return
    upload.mutate({ file, patient: needsPatient ? patient.trim() : undefined })
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    send(event.dataTransfer.files[0])
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    send(event.target.files?.[0])
    event.target.value = ''
  }

  return (
    <section className="card" aria-labelledby="upload-title">
      <h2 id="upload-title">Upload a report</h2>
      {needsPatient && (
        <label style={{ maxWidth: 320 }}>
          Patient username
          <input
            value={patient}
            onChange={(e) => setPatient(e.target.value)}
            placeholder="e.g. asha"
            aria-describedby="patient-hint"
          />
          <span id="patient-hint" className="small muted" style={{ fontWeight: 400 }}>
            Required: the patient must have consented to report storage.
          </span>
        </label>
      )}
      <div
        className="dropzone"
        data-active={dragging}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <p>Drop a PDF lab report here</p>
        <p className="small muted">PDF only, up to 10 MB. Scanned reports are fine.</p>
        <input ref={input} type="file" accept="application/pdf,.pdf" hidden onChange={onPick} />
        <button
          type="button"
          className="primary"
          disabled={upload.isPending || blocked}
          aria-describedby={needsPatient ? 'patient-hint' : undefined}
          onClick={() => input.current?.click()}
        >
          {upload.isPending ? 'Uploading…' : 'Choose file'}
        </button>
      </div>
      {upload.isError && (
        <p className="alert error" role="alert">
          {errorText(upload.error)}
        </p>
      )}
      {upload.isSuccess && (
        <p className="small muted" role="status">
          Uploaded {upload.data.original_filename}. Results appear below once processing finishes.
        </p>
      )}
    </section>
  )
}

export function Reports() {
  const user = useUser()
  const reports = useReports()

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p>{user.role === 'center_staff' ? "Reports uploaded at your center." : 'Every report you have uploaded.'}</p>
        </div>
      </div>

      <UploadCard />

      <section className="card" aria-labelledby="list-title">
        <h2 id="list-title">All reports</h2>
        {reports.isPending && <p className="muted">Loading reports…</p>}
        {reports.isError && (
          <p className="alert error" role="alert">
            {errorText(reports.error)}
          </p>
        )}
        {reports.data?.results.length === 0 && <p className="muted">No reports yet. Upload your first one above.</p>}
        {!!reports.data?.results.length && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Report</th>
                  {user.role === 'center_staff' && <th>Patient</th>}
                  <th>Collected</th>
                  <th>Center</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {reports.data.results.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/reports/${r.id}`}>{r.original_filename}</Link>
                    </td>
                    {user.role === 'center_staff' && <td>{r.patient}</td>}
                    <td>{r.collected_on ? formatDate(r.collected_on) : <span className="muted">—</span>}</td>
                    <td>{r.center ?? <span className="muted">Self-uploaded</span>}</td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="muted">{formatDateTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
