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
  roles: readonly UserRole[],
  layout: () => Promise<ComponentType>,
  pages: RouteObject[],
): RouteObject {
  return {
    path,
    element: (
      <RequireRole roles={roles}>
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
        ['receptionist'],
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
          {
            path: 'inbox',
            lazy: lazyComponent(() => import('@/pages/reception/Inbox').then((m) => m.InboxPage)),
          },
        ],
      ),
      area(
        '/doctor',
        ['doctor'],
        () => import('@/components/layout/DoctorLayout').then((m) => m.DoctorLayout),
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
        ['admin'],
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
          {
            path: 'lab-tests',
            lazy: lazyComponent(() => import('@/pages/admin/LabCatalog').then((m) => m.LabCatalogPage)),
          },
          {
            path: 'lab-tests/:testId',
            lazy: lazyComponent(() => import('@/pages/admin/LabTestManage').then((m) => m.LabTestManagePage)),
          },
          {
            path: 'whatsapp',
            lazy: lazyComponent(() => import('@/pages/admin/WhatsApp').then((m) => m.WhatsAppPage)),
          },
          {
            path: 'voice-simulator',
            lazy: lazyComponent(() => import('@/pages/admin/VoiceSimulator').then((m) => m.VoiceSimulatorPage)),
          },
        ],
      ),
      area(
        '/lab',
        ['lab_technician', 'lab_supervisor'],
        () => import('@/components/layout/LabLayout').then((m) => m.LabLayout),
        [
          { index: true, lazy: lazyComponent(() => import('@/pages/lab/LabWorklist').then((m) => m.LabWorklistPage)) },
          {
            path: 'orders/:orderId',
            lazy: lazyComponent(() => import('@/pages/lab/LabOrder').then((m) => m.LabOrderPage)),
          },
        ],
      ),
      // Tube labels print without the app chrome.
      {
        path: '/lab/orders/:orderId/labels',
        element: (
          <RequireRole roles={['lab_technician', 'lab_supervisor']}>
            <Outlet />
          </RequireRole>
        ),
        children: [{ index: true, lazy: lazyComponent(() => import('@/pages/lab/LabLabels').then((m) => m.LabLabelsPage)) }],
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
])
