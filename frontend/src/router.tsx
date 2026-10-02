import type { ComponentType } from 'react'
import { Navigate, Outlet, type RouteObject, createBrowserRouter } from 'react-router'

import { RequireRole, RootRedirect } from '@/auth/RequireRole'
import { RouteError } from '@/components/layout/RouteError'
import { FullPageLoader } from '@/components/layout/StatusScreens'
import { LoginPage } from '@/pages/Login'
import type { UserRole } from '@/types/api'

// Code-split: the login screen loads alone; each role downloads only its own layout and the
// pages it opens.
function lazyComponent(load: () => Promise<ComponentType>): RouteObject['lazy'] {
  return async () => ({ Component: await load() })
}

/** A role's area: guard -> lazily loaded layout -> lazily loaded pages. */
function area(
  path: string,
  role: UserRole,
  layout: () => Promise<ComponentType>,
  pages: RouteObject[],
): RouteObject {
  return {
    path,
    element: (
      <RequireRole roles={[role]}>
        <Outlet />
      </RequireRole>
    ),
    children: [{ lazy: lazyComponent(layout), children: pages }],
  }
}

export const router = createBrowserRouter([
  {
    errorElement: <RouteError />,
    hydrateFallbackElement: <FullPageLoader />,
    children: [
      { path: '/', element: <RootRedirect /> },
      { path: '/login', element: <LoginPage /> },
      area(
        '/reception',
        'receptionist',
        () => import('@/components/layout/ReceptionLayout').then((m) => m.ReceptionLayout),
        [
          { index: true, lazy: lazyComponent(() => import('@/pages/reception/Today').then((m) => m.TodayPage)) },
          {
            path: 'appointments',
            lazy: lazyComponent(() => import('@/pages/reception/Appointments').then((m) => m.AppointmentsPage)),
          },
          {
            path: 'patients',
            lazy: lazyComponent(() => import('@/pages/reception/Patients').then((m) => m.PatientsPage)),
          },
          {
            path: 'patients/:patientId',
            lazy: lazyComponent(() => import('@/pages/reception/PatientDetail').then((m) => m.PatientDetailPage)),
          },
          {
            path: 'doctors',
            lazy: lazyComponent(() => import('@/pages/reception/Doctors').then((m) => m.DoctorsPage)),
          },
        ],
      ),
      area(
        '/doctor',
        'doctor',
        () => import('@/components/layout/AppShell').then((m) => m.AppShell),
        [
          { index: true, lazy: lazyComponent(() => import('@/pages/doctor/DoctorToday').then((m) => m.DoctorTodayPage)) },
          {
            path: 'patients/:patientId',
            lazy: lazyComponent(() => import('@/pages/doctor/PatientChart').then((m) => m.PatientChartPage)),
          },
        ],
      ),
      area(
        '/admin',
        'admin',
        () => import('@/components/layout/AdminLayout').then((m) => m.AdminLayout),
        [
          { index: true, lazy: lazyComponent(() => import('@/pages/admin/Users').then((m) => m.UsersPage)) },
          {
            path: 'doctors',
            lazy: lazyComponent(() => import('@/pages/admin/Doctors').then((m) => m.AdminDoctorsPage)),
          },
          {
            path: 'doctors/:doctorId',
            lazy: lazyComponent(() => import('@/pages/admin/DoctorManage').then((m) => m.DoctorManagePage)),
          },
        ],
      ),
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
