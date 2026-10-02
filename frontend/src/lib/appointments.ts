import {
  BotMessageSquareIcon,
  FootprintsIcon,
  type LucideIcon,
  PencilLineIcon,
  PhoneIcon,
  PhoneCallIcon,
} from 'lucide-react'

import { api } from '@/lib/api'
import type {
  Appointment,
  AppointmentCreate,
  AppointmentDetail,
  AppointmentSource,
  AppointmentStatus,
  DaySlots,
  Doctor,
  Page,
} from '@/types/api'

// --- Query keys (everything appointment-related starts with 'appointments') -----------------

export const appointmentKeys = {
  all: ['appointments'] as const,
  day: (date: string) => ['appointments', 'day', date] as const,
  detail: (id: string) => ['appointments', 'detail', id] as const,
}

export const doctorKeys = {
  all: ['doctors'] as const,
  // Free slots change whenever an appointment does, so they live under 'appointments'.
  slots: (doctorId: string, date: string) => ['appointments', 'slots', doctorId, date] as const,
}

// --- API ------------------------------------------------------------------------------------

const PAGE_SIZE = 200

/** Every appointment on a clinic-local day (all pages). */
export async function fetchDayAppointments(
  date: string,
  signal?: AbortSignal,
): Promise<Appointment[]> {
  const items: Appointment[] = []
  for (let page = 1; ; page++) {
    const result = await api<Page<Appointment>>('/appointments', {
      query: { date, page, page_size: PAGE_SIZE },
      signal,
    })
    items.push(...result.items)
    if (items.length >= result.total || result.items.length === 0) return items
  }
}

export const fetchAppointment = (id: string, signal?: AbortSignal) =>
  api<AppointmentDetail>(`/appointments/${id}`, { signal })

export const createAppointment = (body: AppointmentCreate) =>
  api<Appointment>('/appointments', { method: 'POST', body })

export const changeStatus = (id: string, status: AppointmentStatus, note?: string) =>
  api<Appointment>(`/appointments/${id}/status`, {
    method: 'POST',
    body: { status, note: note || null },
  })

export const approveAppointment = (id: string) =>
  api<Appointment>(`/appointments/${id}/approve`, { method: 'POST' })

export const rejectAppointment = (id: string, reason?: string) =>
  api<Appointment>(`/appointments/${id}/reject`, {
    method: 'POST',
    body: { reason: reason || null },
  })

export const rescheduleAppointment = (id: string, startsAt: string, squeezeIn = false) =>
  api<Appointment>(`/appointments/${id}/reschedule`, {
    method: 'POST',
    body: { starts_at: startsAt, squeeze_in: squeezeIn },
  })

export const fetchDoctors = (signal?: AbortSignal) => api<Doctor[]>('/doctors', { signal })

export const fetchSlots = (doctorId: string, date: string, signal?: AbortSignal) =>
  api<DaySlots>(`/doctors/${doctorId}/slots`, { query: { date }, signal })

// --- Status & source metadata ---------------------------------------------------------------

/** Mirrors backend ALLOWED_TRANSITIONS (app/services/booking/status.py). */
export const ALLOWED_TRANSITIONS: Record<AppointmentStatus, readonly AppointmentStatus[]> = {
  pending_confirmation: ['scheduled', 'cancelled'],
  scheduled: ['checked_in', 'cancelled', 'no_show'],
  checked_in: ['in_consultation', 'cancelled', 'no_show'],
  in_consultation: ['completed'],
  completed: [],
  cancelled: [],
  no_show: [],
}

export const RESCHEDULABLE: readonly AppointmentStatus[] = ['pending_confirmation', 'scheduled']

export const STATUS_ORDER: readonly AppointmentStatus[] = [
  'pending_confirmation',
  'scheduled',
  'checked_in',
  'in_consultation',
  'completed',
  'no_show',
  'cancelled',
]

export const STATUS_META: Record<AppointmentStatus, { label: string; className: string }> = {
  pending_confirmation: {
    label: 'Pending',
    className: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  },
  scheduled: {
    label: 'Scheduled',
    className: 'bg-slate-100 text-slate-700 dark:bg-slate-500/20 dark:text-slate-200',
  },
  checked_in: {
    label: 'Waiting',
    className: 'bg-sky-100 text-sky-900 dark:bg-sky-500/20 dark:text-sky-200',
  },
  in_consultation: {
    label: 'With doctor',
    className: 'bg-violet-100 text-violet-900 dark:bg-violet-500/20 dark:text-violet-200',
  },
  completed: {
    label: 'Completed',
    className: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-muted text-muted-foreground line-through decoration-1',
  },
  no_show: {
    label: 'No-show',
    className: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  },
}

/** The verb shown on an action that moves an appointment into this status. */
export const STATUS_ACTION: Partial<Record<AppointmentStatus, string>> = {
  scheduled: 'Approve',
  checked_in: 'Check in',
  in_consultation: 'Start consultation',
  completed: 'Complete',
  no_show: 'Mark no-show',
  cancelled: 'Cancel',
}

export const SOURCE_META: Record<AppointmentSource, { label: string; icon: LucideIcon }> = {
  walk_in: { label: 'Walk-in', icon: FootprintsIcon },
  phone: { label: 'Phone', icon: PhoneIcon },
  manual: { label: 'Manual', icon: PencilLineIcon },
  whatsapp: { label: 'WhatsApp', icon: BotMessageSquareIcon },
  voice: { label: 'Voice bot', icon: PhoneCallIcon },
}

/** Appointments that still occupy the doctor's time. */
export function isLive(status: AppointmentStatus): boolean {
  return status !== 'cancelled' && status !== 'no_show'
}
