import { createContext, useContext } from 'react'
import type { Me } from './api/schemas'

export type AuthState =
  | { status: 'loading' }
  | { status: 'signed_out' }
  | { status: 'signed_in'; user: Me }

export type Registration = {
  username: string
  email: string
  password: string
  consent_store_reports: boolean
  consent_llm_extraction: boolean
}

export type AuthContextValue = {
  state: AuthState
  signIn: (username: string, password: string) => Promise<void>
  register: (form: Registration) => Promise<void>
  signOut: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}

/** The signed-in user; only call below a route that requires sign-in. */
export function useUser(): Me {
  const { state } = useAuth()
  if (state.status !== 'signed_in') throw new Error('useUser called while signed out')
  return state.user
}
