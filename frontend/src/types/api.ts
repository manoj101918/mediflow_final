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

// --- Clinical records (doctor chart) -------------------------------------------------------
// Mirrors backend/app/schemas/records.py and reports.py.

export type ConsultationStatus = Enums['consultation_status']
export type ReportType = Enums['report_type']
export type IngestionStatus = Enums['ingestion_status']
export type BloodGroup = 'A+' | 'A-' | 'B+' | 'B-' | 'AB+' | 'AB-' | 'O+' | 'O-'
export type Timing = 'before_food' | 'after_food' | 'with_food' | 'empty_stomach' | 'bedtime' | 'any'

export interface Vitals {
  bp_systolic?: number | null
  bp_diastolic?: number | null
  pulse?: number | null
  temperature_c?: number | null
  weight_kg?: number | null
  height_cm?: number | null
  spo2?: number | null
  blood_sugar?: number | null
}

export interface PrescriptionItemInput {
  medicine_name: string
  strength?: string | null
  dosage_form?: string | null
  dose?: string | null
  route?: string | null
  /** Indian style, e.g. 1-0-1, or SOS. */
  frequency?: string | null
  timing?: Timing | null
  duration_days?: number | null
  instructions?: string | null
}

export interface PrescriptionItem {
  id: string
  medicine_name: string
  strength: string | null
  dosage_form: string | null
  dose: string | null
  route: string | null
  frequency: string | null
  timing: string | null
  duration_days: number | null
  instructions: string | null
  sort_order: number
}

/** Draft autosave body: only keys present change; `items` replaces the prescription. */
export interface ConsultationInput {
  chief_complaint?: string | null
  history?: string | null
  examination?: string | null
  diagnosis?: string | null
  advice?: string | null
  follow_up_date?: string | null
  notes?: string | null
  vitals?: Vitals | null
  items?: PrescriptionItemInput[] | null
}

export interface Consultation {
  id: string
  appointment_id: string
  patient_id: string
  doctor_id: string
  chief_complaint: string | null
  history: string | null
  examination: string | null
  diagnosis: string | null
  advice: string | null
  follow_up_date: string | null
  notes: string | null
  vitals: Vitals
  status: ConsultationStatus
  finalized_at: string | null
  created_at: string
  updated_at: string
  items: PrescriptionItem[]
}

export interface Visit {
  appointment_id: string
  appointment_status: AppointmentStatus
  doctor_id: string
  /** True when the signed-in doctor may edit (own visit, checked in / in consultation, draft). */
  editable: boolean
  consultation: Consultation | null
}

export interface CompleteResult {
  appointment_id: string
  appointment_status: AppointmentStatus
  consultation_id: string | null
  finalized: boolean
}

export interface Addendum {
  id: string
  consultation_id: string
  author_name: string
  text: string
  created_at: string
}

export interface MedicalProfile {
  blood_group: string | null
  allergies: string[]
  chronic_conditions: string[]
  updated_at: string | null
}

export interface MedicalProfileInput {
  blood_group: BloodGroup | null
  allergies: string[]
  chronic_conditions: string[]
}

export interface ChartAppointment {
  id: string
  token_number: number
  status: AppointmentStatus
  starts_at: string
  appointment_date: string
  reason_for_visit: string | null
  doctor_id: string
  doctor_name: string
}

/** Chart header. No phone numbers (doctors never see them). */
export interface Chart {
  patient_id: string
  full_name: string
  gender: Gender | null
  age: number | null
  date_of_birth: string | null
  profile: MedicalProfile
  visit_count: number
  last_visit: string | null
  appointment: ChartAppointment | null
}

export interface ReportBrief {
  id: string
  title: string
  report_type: ReportType
  report_date: string | null
  mime_type: string
  ingestion_status: IngestionStatus
}

export interface HistoryVisit {
  consultation_id: string
  appointment_id: string
  visit_date: string
  token_number: number
  doctor_id: string
  doctor_name: string
  doctor_specialization: string
  chief_complaint: string | null
  history: string | null
  examination: string | null
  diagnosis: string | null
  advice: string | null
  follow_up_date: string | null
  notes: string | null
  vitals: Vitals
  finalized_at: string | null
  items: PrescriptionItem[]
  addenda: Addendum[]
  reports: ReportBrief[]
}

export interface Medication {
  item: PrescriptionItem
  consultation_id: string
  visit_date: string
  doctor_name: string
  /** Last day of the course, if a duration was given. */
  end_date: string | null
  current: boolean
}

export interface VitalsPoint {
  consultation_id: string
  visit_date: string
  vitals: Vitals
}

export interface LatestPrescription {
  consultation_id: string
  visit_date: string
  doctor_name: string
  items: PrescriptionItem[]
}

/** Report metadata (reception, admin and doctors). */
export interface Report {
  id: string
  patient_id: string
  consultation_id: string | null
  title: string
  report_type: ReportType
  report_date: string | null
  mime_type: string
  size_bytes: number
  page_count: number | null
  ingestion_status: IngestionStatus
  ingestion_error: string | null
  created_at: string
  updated_at: string
}

export interface ReportUrl {
  url: string
  mime_type: string
  expires_in: number
}
