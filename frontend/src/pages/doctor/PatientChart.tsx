import { useQuery } from '@tanstack/react-query'
import { ArrowLeftIcon } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ChartHeader } from '@/components/chart/ChartHeader'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { CurrentVisit } from '@/components/chart/CurrentVisit'
import { MedicationsTab } from '@/components/chart/MedicationsTab'
import { type OpenReport, ReportViewer } from '@/components/chart/ReportViewer'
import { ReportsTab } from '@/components/chart/ReportsTab'
import { useReports } from '@/hooks/useReports'
import { VisitHistory } from '@/components/chart/VisitHistory'
import { VitalsTrend } from '@/components/chart/VitalsTrend'
import { LabResultsTab } from '@/components/labs/LabResultsTab'
import { LabTrends } from '@/components/labs/LabTrends'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ApiError } from '@/lib/api'
import { fetchChart, recordKeys } from '@/lib/records'
import type { Citation } from '@/types/api'

type Tab = 'current' | 'history' | 'labs' | 'lab-trends' | 'medications' | 'reports' | 'vitals'

export function PatientChartPage() {
  const { patientId = '' } = useParams()
  const [params] = useSearchParams()
  const appointmentId = params.get('appointment') ?? undefined
  // ?labs=<order id> (from the results inbox) opens the Lab results tab on that order.
  const labsOrder = params.get('labs')

  const chart = useQuery({
    queryKey: recordKeys.chart(patientId, appointmentId),
    queryFn: ({ signal }) => fetchChart(patientId, appointmentId, signal),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  })
  const reports = useReports(patientId)

  const [tab, setTab] = useState<Tab>(labsOrder ? 'labs' : appointmentId ? 'current' : 'history')
  const [focusLab, setFocusLab] = useState<{ orderId?: string | null; itemId?: string | null; token: number } | null>(
    labsOrder ? { orderId: labsOrder, token: 0 } : null,
  )
  const [focusVisit, setFocusVisit] = useState<{ id: string; token: number } | null>(null)
  const [viewing, setViewing] = useState<OpenReport | null>(null)
  const header = useRef<HTMLDivElement>(null)

  const openReport = useCallback(
    (reportId: string, page?: number | null) => {
      const title = reports.data?.find((r) => r.id === reportId)?.title
      setViewing({ id: reportId, page, title })
    },
    [reports.data],
  )

  /** A citation chip opens what it cites: the visit, the report at its page, or the summary. */
  const openCitation = useCallback(
    (citation: Citation) => {
      if (citation.source_type === 'consultation') {
        setTab('history')
        setFocusVisit({ id: citation.source_id, token: Date.now() })
      } else if (citation.source_type === 'lab_result') {
        setTab('labs')
        setFocusLab({ orderId: citation.source_id, itemId: citation.item_id ?? null, token: Date.now() })
      } else if (citation.source_type === 'report') {
        openReport(citation.source_id, citation.page)
      } else {
        header.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    },
    [openReport],
  )

  if (chart.isPending) {
    return (
      <div className="mx-auto max-w-7xl space-y-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-96" />
      </div>
    )
  }
  if (chart.isError) {
    return (
      <div className="mx-auto max-w-xl rounded-xl border bg-background p-6 text-center">
        <h1 className="text-lg font-semibold">Chart unavailable</h1>
        <p className="mt-1 text-sm text-muted-foreground">{chart.error.message}</p>
        <Button asChild variant="outline" className="mt-4">
          <Link to="/doctor">Back to today</Link>
        </Button>
      </div>
    )
  }

  const hasVisit = Boolean(appointmentId && chart.data.appointment)

  return (
    <div className="mx-auto grid max-w-[1600px] gap-4 xl:grid-cols-[minmax(0,1fr)_26rem]">
      <div className="min-w-0 space-y-4">
        <Button asChild variant="ghost" size="sm" className="-ml-2">
          <Link to="/doctor">
            <ArrowLeftIcon />
            Today&apos;s queue
          </Link>
        </Button>
        <div ref={header} className="scroll-mt-4">
          <ChartHeader chart={chart.data} />
        </div>
        <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
          <TabsList className="flex-wrap">
            {hasVisit && <TabsTrigger value="current">Current visit</TabsTrigger>}
            <TabsTrigger value="history">Visit history</TabsTrigger>
            <TabsTrigger value="labs">Lab results</TabsTrigger>
            <TabsTrigger value="medications">Medications</TabsTrigger>
            <TabsTrigger value="reports">Reports</TabsTrigger>
            <TabsTrigger value="vitals">Vitals trend</TabsTrigger>
            <TabsTrigger value="lab-trends">Lab trends</TabsTrigger>
          </TabsList>
          {hasVisit && appointmentId && (
            <TabsContent value="current" forceMount hidden={tab !== 'current'}>
              <CurrentVisit patientId={patientId} appointmentId={appointmentId} />
            </TabsContent>
          )}
          <TabsContent value="history">
            <VisitHistory patientId={patientId} focus={focusVisit} onOpenReport={(id) => openReport(id)} />
          </TabsContent>
          <TabsContent value="labs">
            <LabResultsTab patientId={patientId} focus={focusLab} onOpenReport={(id) => openReport(id)} />
          </TabsContent>
          <TabsContent value="medications">
            <MedicationsTab patientId={patientId} />
          </TabsContent>
          <TabsContent value="reports">
            <ReportsTab patientId={patientId} canView onOpenReport={(id) => openReport(id)} />
          </TabsContent>
          <TabsContent value="vitals">
            <VitalsTrend patientId={patientId} />
          </TabsContent>
          <TabsContent value="lab-trends">
            <LabTrends patientId={patientId} />
          </TabsContent>
        </Tabs>
      </div>
      <aside className="xl:sticky xl:top-4 xl:self-start">
        <ChatPanel patientId={patientId} onCite={openCitation} />
      </aside>
      <ReportViewer report={viewing} onClose={() => setViewing(null)} />
    </div>
  )
}
