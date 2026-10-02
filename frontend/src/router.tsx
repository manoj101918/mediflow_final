import { Navigate, createBrowserRouter } from 'react-router'

import { RequireRole, RootRedirect } from '@/auth/RequireRole'
import { AppShell } from '@/components/layout/AppShell'
import { ComingSoon } from '@/components/layout/ComingSoon'
import { ReceptionLayout } from '@/components/layout/ReceptionLayout'
import { LoginPage } from '@/pages/Login'
import { AppointmentsPage } from '@/pages/reception/Appointments'
import { DoctorsPage } from '@/pages/reception/Doctors'
import { PatientDetailPage } from '@/pages/reception/PatientDetail'
import { PatientsPage } from '@/pages/reception/Patients'
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
      { path: 'appointments', element: <AppointmentsPage /> },
      { path: 'patients', element: <PatientsPage /> },
      { path: 'patients/:patientId', element: <PatientDetailPage /> },
      { path: 'doctors', element: <DoctorsPage /> },
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
