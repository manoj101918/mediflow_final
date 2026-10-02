import { useQuery } from '@tanstack/react-query'
import { ExternalLinkIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchReportUrl } from '@/lib/reports'

export interface OpenReport {
  id: string
  page?: number | null
  title?: string
}

/** Inline PDF/image viewer. Each open asks for a fresh short-lived signed URL (and is logged). */
export function ReportViewer({ report, onClose }: { report: OpenReport | null; onClose: () => void }) {
  const url = useQuery({
    queryKey: ['patient-records', 'report-url', report?.id ?? null],
    queryFn: () => fetchReportUrl(report!.id),
    enabled: report != null,
    // Signed URLs expire quickly; never reuse one.
    gcTime: 0,
    staleTime: 0,
  })
  const pdf = url.data?.mime_type === 'application/pdf'
  const src = url.data ? `${url.data.url}${pdf && report?.page ? `#page=${report.page}` : ''}` : ''

  return (
    <Dialog open={report != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex h-[90svh] max-w-5xl flex-col sm:max-w-5xl">
        <DialogHeader className="flex-row items-center justify-between gap-2 pr-8">
          <DialogTitle>
            {report?.title ?? 'Report'}
            {report?.page ? <span className="text-muted-foreground"> · page {report.page}</span> : null}
          </DialogTitle>
          {url.data && (
            <Button variant="ghost" size="sm" asChild>
              <a href={src} target="_blank" rel="noreferrer">
                <ExternalLinkIcon />
                Open in new tab
              </a>
            </Button>
          )}
        </DialogHeader>
        <div className="min-h-0 flex-1" data-testid="report-viewer">
          {url.isPending ? (
            <Skeleton className="size-full" />
          ) : url.isError ? (
            <p className="text-sm text-destructive">{url.error.message}</p>
          ) : pdf ? (
            <iframe key={src} title={report?.title ?? 'Report'} src={src} className="size-full rounded-md border" />
          ) : (
            <div className="flex size-full items-center justify-center overflow-auto rounded-md border bg-muted/30">
              <img src={src} alt={report?.title ?? 'Report'} className="max-h-full max-w-full object-contain" />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
