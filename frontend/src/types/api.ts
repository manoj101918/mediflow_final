// Hand-written mirrors of the FastAPI response models (backend/app/schemas).
import type { Database } from '@/types/database'

type Enums = Database['public']['Enums']

export type UserRole = Enums['user_role']
export type AppointmentStatus = Enums['appointment_status']
export type AppointmentSource = Enums['appointment_source']
export type Gender = Enums['gender']
export type ActorType = Enums['actor_type']

export interface Clinic {
  id: string
  name: string
  timezone: string
}

export interface Me {
  id: string
  email: string | null
  full_name: string
  role: UserRole
  clinic: Clinic
  doctor_id: string | null
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// --- Appointments ---------------------------------------------------------------------------

export interface PatientBrief {
  id: string
  full_name: string
  /** Null for doctors. */
  phone: string | null
  gender: Gender | null
  age: number | null
}

export interface DoctorBrief {
  id: string
  full_name: string
  specialization: string
}

export interface Appointment {
  id: string
  token_number: number
  status: AppointmentStatus
  source: AppointmentSource
  /** UTC ISO timestamps. */
  starts_at: string
  ends_at: string
  /** Clinic-local date, YYYY-MM-DD. */
  appointment_date: string
  reason_for_visit: string | null
  notes: string | null
  external_ref: string | null
  created_at: string
  updated_at: string
  patient: PatientBrief
  doctor: DoctorBrief
}

export interface AppointmentEvent {
  id: number
  from_status: AppointmentStatus | null
  to_status: AppointmentStatus
  actor_type: ActorType
  channel: string
  changed_by_name: string | null
  note: string | null
  created_at: string
}

export interface AppointmentDetail extends Appointment {
  events: AppointmentEvent[]
}

export type StaffSource = Extract<AppointmentSource, 'walk_in' | 'phone' | 'manual'>

export interface AppointmentCreate {
  patient_id: string
  doctor_id: string
  starts_at: string
  source: StaffSource
  reason_for_visit?: string | null
  notes?: string | null
  squeeze_in?: boolean
}

// --- Doctors --------------------------------------------------------------------------------

export interface Schedule {
  id: string
  weekday: number
  /** HH:MM:SS */
  start_time: string
  end_time: string
}

export interface Leave {
  id: string
  leave_date: string
  reason: string | null
}

export interface Doctor {
  id: string
  full_name: string
  specialization: string
  consultation_fee: number
  default_slot_minutes: number
  is_active: boolean
  profile_id: string | null
  schedules: Schedule[]
  upcoming_leaves: Leave[]
  on_leave_today: boolean
  created_at: string
}

export interface Slot {
  starts_at: string
  ends_at: string
}

export interface DaySlots {
  doctor_id: string
  date: string
  slot_minutes: number
  on_leave: boolean
  slots: Slot[]
}

// --- Patients -------------------------------------------------------------------------------

export interface Patient {
  id: string
  full_name: string
  phone: string
  alternate_phone: string | null
  gender: Gender | null
  date_of_birth: string | null
  age_years: number | null
  /** From date_of_birth when known, else age_years. */
  age: number | null
  address: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface PatientVisit {
  id: string
  starts_at: string
  appointment_date: string
  token_number: number
  status: AppointmentStatus
  source: AppointmentSource
  doctor_name: string
  reason_for_visit: string | null
}

export interface PatientDetail extends Patient {
  appointments: PatientVisit[]
}

export interface PatientInput {
  full_name: string
  phone: string
  alternate_phone: string | null
  gender: Gender | null
  date_of_birth: string | null
  age_years: number | null
  address: string | null
  notes: string | null
}

export type DuplicateReason = 'same_phone' | 'similar_name' | 'same_phone_similar_name'

export interface Duplicate {
  patient: Patient
  reason: DuplicateReason
}

// --- Admin ----------------------------------------------------------------------------------

export interface StaffUser {
  id: string
  email: string | null
  full_name: string
  phone: string | null
  role: UserRole
  is_active: boolean
  /** Linked doctor record (doctor accounts only). */
  doctor_id: string | null
  created_at: string
}

export interface StaffUserCreate {
  email: string
  password: string
  full_name: string
  phone: string | null
  role: UserRole
  doctor_id: string | null
}

export interface DoctorInput {
  full_name: string
  specialization: string
  consultation_fee: number
  default_slot_minutes: number
}

export interface ShiftInput {
  weekday: number
  start_time: string
  end_time: string
}

export interface LeaveCreated extends Leave {
  affected_appointments: number
}

// --- Inbound (bot) requests -------------------------------------------------------------------

export type InboundStatus = Enums['inbound_status']
export type InboundChannel = Enums['inbound_channel']

export interface InboundRequest {
  id: string
  channel: InboundChannel
  external_ref: string | null
  caller_phone: string | null
  parsed_patient_name: string | null
  requested_doctor_id: string | null
  requested_doctor_name: string | null
  requested_time: string | null
  status: InboundStatus
  /** "CODE: message" explaining why it was not booked automatically. */
  error: string | null
  appointment_id: string | null
  created_at: string
}
