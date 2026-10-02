import { api } from '@/lib/api'
import type {
  Addendum,
  Chart,
  CompleteResult,
  ConsultationInput,
  HistoryVisit,
  LatestPrescription,
  MedicalProfile,
  MedicalProfileInput,
  Medication,
  Visit,
  VitalsPoint,
} from '@/types/api'

// --- Query keys: everything clinical starts with 'patient-records' --------------------------

export const recordKeys = {
  all: ['patient-records'] as const,
  patient: (patientId: string) => ['patient-records', patientId] as const,
  chart: (patientId: string, appointmentId?: string) =>
    ['patient-records', patientId, 'chart', appointmentId ?? null] as const,
  history: (patientId: string) => ['patient-records', patientId, 'history'] as const,
  medications: (patientId: string) => ['patient-records', patientId, 'medications'] as const,
  vitals: (patientId: string) => ['patient-records', patientId, 'vitals'] as const,
  latestPrescription: (patientId: string) =>
    ['patient-records', patientId, 'latest-prescription'] as const,
  visit: (appointmentId: string) => ['patient-records', 'visit', appointmentId] as const,
}

// --- API ------------------------------------------------------------------------------------

export const fetchChart = (patientId: string, appointmentId?: string, signal?: AbortSignal) =>
  api<Chart>(`/patients/${patientId}/chart`, { query: { appointment: appointmentId }, signal })

export const saveMedicalProfile = (patientId: string, body: MedicalProfileInput) =>
  api<MedicalProfile>(`/patients/${patientId}/medical-profile`, { method: 'PUT', body })

export const fetchHistory = (patientId: string, signal?: AbortSignal) =>
  api<HistoryVisit[]>(`/patients/${patientId}/consultations`, { signal })

export const fetchMedications = (patientId: string, signal?: AbortSignal) =>
  api<Medication[]>(`/patients/${patientId}/medications`, { signal })

export const fetchVitals = (patientId: string, signal?: AbortSignal) =>
  api<VitalsPoint[]>(`/patients/${patientId}/vitals`, { signal })

export const fetchLatestPrescription = (patientId: string, signal?: AbortSignal) =>
  api<LatestPrescription | null>(`/patients/${patientId}/prescriptions/latest`, { signal })

export const fetchVisit = (appointmentId: string, signal?: AbortSignal) =>
  api<Visit>(`/appointments/${appointmentId}/consultation`, { signal })

export const saveVisit = (appointmentId: string, body: ConsultationInput) =>
  api<Visit>(`/appointments/${appointmentId}/consultation`, { method: 'PUT', body })

export const completeVisit = (appointmentId: string) =>
  api<CompleteResult>(`/appointments/${appointmentId}/complete`, { method: 'POST' })

export const addAddendum = (consultationId: string, text: string) =>
  api<Addendum>(`/consultations/${consultationId}/addenda`, { method: 'POST', body: { text } })

// --- Display helpers ------------------------------------------------------------------------

export const FREQUENCY_PRESETS = ['1-0-1', '1-1-1', '1-0-0', '0-0-1', 'SOS'] as const

export const TIMING_LABEL: Record<string, string> = {
  before_food: 'Before food',
  after_food: 'After food',
  with_food: 'With food',
  empty_stomach: 'Empty stomach',
  bedtime: 'At bedtime',
  any: 'Any time',
}

/** "Metformin 500 mg tablet · 1-0-1 · after food · 30 days" */
export function describeItem(item: {
  medicine_name: string
  strength?: string | null
  dosage_form?: string | null
  dose?: string | null
  frequency?: string | null
  timing?: string | null
  duration_days?: number | null
}): string {
  const head = [item.medicine_name, item.strength, item.dosage_form].filter(Boolean).join(' ')
  const rest = [
    item.dose,
    item.frequency,
    item.timing ? TIMING_LABEL[item.timing]?.toLowerCase() : null,
    item.duration_days ? `${item.duration_days} day${item.duration_days === 1 ? '' : 's'}` : null,
  ].filter(Boolean)
  return [head, ...rest].join(' · ')
}

/** "BP 140/90 · Pulse 82 · 78.5 kg" (only the recorded values). */
export function describeVitals(v: {
  bp_systolic?: number | null
  bp_diastolic?: number | null
  pulse?: number | null
  temperature_c?: number | null
  weight_kg?: number | null
  height_cm?: number | null
  spo2?: number | null
  blood_sugar?: number | null
}): string {
  const parts = [
    v.bp_systolic && v.bp_diastolic ? `BP ${v.bp_systolic}/${v.bp_diastolic}` : null,
    v.pulse ? `Pulse ${v.pulse}` : null,
    v.temperature_c ? `${v.temperature_c} °C` : null,
    v.spo2 ? `SpO₂ ${v.spo2}%` : null,
    v.weight_kg ? `${v.weight_kg} kg` : null,
    v.height_cm ? `${v.height_cm} cm` : null,
    v.blood_sugar ? `Sugar ${v.blood_sugar} mg/dL` : null,
  ]
  return parts.filter(Boolean).join(' · ')
}
