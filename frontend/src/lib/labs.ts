import { api } from '@/lib/api'
import type {
  LabAlert,
  LabCategory,
  LabFlag,
  LabInboxRow,
  LabItemStatus,
  LabOrder,
  LabOrderDetail,
  LabOrderInput,
  LabOrderStatus,
  LabOrderStatusRow,
  LabPriority,
  LabRange,
  LabRangeSex,
  LabSampleType,
  LabStatusCounts,
  LabTest,
  LabTrend,
  LabValueInput,
  LabValueType,
  LabWorklistRow,
  LabWorklistTab,
} from '@/types/api'

export const LAB_CATEGORY_LABEL: Record<LabCategory, string> = {
  haematology: 'Haematology',
  biochemistry: 'Biochemistry',
  hormones: 'Hormones',
  urine: 'Urine',
  serology: 'Serology',
  other: 'Other',
}

export const LAB_SAMPLE_LABEL: Record<LabSampleType, string> = {
  blood: 'Blood',
  urine: 'Urine',
  stool: 'Stool',
  swab: 'Swab',
  other: 'Other',
}

export const LAB_VALUE_TYPE_LABEL: Record<LabValueType, string> = {
  numeric: 'Number',
  text: 'Text',
  choice: 'Choice',
}

export const LAB_SEX_LABEL: Record<LabRangeSex, string> = {
  any: 'Any',
  male: 'Male',
  female: 'Female',
}

export const LAB_PRIORITY_LABEL: Record<LabPriority, string> = {
  routine: 'Routine',
  urgent: 'Urgent',
  stat: 'STAT',
}

export const LAB_ITEM_STATUS_LABEL: Record<LabItemStatus, string> = {
  ordered: 'Awaiting sample',
  sample_collected: 'Sample collected',
  sample_rejected: 'Recollect sample',
  result_entered: 'Awaiting verification',
  verified: 'Verified',
  released: 'Released',
  cancelled: 'Cancelled',
}

export const LAB_ORDER_STATUS_LABEL: Record<LabOrderStatus, string> = {
  ordered: 'Ordered',
  in_progress: 'In progress',
  partially_released: 'Partly ready',
  released: 'Results ready',
  cancelled: 'Cancelled',
}

export const LAB_FLAG_LABEL: Record<LabFlag, string> = {
  normal: 'Normal',
  low: 'Low',
  high: 'High',
  critical_low: 'Critical low',
  critical_high: 'Critical high',
  abnormal: 'Abnormal',
}

/** Short marker shown next to a value: H, L, HH, LL, A. */
export const LAB_FLAG_MARK: Record<LabFlag, string> = {
  normal: '',
  low: 'L',
  high: 'H',
  critical_low: 'LL',
  critical_high: 'HH',
  abnormal: 'A',
}

export const isCritical = (flag: LabFlag | null | undefined) => flag === 'critical_low' || flag === 'critical_high'
export const isAbnormal = (flag: LabFlag | null | undefined) => Boolean(flag && flag !== 'normal')

/** Text colour for a flagged value; the flag word next to it carries the meaning. */
export function flagTone(flag: LabFlag | null | undefined): string {
  if (isCritical(flag)) return 'font-semibold text-red-700 dark:text-red-400'
  if (isAbnormal(flag)) return 'font-semibold text-amber-700 dark:text-amber-400'
  return ''
}

/** Mirrors the server's flagging (services/labs/ranges.py) so the entry form flags while typing. */
export function flagValue(valueType: LabValueType, raw: string, range: LabRange | null): LabFlag | null {
  const text = raw.trim()
  if (!text || !range) return null
  if (valueType !== 'numeric') {
    if (!range.text_normal) return null
    return text.toLowerCase() === range.text_normal.toLowerCase() ? 'normal' : 'abnormal'
  }
  const value = Number(text)
  if (!Number.isFinite(value)) return null
  if (range.critical_low !== null && value <= range.critical_low) return 'critical_low'
  if (range.critical_high !== null && value >= range.critical_high) return 'critical_high'
  if (range.low !== null && value < range.low) return 'low'
  if (range.high !== null && value > range.high) return 'high'
  if (range.low === null && range.high === null) return null
  return 'normal'
}

export function formatResultValue(r: { value_numeric: number | null; value_text: string | null }): string {
  return r.value_numeric !== null ? String(r.value_numeric) : (r.value_text ?? '')
}

// --- Query keys -------------------------------------------------------------------------------
// Lab screens live under 'labs'; chart data under 'patient-records'; Today counts under
// 'appointments' (appointment changes refresh them too); reception patient lists under 'patients'.

export const labKeys = {
  all: ['labs'] as const,
  catalog: ['labs', 'catalog'] as const,
  worklist: (tab: LabWorklistTab, q: string) => ['labs', 'worklist', tab, q] as const,
  order: (orderId: string) => ['labs', 'order', orderId] as const,
  inbox: ['labs', 'inbox'] as const,
  alerts: ['labs', 'alerts'] as const,
  visitOrders: (appointmentId: string) => ['patient-records', 'visit', appointmentId, 'labs'] as const,
  patientResults: (patientId: string) => ['patient-records', patientId, 'labs'] as const,
  trends: (patientId: string) => ['patient-records', patientId, 'lab-trends'] as const,
  summary: (day: string) => ['appointments', 'lab-summary', day] as const,
  patientOrders: (patientId: string) => ['patients', patientId, 'lab-orders'] as const,
}

// --- Doctor -------------------------------------------------------------------------------------

export const fetchLabCatalog = (signal?: AbortSignal) => api<LabTest[]>('/lab/catalog', { signal })

export const fetchVisitLabOrders = (appointmentId: string, signal?: AbortSignal) =>
  api<LabOrder[]>(`/appointments/${appointmentId}/lab-orders`, { signal })

export const createLabOrder = (appointmentId: string, body: LabOrderInput) =>
  api<LabOrder>(`/appointments/${appointmentId}/lab-orders`, { method: 'POST', body })

export const fetchLastLabOrder = (patientId: string) =>
  api<{ test_ids: string[] }>(`/patients/${patientId}/lab-orders/last`)

export const cancelLabOrder = (orderId: string, body: { item_ids?: string[] | null; reason?: string | null }) =>
  api<LabOrder>(`/lab/orders/${orderId}/cancel`, { method: 'POST', body })

export const fetchPatientLabResults = (patientId: string, signal?: AbortSignal) =>
  api<LabOrder[]>(`/patients/${patientId}/lab-results`, { signal })

export const fetchLabTrends = (patientId: string, signal?: AbortSignal) =>
  api<LabTrend[]>(`/patients/${patientId}/lab-trends`, { signal })

export const fetchLabInbox = (signal?: AbortSignal) => api<LabInboxRow[]>('/lab/inbox', { signal })

export const markLabReviewed = (orderId: string) =>
  api<{ order_id: string; reviewed_at: string }>(`/lab/orders/${orderId}/review`, { method: 'POST' })

export const fetchLabAlerts = (signal?: AbortSignal) => api<LabAlert[]>('/lab/alerts', { signal })

export const acknowledgeLabAlert = (alertId: string, note: string | null) =>
  api<void>(`/lab/alerts/${alertId}/acknowledge`, { method: 'POST', body: { note } })

// --- Status only (reception and doctors) ---------------------------------------------------------

export const fetchLabSummary = (day: string, signal?: AbortSignal) =>
  api<LabStatusCounts[]>('/lab/status-summary', { query: { day }, signal })

export const fetchPatientLabOrders = (patientId: string, signal?: AbortSignal) =>
  api<LabOrderStatusRow[]>(`/patients/${patientId}/lab-orders`, { signal })

// --- Lab staff ------------------------------------------------------------------------------------

export const fetchWorklist = (tab: LabWorklistTab, q: string, signal?: AbortSignal) =>
  api<LabWorklistRow[]>('/lab/worklist', { query: { tab, q: q || undefined }, signal })

export const fetchLabOrder = (orderId: string, signal?: AbortSignal) =>
  api<LabOrderDetail>(`/lab/orders/${orderId}`, { signal })

export const collectSamples = (orderId: string, itemIds: string[]) =>
  api<LabOrderDetail>(`/lab/orders/${orderId}/collect`, { method: 'POST', body: { item_ids: itemIds } })

export const rejectSample = (sampleId: string, reason: string) =>
  api<LabOrderDetail>(`/lab/samples/${sampleId}/reject`, { method: 'POST', body: { reason } })

export const saveLabResults = (itemId: string, values: LabValueInput[], confirmCritical: boolean) =>
  api<LabOrderDetail>(`/lab/items/${itemId}/results`, {
    method: 'PUT',
    body: { values, confirm_critical: confirmCritical },
  })

export const labItemAction = (itemId: string, action: 'submit' | 'verify' | 'release') =>
  api<LabOrderDetail>(`/lab/items/${itemId}/${action}`, { method: 'POST' })

export const sendBackLabItem = (itemId: string, comment: string) =>
  api<LabOrderDetail>(`/lab/items/${itemId}/send-back`, { method: 'POST', body: { comment } })

export const amendLabItem = (itemId: string, values: LabValueInput[], reason: string) =>
  api<LabOrderDetail>(`/lab/items/${itemId}/amend`, { method: 'POST', body: { values, reason } })

export const fetchLabSettings = (signal?: AbortSignal) =>
  api<{ lab_requires_verification: boolean }>('/lab/settings', { signal })

/** The lab machine's own PDF for an order (stored with the order, not indexed separately). */
export function attachLabPdf(orderId: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return api<{ id: string; title: string }>(`/lab/orders/${orderId}/attachment`, { method: 'POST', body: form })
}
