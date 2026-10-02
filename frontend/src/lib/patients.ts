import { api } from '@/lib/api'
import type { Duplicate, Page, Patient, PatientDetail, PatientInput } from '@/types/api'

export const patientKeys = {
  all: ['patients'] as const,
  search: (q: string, page: number, pageSize: number) =>
    ['patients', 'search', q, page, pageSize] as const,
  detail: (id: string) => ['patients', 'detail', id] as const,
  duplicates: (phone: string, name: string, excludeId?: string) =>
    ['patients', 'duplicates', phone, name, excludeId ?? null] as const,
}

export const searchPatients = (q: string, page: number, pageSize: number, signal?: AbortSignal) =>
  api<Page<Patient>>('/patients', { query: { q: q || undefined, page, page_size: pageSize }, signal })

export const fetchPatient = (id: string, signal?: AbortSignal) =>
  api<PatientDetail>(`/patients/${id}`, { signal })

export const createPatient = (body: PatientInput) =>
  api<Patient>('/patients', { method: 'POST', body })

export const updatePatient = (id: string, body: Partial<PatientInput>) =>
  api<Patient>(`/patients/${id}`, { method: 'PATCH', body })

export const findDuplicates = (
  phone: string,
  fullName: string,
  excludeId?: string,
  signal?: AbortSignal,
) =>
  api<Duplicate[]>('/patients/duplicates', {
    query: { phone: phone || undefined, full_name: fullName || undefined, exclude_id: excludeId },
    signal,
  })

export const DUPLICATE_LABEL: Record<Duplicate['reason'], string> = {
  same_phone_similar_name: 'Same phone, similar name',
  same_phone: 'Same phone number',
  similar_name: 'Similar name',
}
