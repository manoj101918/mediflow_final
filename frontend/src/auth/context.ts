import type { Session } from '@supabase/supabase-js'
import { createContext, useContext } from 'react'

import type { ApiError } from '@/lib/api'
import type { Me } from '@/types/api'

export type AuthStatus = 'loading' | 'signed_out' | 'signed_in' | 'error'

export interface AuthContextValue {
  status: AuthStatus
  session: Session | null
  /** Staff profile from GET /api/me; set whenever status is 'signed_in'. */
  me: Me | null
  /** Set when the session exists but /api/me failed for a non-auth reason (e.g. network). */
  error: ApiError | null
  /** Why the user was signed out automatically (inactive account, no profile). */
  notice: string | null
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  retry: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
