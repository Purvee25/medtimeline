import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import { api, ApiError, session } from './client'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('api', () => {
  it('refreshes an expired access token once and retries', async () => {
    session.setTokens({ access: 'old', refresh: 'r' })
    const auth: (string | undefined)[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/auth/token/refresh/') return json({ access: 'new', refresh: 'r2' })
        const header = (init?.headers as Record<string, string> | undefined)?.Authorization
        auth.push(header)
        return header === 'Bearer new' ? json({ ok: true }) : json({ detail: 'expired' }, 401)
      }),
    )

    await expect(api('/api/thing/', z.object({ ok: z.boolean() }))).resolves.toEqual({ ok: true })
    expect(auth).toEqual(['Bearer old', 'Bearer new'])
    expect(sessionStorage.getItem('medtimeline.refresh')).toBe('r2')
  })

  it('signs out when the refresh token is also rejected', async () => {
    session.setTokens({ access: 'old', refresh: 'r' })
    const signedOut = vi.fn()
    session.onSignedOut(signedOut)
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'nope' }, 401)))

    await expect(api('/api/thing/', z.object({}))).rejects.toBeInstanceOf(ApiError)
    expect(signedOut).toHaveBeenCalledOnce()
    expect(session.hasRefreshToken()).toBe(false)
  })

  it('turns DRF field errors into a readable message', async () => {
    session.setTokens({ access: 'a', refresh: 'r' })
    vi.stubGlobal('fetch', vi.fn(async () => json({ password: ['This password is too common.'] }, 400)))
    await expect(api('/api/x/', z.object({}))).rejects.toThrow('password: This password is too common.')
  })

  it('rejects responses that do not match the schema', async () => {
    session.setTokens({ access: 'a', refresh: 'r' })
    vi.stubGlobal('fetch', vi.fn(async () => json({ count: 'many' })))
    await expect(api('/api/x/', z.object({ count: z.number() }))).rejects.toBeInstanceOf(z.ZodError)
  })
})

describe('session.logout', () => {
  it('revokes the refresh token on the server and forgets it locally', async () => {
    session.setTokens({ access: 'a', refresh: 'r' })
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await session.logout()
    expect(fetchMock).toHaveBeenCalledWith('/api/auth/logout/', expect.objectContaining({ body: '{"refresh":"r"}' }))
    expect(session.hasRefreshToken()).toBe(false)
  })
})

describe('single-flight refresh', () => {
  it('shares one refresh between concurrent 401s', async () => {
    session.setTokens({ access: 'old', refresh: 'r' })
    let refreshes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/auth/token/refresh/') {
          refreshes += 1
          return json({ access: 'new', refresh: 'r2' })
        }
        const header = (init?.headers as Record<string, string> | undefined)?.Authorization
        return header === 'Bearer new' ? json({}) : json({}, 401)
      }),
    )
    await Promise.all([api('/a/', z.object({})), api('/b/', z.object({})), api('/c/', z.object({}))])
    expect(refreshes).toBe(1)
  })
})
