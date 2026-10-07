import { useState } from 'react'
import type { ConsentPurpose } from '../api/schemas'
import { downloadFhirBundle, eraseAccount, useConsents, useSetConsent } from '../api/queries'
import { useAuth, useUser } from '../authContext'
import { errorText } from '../format'

const PURPOSES: { purpose: ConsentPurpose; title: string; detail: string }[] = [
  {
    purpose: 'store_reports',
    title: 'Store my reports',
    detail: 'Needed to upload reports. Withdrawing stops new uploads; delete your account to remove existing data.',
  },
  {
    purpose: 'llm_extraction',
    title: 'Read reports with an AI model',
    detail: 'Names and IDs are removed before any text is sent. When off, values are entered by review.',
  },
]

function Consents() {
  const consents = useConsents()
  const setConsent = useSetConsent()

  if (consents.isPending) return <p className="muted">Loading…</p>
  if (consents.isError) return <p className="alert error">{errorText(consents.error)}</p>

  const active = new Set(consents.data.filter((c) => !c.withdrawn_at).map((c) => c.purpose))
  return (
    <div className="stack">
      {PURPOSES.map(({ purpose, title, detail }) => (
        <label key={purpose} className="check">
          <input
            type="checkbox"
            checked={active.has(purpose)}
            disabled={setConsent.isPending}
            onChange={(e) => setConsent.mutate({ purpose, granted: e.target.checked })}
          />
          <span>
            <strong>{title}</strong>
            <br />
            <span className="small muted">{detail}</span>
          </span>
        </label>
      ))}
      {setConsent.isError && <p className="alert error">{errorText(setConsent.error)}</p>}
    </div>
  )
}

function DangerZone() {
  const user = useUser()
  const { signOut } = useAuth()
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function erase() {
    setPending(true)
    setError(null)
    try {
      await eraseAccount()
      signOut()
    } catch (err) {
      setError(errorText(err))
      setPending(false)
    }
  }

  return (
    <section className="card" aria-labelledby="delete-title">
      <h2 id="delete-title">Delete account</h2>
      <p className="small muted">
        Permanently deletes your account, every report file and every result. This cannot be undone. Export your data
        first if you want a copy.
      </p>
      <label style={{ maxWidth: 320 }}>
        Type your username ({user.username}) to confirm
        <input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
      </label>
      <div>
        <button type="button" className="danger" disabled={confirm !== user.username || pending} onClick={erase}>
          {pending ? 'Deleting…' : 'Delete my account'}
        </button>
      </div>
      {error && (
        <p className="alert error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

export function Account() {
  const user = useUser()
  const [exportError, setExportError] = useState<string | null>(null)

  if (user.role !== 'patient') {
    return (
      <>
        <h1>Account</h1>
        <p className="muted">Staff accounts are managed by your center's administrator.</p>
      </>
    )
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Account</h1>
          <p>Signed in as {user.username}.</p>
        </div>
      </div>

      <section className="card" aria-labelledby="consent-title">
        <h2 id="consent-title">Consent</h2>
        <Consents />
      </section>

      <section className="card" aria-labelledby="export-title">
        <h2 id="export-title">Export your data</h2>
        <p className="small muted">
          Download everything stored about you as a FHIR R4 bundle, the standard format other health systems can import.
        </p>
        <div>
          <button type="button" onClick={() => downloadFhirBundle().catch((e: unknown) => setExportError(errorText(e)))}>
            Download FHIR bundle
          </button>
        </div>
        {exportError && <p className="alert error">{exportError}</p>}
      </section>

      <DangerZone />
    </>
  )
}
