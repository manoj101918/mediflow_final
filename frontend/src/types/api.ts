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
  /** Lab PDFs: generated from an order's results, or the lab machine's own PDF. */
  lab_order_id: string | null
  is_generated: boolean
  created_at: string
  updated_at: string
}

export interface ReportUrl {
  url: string
  mime_type: string
  expires_in: number
}

// --- Patient chat (assistant) ---------------------------------------------------------------
// Mirrors backend/app/schemas/chat.py.

export type CitationSourceType = 'summary' | 'profile' | 'consultation' | 'report' | 'lab_result'

/** What an [n] marker in an answer points at. */
export interface Citation {
  n: number
  source_type: CitationSourceType
  source_id: string
  label: string
  /** YYYY-MM-DD */
  date: string | null
  page: number | null
  /** lab_result: the cited test (source_id is its lab order). */
  item_id?: string | null
}

export interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  error_code: string | null
  created_at: string
}

/** Server-Sent Events from POST /patients/{id}/chat. */
export type ChatStreamEvent =
  | { event: 'token'; data: { text: string } }
  | { event: 'citations'; data: { citations: Citation[] } }
  | { event: 'done'; data: { session_id: string; message_id: string } }
  | { event: 'error'; data: { code: string; message: string; session_id: string; message_id: string } }

// ---------------------------------------------------------------------------
// Lab (Phase 3) — mirrors backend/app/schemas/labs.py
// ---------------------------------------------------------------------------

export type LabCategory = Enums['lab_category']
export type LabSampleType = Enums['lab_sample_type']
export type LabValueType = Enums['lab_value_type']
export type LabRangeSex = Enums['lab_range_sex']

export interface LabReferenceRangeInput {
  sex: LabRangeSex
  age_min_years: number | null
  age_max_years: number | null
  low: number | null
  high: number | null
  critical_low: number | null
  critical_high: number | null
  text_normal: string | null
}

export interface LabReferenceRange extends LabReferenceRangeInput {
  id: string
}

export interface LabParameterInput {
  /** Set to keep an existing parameter (results reference parameters by id). */
  id?: string | null
  code: string
  name: string
  unit: string | null
  value_type: LabValueType
  choices: string[]
  decimals: number
  delta_percent: number | null
  is_active: boolean
  ranges: LabReferenceRangeInput[]
}

export interface LabParameter extends Omit<LabParameterInput, 'id' | 'ranges'> {
  id: string
  ranges: LabReferenceRange[]
}

export interface LabTestInput {
  code: string
  name: string
  category: LabCategory
  sample_type: LabSampleType
  container: string | null
  turnaround_hours: number
  is_panel: boolean
  is_active: boolean
  sort_order: number
  parameters: LabParameterInput[]
}

export interface LabTest extends Omit<LabTestInput, 'parameters'> {
  id: string
  parameters: LabParameter[]
  updated_at: string
}

export interface ClinicSettings {
  lab_requires_verification: boolean
}

export type LabPriority = Enums['lab_priority']
export type LabOrderStatus = Enums['lab_order_status']
export type LabItemStatus = Enums['lab_item_status']
export type LabFlag = Enums['lab_flag']

export interface LabResult {
  id: string
  parameter_id: string
  parameter_code: string
  parameter_name: string
  unit: string | null
  value_type: LabValueType
  value_numeric: number | null
  value_text: string | null
  range_label: string | null
  ref_low: number | null
  ref_high: number | null
  flag: LabFlag | null
  version: number
  is_current: boolean
  amended_reason: string | null
  entered_at: string
}

export interface LabSample {
  id: string
  sample_code: string
  sample_type: LabSampleType
  container: string | null
  collected_at: string
  rejected_at: string | null
  rejected_reason: string | null
}

export interface LabItem {
  id: string
  test_id: string
  test_code: string
  test_name: string
  status: LabItemStatus
  sample_id: string | null
  sample_code: string | null
  rejection_reason: string | null
  return_comment: string | null
  entered_at: string | null
  verified_at: string | null
  released_at: string | null
  cancelled_reason: string | null
  /** Current values. Doctors get released tests only. */
  results: LabResult[]
  /** Earlier versions of amended results. */
  history: LabResult[]
}

export interface LabOrder {
  id: string
  order_number: string
  patient_id: string
  patient_name: string
  appointment_id: string
  consultation_id: string | null
  ordering_doctor_id: string
  ordering_doctor_name: string
  priority: LabPriority
  status: LabOrderStatus
  clinical_note: string | null
  cancelled_reason: string | null
  reviewed_at: string | null
  report_id: string | null
  created_at: string
  updated_at: string
  items: LabItem[]
  samples: LabSample[]
}

export interface LabOrderInput {
  test_ids: string[]
  priority: LabPriority
  clinical_note: string | null
}

/** Front desk view: no clinical note and no values. */
export interface LabOrderStatusRow {
  id: string
  order_number: string
  appointment_id: string
  ordering_doctor_name: string
  priority: LabPriority
  status: LabOrderStatus
  created_at: string
  tests: { test_name: string; status: LabItemStatus }[]
}

export interface LabStatusCounts {
  appointment_id: string
  pending: number
  ready: number
}

export interface LabPatient {
  id: string
  full_name: string
  phone: string
  gender: Gender | null
  age: number | null
}

export interface LabRange {
  low: number | null
  high: number | null
  critical_low: number | null
  critical_high: number | null
  text_normal: string | null
  label: string | null
}

export interface LabPrevious {
  value_numeric: number | null
  value_text: string | null
  unit: string | null
  flag: LabFlag | null
  released_at: string
  order_number: string
}

export interface LabParameterEntry {
  id: string
  code: string
  name: string
  unit: string | null
  value_type: LabValueType
  choices: string[]
  decimals: number
  delta_percent: number | null
  range: LabRange | null
  previous: LabPrevious | null
  delta_warning: boolean
}

export interface LabItemDetail extends LabItem {
  category: LabCategory
  sample_type: LabSampleType
  container: string | null
  parameters: LabParameterEntry[]
}

export interface LabOrderDetail {
  order: LabOrder
  patient: LabPatient
  requires_verification: boolean
  items: LabItemDetail[]
}

export type LabWorklistTab = 'to_collect' | 'in_progress' | 'awaiting_verification' | 'released_today' | 'rejected'

export interface LabWorklistRow {
  order_id: string
  order_number: string
  priority: LabPriority
  status: LabOrderStatus
  created_at: string
  patient_id: string
  patient_name: string
  patient_phone: string
  patient_gender: Gender | null
  patient_age: number | null
  ordering_doctor_name: string
  counts: Partial<Record<LabItemStatus, number>>
  tests: string[]
  sample_codes: string[]
}

export interface LabValueInput {
  parameter_id: string
  value: number | string | null
}

export interface LabTrendPoint {
  value: number
  flag: LabFlag | null
  ref_low: number | null
  ref_high: number | null
  released_at: string
  order_id: string
  order_item_id: string
  order_number: string
}

export interface LabTrend {
  code: string
  name: string
  unit: string | null
  points: LabTrendPoint[]
}

export interface LabInboxRow {
  order: LabOrder
  abnormal: number
  critical: number
}

export interface LabAlert {
  id: string
  patient_id: string
  patient_name: string
  order_id: string
  order_number: string
  parameter_name: string
  value: string
  unit: string | null
  flag: LabFlag | null
  range_label: string | null
  created_at: string
}

// --- Booking bot (backend app/schemas/bot.py, appointments.DecisionOut) ---

export type BotChannel = Enums['bot_channel']

export type BotNotificationStatus =
  | 'queued'
  | 'window_closed'
  | 'opted_out'
  | 'no_consent'
  | 'limit'
  | 'not_configured'
  | 'no_conversation'

/** What happened to the patient's WhatsApp / voice message after approve or reject. */
export interface BotNotification {
  status: BotNotificationStatus
  channel: BotChannel
  phone: string
}

export interface DecisionAppointment extends Appointment {
  notification: BotNotification | null
}

export interface BotUsage {
  month: string
  sent: number
  limit: number
  reserve_from: number
  warn: boolean
  exhausted: boolean
}

export interface WhatsAppStatus {
  configured: boolean
  fake: boolean
  connected: boolean | null
  display_phone_number: string | null
  verified_name: string | null
  error: string | null
  webhook_url: string | null
  webhook_last_seen_at: string | null
  paid_templates_allowed: boolean
}

export interface BotStatus {
  whatsapp: WhatsAppStatus
  usage: BotUsage
  llm_enabled: boolean
  stt_provider: string
  tts_provider: string
  clinic_configured: boolean
}

export interface BotConversationSummary {
  id: string
  channel: BotChannel
  phone: string
  names: string[]
  language: 'te' | 'hi' | 'en' | null
  state: string
  handoff_status: 'none' | 'open' | 'resolved'
  handoff_reason: 'button' | 'parse_failed' | 'emergency' | 'staff' | null
  handoff_at: string | null
  last_inbound_at: string | null
  last_message: string | null
  window_open: boolean
  opted_out: boolean
  open_alerts: number
  emergency: boolean
}

export interface BotTranscriptMessage {
  id: string
  direction: 'inbound' | 'outbound'
  type: string
  text: string | null
  transcript: string | null
  status: string
  created_at: string
}

export interface BotConversationDetail extends BotConversationSummary {
  messages: BotTranscriptMessage[]
}

export interface BotAlert {
  id: string
  kind: 'emergency' | 'handoff'
  conversation_id: string
  channel: BotChannel
  phone: string
  names: string[]
  excerpt: string | null
  created_at: string
}

export type KeywordKind = 'emergency' | 'stop' | 'start'
export type BotLanguage = 'te' | 'hi' | 'en'

export interface KeywordList {
  kind: KeywordKind
  language: BotLanguage
  words: string[]
  custom: boolean
}

export interface SimOption {
  id: string
  title: string
  description: string | null
}

export interface SimReply {
  text: string
  options: SimOption[]
}

export interface VoiceTurn {
  transcript: string
  voice_error: 'too_long' | 'failed' | null
  replies: SimReply[]
  speech_text: string
  audio_base64: string | null
  audio_mime: string | null
  tts_provider: string
  appointment_id: string | null
  state: string
}

export interface SimMessage {
  id: string
  kind: string
  text: string
  status: string
  appointment_id: string | null
  created_at: string
}
