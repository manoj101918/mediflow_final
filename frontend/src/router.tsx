import { Navigate, createBrowserRouter } from 'react-router'

import { RequireRole, RootRedirect } from '@/auth/RequireRole'
import { AppShell } from '@/components/layout/AppShell'
import { ComingSoon } from '@/components/layout/ComingSoon'
import { ReceptionLayout } from '@/components/layout/ReceptionLayout'
import { LoginPage } from '@/pages/Login'
import { TodayPage } from '@/pages/reception/Today'

export const router = createBrowserRouter([
  { path: '/', element: <RootRedirect /> },
  { path: '/login', element: <LoginPage /> },
  {
    path: '/reception',
    element: (
      <RequireRole roles={['receptionist']}>
        <ReceptionLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: <TodayPage /> },
      { path: 'appointments', element: <ComingSoon title="Appointments" milestone="Milestone 6" /> },
      { path: 'patients', element: <ComingSoon title="Patients" milestone="Milestone 6" /> },
      { path: 'doctors', element: <ComingSoon title="Doctors" milestone="Milestone 6" /> },
    ],
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
