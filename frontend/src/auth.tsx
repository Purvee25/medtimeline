import { useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError, session } from './api/client'
import { Me, Registration, Tokens } from './api/schemas'
import { AuthContext, type AuthState } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<AuthState>(() =>
    session.hasRefreshToken() ? { status: 'loading' } : { status: 'signed_out' },
  )

  const signOut = useCallback(() => {
    void session.logout()
    queryClient.clear()
    setState({ status: 'signed_out' })
  }, [queryClient])

  useEffect(() => {
    session.onSignedOut(signOut)
  }, [signOut])

  // Resume a session after reload: the refresh token is exchanged on the first call.
  useEffect(() => {
    if (state.status !== 'loading') return
    api('/api/auth/me/', Me)
      .then((user) => setState({ status: 'signed_in', user }))
      .catch((error: unknown) => {
        // Only a rejected session ends it; a network blip or 5xx keeps the refresh token for a retry.
        if (error instanceof ApiError && error.status === 401) signOut()
        else setState({ status: 'offline' })
      })
  }, [state.status, signOut])

  // Login accepts email (backend resolves email → username).
  const signIn = useCallback(async (email: string, password: string) => {
    const tokens = await api('/api/auth/token/', Tokens, { method: 'POST', body: { email, password }, auth: false })
    session.setTokens(tokens)
    setState({ status: 'signed_in', user: await api('/api/auth/me/', Me) })
  }, [])

  const register = useCallback(
    async (form: Registration) => {
      await api('/api/auth/register/', Me.pick({ id: true, username: true, email: true }), {
        method: 'POST',
        body: form,
        auth: false,
      })
      // After registration, sign in immediately (email verification is advisory, not blocking sign-in).
      await signIn(form.email, form.password)
    },
    [signIn],
  )

  const value = useMemo(() => ({ state, signIn, register, signOut }), [state, signIn, register, signOut])
  return <AuthContext value={value}>{children}</AuthContext>
}
