import { useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { api, session } from './api/client'
import { Me, Tokens } from './api/schemas'
import { AuthContext, type AuthState, type Registration } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<AuthState>(() =>
    session.hasRefreshToken() ? { status: 'loading' } : { status: 'signed_out' },
  )

  const signOut = useCallback(() => {
    session.clear()
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
      .catch(() => signOut())
  }, [state.status, signOut])

  const signIn = useCallback(async (username: string, password: string) => {
    const tokens = await api('/api/auth/token/', Tokens, { method: 'POST', body: { username, password }, auth: false })
    session.setTokens(tokens)
    setState({ status: 'signed_in', user: await api('/api/auth/me/', Me) })
  }, [])

  const register = useCallback(
    async (form: Registration) => {
      await api('/api/auth/register/', Me.pick({ id: true, username: true }), {
        method: 'POST',
        body: form,
        auth: false,
      })
      await signIn(form.username, form.password)
    },
    [signIn],
  )

  const value = useMemo(() => ({ state, signIn, register, signOut }), [state, signIn, register, signOut])
  return <AuthContext value={value}>{children}</AuthContext>
}
