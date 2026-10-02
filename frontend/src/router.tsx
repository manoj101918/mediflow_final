import { Navigate, createBrowserRouter } from 'react-router'

import { RequireRole, RootRedirect } from '@/auth/RequireRole'
import { AppShell } from '@/components/layout/AppShell'
import { AdminLayout } from '@/components/layout/AdminLayout'
import { ReceptionLayout } from '@/components/layout/ReceptionLayout'
import { LoginPage } from '@/pages/Login'
import { DoctorManagePage } from '@/pages/admin/DoctorManage'
import { AdminDoctorsPage } from '@/pages/admin/Doctors'
import { UsersPage } from '@/pages/admin/Users'
import { DoctorTodayPage } from '@/pages/doctor/DoctorToday'
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
      { index: true, element: <DoctorTodayPage /> },
    ],
  },
  {
    path: '/admin',
    element: (
      <RequireRole roles={['admin']}>
        <AdminLayout />
      </RequireRole>
    ),
    children: [
      { index: true, element: <UsersPage /> },
      { path: 'doctors', element: <AdminDoctorsPage /> },
      { path: 'doctors/:doctorId', element: <DoctorManagePage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
