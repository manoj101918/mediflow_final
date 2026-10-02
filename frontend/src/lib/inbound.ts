import { api } from '@/lib/api'
import type { InboundRequest, InboundStatus } from '@/types/api'

export const inboundKeys = {
  // Under 'appointments' so realtime appointment events also refresh it.
  list: (status: InboundStatus) => ['appointments', 'inbound', status] as const,
}

export const fetchInboundRequests = (status: InboundStatus, signal?: AbortSignal) =>
  api<InboundRequest[]>('/inbound-requests', { query: { status }, signal })

export const dismissInboundRequest = (id: string) =>
  api<InboundRequest>(`/inbound-requests/${id}/dismiss`, { method: 'POST' })

const REASONS: Record<string, string> = {
  SLOT_TAKEN: 'Requested time was already taken',
  OUTSIDE_SCHEDULE: "Outside the doctor's hours",
  DOCTOR_ON_LEAVE: 'Doctor is on leave that day',
  IN_PAST: 'Requested time has passed',
  NOT_FOUND: 'Unknown doctor',
}

/** Human explanation of why a request was not booked automatically. */
export function inboundReason(error: string | null): string {
  if (!error) return ''
  const [code, ...rest] = error.split(': ')
  return REASONS[code ?? ''] ?? rest.join(': ') ?? error
}
