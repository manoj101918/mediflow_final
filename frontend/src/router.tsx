import { Navigate, createBrowserRouter } from 'react-router'

import { RequireRole, RootRedirect } from '@/auth/RequireRole'
import { AppShell } from '@/components/layout/AppShell'
import { ComingSoon } from '@/components/layout/ComingSoon'
import { LoginPage } from '@/pages/Login'

export const router = createBrowserRouter([
  { path: '/', element: <RootRedirect /> },
  { path: '/login', element: <LoginPage /> },
  {
    path: '/reception',
    element: (
      <RequireRole roles={['receptionist']}>
        <AppShell />
      </RequireRole>
    ),
    children: [{ index: true, element: <ComingSoon title="Today" milestone="Milestone 5" /> }],
  },
  {
    path: '/doctor',
    element: (
      <RequireRole roles={['doctor']}>
        <AppShell />
      </RequireRole>
    ),
    children: [
      { index: true, element: <ComingSoon title="My appointments today" milestone="Milestone 7" /> },
    ],
  },
  {
    path: '/admin',
    element: (
      <RequireRole roles={['admin']}>
        <AppShell />
      </RequireRole>
    ),
    children: [{ index: true, element: <ComingSoon title="Staff & doctors" milestone="Milestone 7" /> }],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
