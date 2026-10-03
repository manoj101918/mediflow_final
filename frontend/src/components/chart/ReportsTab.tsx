import { useMutation, useQueryClient } from '@tanstack/react-query'
import { EyeIcon, FileImageIcon, FileTextIcon, RotateCwIcon, UploadIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ReportUploadDialog } from '@/components/chart/ReportUploadDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { useReports } from '@/hooks/useReports'
import { INGESTION_META, REPORT_TYPE_LABEL, reportKeys, retryReport } from '@/lib/reports'
import { cn } from '@/lib/utils'
import type { Report } from '@/types/api'

interface Props {
  patientId: string
  /** Doctors can open files; reception only sees the list. */
  canView: boolean
  onOpenReport?: (reportId: string) => void
}

export function ReportsTab({ patientId, canView, onOpenReport }: Props) {
  const reports = useReports(patientId)
  const [uploading, setUploading] = useState(false)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Reports are indexed so the assistant can answer from them.
        </p>
        <Button variant="outline" onClick={() => setUploading(true)}>
          <UploadIcon />
          Upload report
        </Button>
      </div>
      {reports.isPending ? (
        <Skeleton className="h-32" />
      ) : reports.isError ? (
        <p className="text-sm text-destructive">{reports.error.message}</p>
      ) : reports.data.length === 0 ? (
        <p className="rounded-xl border bg-background p-6 text-sm text-muted-foreground">No reports uploaded.</p>
      ) : (
        <ul className="divide-y rounded-xl border bg-background">
          {reports.data.map((report) => (
            <ReportRow
              key={report.id}
              report={report}
              patientId={patientId}
              onOpen={canView && onOpenReport && !(report.is_generated && report.size_bytes === 0) ? () => onOpenReport(report.id) : undefined}
            />
          ))}
        </ul>
      )}
      {uploading && (
        <ReportUploadDialog patientId={patientId} open={uploading} onOpenChange={setUploading} />
      )}
    </div>
  )
}

export function IngestionBadge({ report }: { report: Report }) {
  // Lab PDFs are searchable through the order's structured results, not their own text.
  if (report.lab_order_id) {
    const preparing = report.is_generated && report.size_bytes === 0
    return (
      <Badge variant="secondary" className="font-medium" data-lab-report={report.is_generated ? 'generated' : 'machine'}>
        {preparing ? 'Lab report: preparing PDF' : report.is_generated ? 'Lab order' : 'Lab machine PDF'}
      </Badge>
    )
  }
  const meta = INGESTION_META[report.ingestion_status]
  return (
    <Badge className={cn('font-medium', meta.className)} title={report.ingestion_error ?? undefined}>
      {meta.label}
    </Badge>
  )
}

function ReportRow({
  report,
  patientId,
  onOpen,
}: {
  report: Report
  patientId: string
  onOpen?: () => void
}) {
  const queryClient = useQueryClient()
  const retry = useMutation({
    mutationFn: () => retryReport(report.id),
    onSuccess: () => {
      toast.success('Queued for indexing again')
      void queryClient.invalidateQueries({ queryKey: reportKeys.list(patientId) })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Retry failed.'),
  })
  const Icon = report.mime_type === 'application/pdf' ? FileTextIcon : FileImageIcon

  return (
    <li
      className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3"
      data-report-id={report.id}
      data-report-status={report.ingestion_status}
    >
      <Icon className="size-5 shrink-0 text-muted-foreground" />
      <div className="min-w-48 flex-1">
        <div className="font-medium">{report.title}</div>
        <div className="text-xs text-muted-foreground">
          {REPORT_TYPE_LABEL[report.report_type]}
          {report.report_date && <> · {formatDate(report.report_date)}</>}
          {report.page_count != null && <> · {report.page_count} page{report.page_count === 1 ? '' : 's'}</>}
        </div>
        {report.ingestion_error && (report.ingestion_status === 'failed' || report.ingestion_status === 'no_text') && (
          <div className="text-xs text-muted-foreground">{report.ingestion_error}</div>
        )}
      </div>
      <IngestionBadge report={report} />
      {report.ingestion_status === 'failed' && (
        <Button size="sm" variant="outline" onClick={() => retry.mutate()} disabled={retry.isPending}>
          <RotateCwIcon className={cn(retry.isPending && 'animate-spin')} />
          Retry
        </Button>
      )}
      {onOpen && (
        <Button size="sm" variant="ghost" onClick={onOpen}>
          <EyeIcon />
          View
        </Button>
      )}
    </li>
  )
}
