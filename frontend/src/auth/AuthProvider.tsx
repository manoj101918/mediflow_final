import type { Session } from '@supabase/supabase-js'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { AuthContext, type AuthContextValue, type AuthStatus } from '@/auth/context'
import { ApiError, api } from '@/lib/api'
import { supabase } from '@/lib/supabase'
import type { Me } from '@/types/api'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<Session | null>(null)
  const [sessionReady, setSessionReady] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    // Fires INITIAL_SESSION immediately, then on every sign-in, sign-out and token refresh.
    // Keep this callback synchronous: awaiting supabase calls inside it can deadlock.
    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      setSession(nextSession)
      setSessionReady(true)
      if (event === 'SIGNED_OUT') queryClient.clear()
    })
    return () => data.subscription.unsubscribe()
  }, [queryClient])

  const userId = session?.user.id
  const meQuery = useQuery({
    queryKey: ['me', userId],
    queryFn: async ({ signal }) => {
      try {
        return await api<Me>('/me', { signal })
      } catch (error) {
        // A valid login without an active staff profile cannot use the app: sign it out.
        if (error instanceof ApiError && error.status === 403) {
          setNotice(error.message)
          await supabase.auth.signOut({ scope: 'local' })
        }
        throw error
      }
    },
    enabled: Boolean(userId),
    staleTime: 5 * 60_000,
  })

  const signOut = useCallback(async () => {
    await supabase.auth.signOut({ scope: 'local' })
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    setNotice(null)
    const { error } = await supabase.auth.signInWithPassword({ email, password })
    if (error) throw error
  }, [])

  const { refetch } = meQuery
  const retry = useCallback(() => void refetch(), [refetch])

  const value = useMemo<AuthContextValue>(() => {
    let status: AuthStatus
    if (!sessionReady) status = 'loading'
    else if (!session) status = 'signed_out'
    else if (meQuery.data) status = 'signed_in'
    // 403 = no active staff profile: stay 'loading' while queryFn signs out.
    else if (meQuery.isError && !(meQuery.error instanceof ApiError && meQuery.error.status === 403))
      status = 'error'
    else status = 'loading'

    return {
      status,
      session,
      me: status === 'signed_in' ? (meQuery.data ?? null) : null,
      error: status === 'error' && meQuery.error instanceof ApiError ? meQuery.error : null,
      notice,
      signIn,
      signOut,
      retry,
    }
  }, [sessionReady, session, meQuery.data, meQuery.isError, meQuery.error, notice, signIn, signOut, retry])

  return <AuthContext value={value}>{children}</AuthContext>
}
