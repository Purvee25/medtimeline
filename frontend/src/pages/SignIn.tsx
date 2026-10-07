import { type FormEvent, useState } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../authContext'

type Mode = 'sign_in' | 'register'

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Check your connection and try again.'
}

export function SignIn() {
  const { signIn, register } = useAuth()
  const [mode, setMode] = useState<Mode>('sign_in')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [registered, setRegistered] = useState(false)

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const email = String(form.get('email') ?? '').trim().toLowerCase()
    const password = String(form.get('password') ?? '')
    setError(null)
    setPending(true)
    try {
      if (mode === 'sign_in') {
        await signIn(email, password)
      } else {
        await register({
          username: email.split('@')[0]!.replace(/[^a-z0-9_]/gi, '_').slice(0, 150) + '_' + Math.random().toString(36).slice(2, 6),
          email,
          password,
          consent_store_reports: form.get('consent_store_reports') === 'on',
          consent_llm_extraction: form.get('consent_llm_extraction') === 'on',
        })
        setRegistered(true)
      }
    } catch (err) {
      setError(message(err))
    } finally {
      setPending(false)
    }
  }

  if (registered) {
    return (
      <div className="auth">
        <div className="card">
          <div className="stack">
            <h1>Check your email</h1>
            <p className="muted">
              We sent a verification link to your email address. Click it to confirm your account. You can still use
              MedTimeline in the meantime.
            </p>
            <button type="button" className="primary" onClick={() => setRegistered(false)}>
              Back to sign in
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="auth">
      <div className="card">
        <div className="stack">
          <h1>MedTimeline</h1>
          <p className="muted">Your lab results from every center, on one timeline.</p>
        </div>

        <div className="tabs" role="group" aria-label="Account">
          {(['sign_in', 'register'] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => {
                setMode(m)
                setError(null)
              }}
            >
              {m === 'sign_in' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>

        <form className="stack" onSubmit={onSubmit}>
          <label>
            Email
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete={mode === 'sign_in' ? 'current-password' : 'new-password'}
              minLength={mode === 'register' ? 10 : undefined}
              required
            />
          </label>

          {mode === 'register' && (
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="small muted" style={{ marginBottom: 8 }}>
                Consent: you can change either later in Account.
              </legend>
              <label className="check">
                <input type="checkbox" name="consent_store_reports" required />
                <span>Store my uploaded reports and the results extracted from them. (Required)</span>
              </label>
              <label className="check">
                <input type="checkbox" name="consent_llm_extraction" />
                <span>
                  Use an AI model to read my reports. Names and IDs are removed first. Without this, results are
                  entered by review.
                </span>
              </label>
            </fieldset>
          )}

          {error && (
            <p className="alert error" role="alert">
              {error}
            </p>
          )}
          <button className="primary" type="submit" disabled={pending}>
            {pending ? 'Please wait…' : mode === 'sign_in' ? 'Sign in' : 'Create account'}
          </button>
        </form>
        <p className="small muted">
          MedTimeline tracks and explains results. It does not diagnose or give treatment advice.
        </p>
      </div>
    </div>
  )
}
