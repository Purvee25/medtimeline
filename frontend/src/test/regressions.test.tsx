/** Regression tests for bugs found in the multi-agent frontend review. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { session } from '../api/client'
import { useReports } from '../api/queries'
import { AuthProvider } from '../auth'
import { useAuth } from '../authContext'
import { ReportDetail } from '../pages/ReportDetail'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function wrapper(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

const baseReport = {
  id: 'r1',
  patient: 'alice',
  center: null,
  original_filename: 'cbc.pdf',
  size_bytes: 10,
  collected_on: '2026-01-02',
  error: '',
  created_at: '2026-01-02T10:00:00Z',
}
const markers = [{ code: 'hb', name: 'Hemoglobin', loinc: '718-7', unit: 'g/dL', units: ['g/dL'] }]
const observation = {
  id: 1,
  marker_code: 'hb',
  loinc: '718-7',
  value: '13.0000',
  unit: 'g/dL',
  canonical_value: '13.0000',
  canonical_unit: 'g/dL',
  effective_date: '2026-01-02',
  verified: true,
}

afterEach(() => vi.useRealTimers())

describe('review', () => {
  it('keeps the success message after the report refetches as extracted', async () => {
    session.setTokens({ access: 'a', refresh: 'r' })
    let reviewed = false
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url === '/api/markers/') return json(markers)
        if (url === '/api/reports/r1/review/') {
          reviewed = true
          return json([observation])
        }
        if (url === '/api/reports/r1/observations/') {
          return json({
            report: { ...baseReport, status: reviewed ? 'extracted' : 'needs_review' },
            extraction: null,
            observations: reviewed ? [observation] : [{ ...observation, verified: false }],
          })
        }
        return json({ count: 0, next: null, previous: null, results: [] })
      }),
    )
    const Wrapper = wrapper('/reports/r1')
    render(
      <Wrapper>
        <Routes>
          <Route path="/reports/:id" element={<ReportDetail />} />
        </Routes>
      </Wrapper>,
    )

    await userEvent.click(await screen.findByRole('button', { name: 'Save verified values' }))
    await waitFor(() => expect(screen.getByText('Extracted')).toBeInTheDocument())
    expect(screen.getByRole('status', { name: '' })).toHaveTextContent('Saved 1 verified values.')
  })
})

describe('useReports polling', () => {
  it('does not poll forever for an upload the browser never finished', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    session.setTokens({ access: 'a', refresh: 'r' })
    const fetchMock = vi.fn(async () =>
      json({ count: 1, next: null, previous: null, results: [{ ...baseReport, status: 'awaiting_upload' }] }),
    )
    vi.stubGlobal('fetch', fetchMock)
    function Probe() {
      useReports()
      return null
    }
    const Wrapper = wrapper()
    render(
      <Wrapper>
        <Probe />
      </Wrapper>,
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    await act(() => vi.advanceTimersByTimeAsync(10_000))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('session resume', () => {
  function Status() {
    return <p>{useAuth().state.status}</p>
  }

  it('keeps the session when the server is unreachable', async () => {
    session.setTokens({ access: 'a', refresh: 'r' })
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'down' }, 503)))
    const Wrapper = wrapper()
    render(
      <Wrapper>
        <AuthProvider>
          <Status />
        </AuthProvider>
      </Wrapper>,
    )
    expect(await screen.findByText('offline')).toBeInTheDocument()
    expect(session.hasRefreshToken()).toBe(true)
  })

  it('signs out when the server rejects the session', async () => {
    session.setTokens({ access: 'a', refresh: 'r' })
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'expired' }, 401)))
    const Wrapper = wrapper()
    render(
      <Wrapper>
        <AuthProvider>
          <Status />
        </AuthProvider>
      </Wrapper>,
    )
    expect(await screen.findByText('signed_out')).toBeInTheDocument()
    expect(session.hasRefreshToken()).toBe(false)
  })
})
