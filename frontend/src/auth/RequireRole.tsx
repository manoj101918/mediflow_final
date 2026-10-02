import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import { useAuth } from '@/auth/context'
import { ROLE_HOME } from '@/auth/roles'
import { AuthErrorScreen, FullPageLoader } from '@/components/layout/StatusScreens'
import type { UserRole } from '@/types/api'

interface RequireRoleProps {
  roles: readonly UserRole[]
  children: ReactNode
}

/** Renders children only for signed-in staff with one of `roles`; others go to their own home. */
export function RequireRole({ roles, children }: RequireRoleProps) {
  const { status, me } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <FullPageLoader />
  if (status === 'error') return <AuthErrorScreen />
  if (status === 'signed_out' || !me) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  if (!roles.includes(me.role)) return <Navigate to={ROLE_HOME[me.role]} replace />
  return children
}

/** `/` sends signed-in staff to their dashboard and everyone else to the login page. */
export function RootRedirect() {
  const { status, me } = useAuth()
  if (status === 'loading') return <FullPageLoader />
  if (status === 'error') return <AuthErrorScreen />
  return <Navigate to={me ? ROLE_HOME[me.role] : '/login'} replace />
}
