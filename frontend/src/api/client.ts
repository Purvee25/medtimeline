import type { z } from 'zod'
import { RefreshedTokens, Tokens } from './schemas'

const REFRESH_KEY = 'medtimeline.refresh'

/** An HTTP error with the server's message, safe to show to the user. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// The access token lives only in memory. The refresh token is kept in sessionStorage so a page
// reload stays signed in, but it is gone when the tab closes. See DECISIONS.md.
let accessToken: string | null = null
let onSignedOut: () => void = () => {}

function readRefresh(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

function writeRefresh(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(REFRESH_KEY, token)
    else sessionStorage.removeItem(REFRESH_KEY)
  } catch {
    // Storage blocked (private mode): the session simply won't survive a reload.
  }
}

export const session = {
  hasRefreshToken: () => readRefresh() !== null,
  setTokens(tokens: z.infer<typeof Tokens>) {
    accessToken = tokens.access
    writeRefresh(tokens.refresh)
  },
  clear() {
    accessToken = null
    writeRefresh(null)
  },
  /** Revoke the refresh token server-side (best effort), then forget both tokens. */
  async logout() {
    const refresh = readRefresh()
    session.clear()
    if (!refresh) return
    try {
      await fetch('/api/auth/logout/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      })
    } catch {
      // Offline: the token still expires on its own within a day.
    }
  },
  onSignedOut(callback: () => void) {
    onSignedOut = callback
  },
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object') {
      if ('detail' in body && typeof body.detail === 'string') return body.detail
      // DRF field errors: {"field": ["message", ...]}
      const parts = Object.entries(body).map(([field, value]) =>
        Array.isArray(value) ? `${field}: ${value.join(' ')}` : `${field}: ${String(value)}`,
      )
      if (parts.length) return parts.join('\n')
    }
  } catch {
    // Not JSON: fall through to the status text.
  }
  return response.statusText || `Request failed (${response.status})`
}

let refreshing: Promise<boolean> | null = null

/** Exchange the refresh token for a new access token; concurrent callers share one request. */
async function refreshAccess(): Promise<boolean> {
  const refresh = readRefresh()
  if (!refresh) return false
  refreshing ??= (async () => {
    try {
      const response = await fetch('/api/auth/token/refresh/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      })
      if (!response.ok) return false
      // The server rotates refresh tokens: the old one is now revoked, so store the new pair.
      session.setTokens(RefreshedTokens.parse(await response.json()))
      return true
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

type RequestOptions = { method?: string; body?: unknown; auth?: boolean }

async function send(path: string, { method = 'GET', body, auth = true }: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`
  return fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
}

/**
 * Call the API and validate the response with `schema`.
 *
 * On a 401 the access token is refreshed once and the request retried; if that fails the
 * session is cleared and the app returns to sign-in.
 */
export async function api<T extends z.ZodType>(
  path: string,
  schema: T,
  options: RequestOptions = {},
): Promise<z.infer<T>> {
  const response = await apiRaw(path, options)
  return schema.parse(await response.json())
}

/** Like `api`, for endpoints with no body to validate (e.g. 204 responses). */
export async function apiRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  const auth = options.auth ?? true
  if (auth && !accessToken) await refreshAccess()
  let response = await send(path, options)
  if (response.status === 401 && auth && (await refreshAccess())) {
    response = await send(path, options)
  }
  if (response.status === 401 && auth) {
    session.clear()
    onSignedOut()
  }
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  return response
}
