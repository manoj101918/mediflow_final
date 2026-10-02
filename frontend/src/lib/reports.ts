import { api } from '@/lib/api'
import type { IngestionStatus, Report, ReportType, ReportUrl } from '@/types/api'

// Reports are part of the patient record, so their keys share the 'patient-records' prefix.
export const reportKeys = {
  list: (patientId: string) => ['patient-records', patientId, 'reports'] as const,
}

export interface ReportUploadInput {
  file: File
  title: string
  report_type: ReportType
  report_date: string | null
  consultation_id?: string | null
}

export function uploadReport(patientId: string, input: ReportUploadInput): Promise<Report> {
  const form = new FormData()
  form.append('file', input.file)
  form.append('title', input.title)
  form.append('report_type', input.report_type)
  if (input.report_date) form.append('report_date', input.report_date)
  if (input.consultation_id) form.append('consultation_id', input.consultation_id)
  return api<Report>(`/patients/${patientId}/reports`, { method: 'POST', body: form })
}

export const fetchReports = (patientId: string, signal?: AbortSignal) =>
  api<Report[]>(`/patients/${patientId}/reports`, { signal })

export const fetchReportUrl = (reportId: string) => api<ReportUrl>(`/reports/${reportId}/url`)

export const retryReport = (reportId: string) =>
  api<Report>(`/reports/${reportId}/retry`, { method: 'POST' })

export const REPORT_TYPE_LABEL: Record<ReportType, string> = {
  lab: 'Lab',
  imaging: 'Imaging',
  discharge_summary: 'Discharge summary',
  referral: 'Referral',
  old_prescription: 'Old prescription',
  other: 'Other',
}

export const REPORT_TYPES = Object.keys(REPORT_TYPE_LABEL) as ReportType[]

export const INGESTION_META: Record<IngestionStatus, { label: string; className: string }> = {
  pending: {
    label: 'Queued',
    className: 'bg-slate-100 text-slate-700 dark:bg-slate-500/20 dark:text-slate-200',
  },
  processing: {
    label: 'Indexing…',
    className: 'bg-sky-100 text-sky-900 dark:bg-sky-500/20 dark:text-sky-200',
  },
  indexed: {
    label: 'Searchable',
    className: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  },
  failed: {
    label: 'Failed',
    className: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  },
  no_text: {
    label: 'Not searchable',
    className: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  },
}

/** Still being processed: poll until it settles. */
export const isIngesting = (status: IngestionStatus) =>
  status === 'pending' || status === 'processing'

export const ACCEPTED_REPORT_TYPES = 'application/pdf,image/jpeg,image/png'
export const MAX_REPORT_MB = 10
