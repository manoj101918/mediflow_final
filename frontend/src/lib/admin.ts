import { api } from '@/lib/api'
import type {
  ClinicSettings,
  Doctor,
  DoctorInput,
  LabTest,
  LabTestInput,
  LeaveCreated,
  ShiftInput,
  StaffUser,
  StaffUserCreate,
} from '@/types/api'

export const adminKeys = {
  users: ['admin', 'users'] as const,
  // Under 'doctors' so any doctor change also refreshes the reception doctor list.
  doctors: ['doctors', 'admin', 'all'] as const,
}

export const fetchUsers = (signal?: AbortSignal) => api<StaffUser[]>('/admin/users', { signal })

export const createUser = (body: StaffUserCreate) =>
  api<StaffUser>('/admin/users', { method: 'POST', body })

export const updateUser = (
  id: string,
  body: Partial<Pick<StaffUser, 'full_name' | 'phone' | 'is_active'>>,
) => api<StaffUser>(`/admin/users/${id}`, { method: 'PATCH', body })

export const fetchAllDoctors = (signal?: AbortSignal) =>
  api<Doctor[]>('/doctors', { query: { include_inactive: true }, signal })

export const createDoctor = (body: DoctorInput) =>
  api<Doctor>('/admin/doctors', { method: 'POST', body })

export const updateDoctor = (id: string, body: Partial<DoctorInput & { is_active: boolean }>) =>
  api<Doctor>(`/admin/doctors/${id}`, { method: 'PATCH', body })

export const replaceSchedules = (id: string, schedules: ShiftInput[]) =>
  api<Doctor>(`/admin/doctors/${id}/schedules`, { method: 'PUT', body: { schedules } })

export const addLeave = (doctorId: string, leaveDate: string, reason: string | null) =>
  api<LeaveCreated>(`/admin/doctors/${doctorId}/leaves`, {
    method: 'POST',
    body: { leave_date: leaveDate, reason },
  })

export const deleteLeave = (leaveId: string) =>
  api<void>(`/admin/leaves/${leaveId}`, { method: 'DELETE' })

// Lab catalog and clinic settings. Under 'labs' so the doctor/lab catalog refreshes too.
export const labAdminKeys = {
  tests: ['labs', 'admin', 'tests'] as const,
  settings: ['labs', 'admin', 'settings'] as const,
}

export const fetchLabTests = (signal?: AbortSignal) => api<LabTest[]>('/admin/lab-tests', { signal })

export const createLabTest = (body: LabTestInput) =>
  api<LabTest>('/admin/lab-tests', { method: 'POST', body })

export const updateLabTest = (id: string, body: LabTestInput) =>
  api<LabTest>(`/admin/lab-tests/${id}`, { method: 'PUT', body })

export const setLabTestActive = (id: string, isActive: boolean) =>
  api<LabTest>(`/admin/lab-tests/${id}`, { method: 'PATCH', body: { is_active: isActive } })

export const fetchClinicSettings = (signal?: AbortSignal) =>
  api<ClinicSettings>('/admin/clinic-settings', { signal })

export const updateClinicSettings = (body: ClinicSettings) =>
  api<ClinicSettings>('/admin/clinic-settings', { method: 'PUT', body })
