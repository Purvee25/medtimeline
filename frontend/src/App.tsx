import { NavLink, Navigate, Outlet, Route, Routes } from 'react-router'
import { useAuth } from './authContext'
import { Account } from './pages/Account'
import { ReportDetail } from './pages/ReportDetail'
import { Reports } from './pages/Reports'
import { SignIn } from './pages/SignIn'
import { Trends } from './pages/Trends'

function Shell() {
  const { state, signOut } = useAuth()
  if (state.status !== 'signed_in') return null
  return (
    <div className="shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          MedTimeline
        </NavLink>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            Reports
          </NavLink>
          <NavLink to="/trends">Trends</NavLink>
          <NavLink to="/account">Account</NavLink>
        </nav>
        <span className="who">
          {state.user.username}
          {state.user.role === 'center_staff' ? ' · center staff' : ''}
        </span>
        <button type="button" onClick={signOut}>
          Sign out
        </button>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  )
}

export function App() {
  const { state } = useAuth()

  if (state.status === 'loading') {
    return (
      <p className="auth muted" role="status">
        Loading…
      </p>
    )
  }
  if (state.status === 'offline') {
    return (
      <div className="auth">
        <div className="card" role="alert">
          <h1>Can't reach MedTimeline</h1>
          <p className="muted">Check your connection. You're still signed in.</p>
          <div>
            <button type="button" className="primary" onClick={() => window.location.reload()}>
              Try again
            </button>
          </div>
        </div>
      </div>
    )
  }
  if (state.status === 'signed_out') return <SignIn />

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Reports />} />
        <Route path="reports/:id" element={<ReportDetail />} />
        <Route path="trends" element={<Trends />} />
        <Route path="account" element={<Account />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
