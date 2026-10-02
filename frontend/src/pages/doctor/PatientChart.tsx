import { useQuery } from '@tanstack/react-query'
import { ArrowLeftIcon } from 'lucide-react'
import { useCallback, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'

import { ChartHeader } from '@/components/chart/ChartHeader'
import { CurrentVisit } from '@/components/chart/CurrentVisit'
import { MedicationsTab } from '@/components/chart/MedicationsTab'
import { type OpenReport, ReportViewer } from '@/components/chart/ReportViewer'
import { ReportsTab } from '@/components/chart/ReportsTab'
import { useReports } from '@/hooks/useReports'
import { VisitHistory } from '@/components/chart/VisitHistory'
import { VitalsTrend } from '@/components/chart/VitalsTrend'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ApiError } from '@/lib/api'
import { fetchChart, recordKeys } from '@/lib/records'

type Tab = 'current' | 'history' | 'medications' | 'reports' | 'vitals'

export function PatientChartPage() {
  const { patientId = '' } = useParams()
  const [params] = useSearchParams()
  const appointmentId = params.get('appointment') ?? undefined

  const chart = useQuery({
    queryKey: recordKeys.chart(patientId, appointmentId),
    queryFn: ({ signal }) => fetchChart(patientId, appointmentId, signal),
    retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
  })
  const reports = useReports(patientId)

  const [tab, setTab] = useState<Tab>(appointmentId ? 'current' : 'history')
  const [focusVisit] = useState<string | null>(null)
  const [viewing, setViewing] = useState<OpenReport | null>(null)

  const openReport = useCallback(
    (reportId: string, page?: number | null) => {
      const title = reports.data?.find((r) => r.id === reportId)?.title
      setViewing({ id: reportId, page, title })
    },
    [reports.data],
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
    <div className="mx-auto max-w-7xl space-y-4">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/doctor">
          <ArrowLeftIcon />
          Today&apos;s queue
        </Link>
      </Button>
      <ChartHeader chart={chart.data} />
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
        <TabsList className="flex-wrap">
          {hasVisit && <TabsTrigger value="current">Current visit</TabsTrigger>}
          <TabsTrigger value="history">Visit history</TabsTrigger>
          <TabsTrigger value="medications">Medications</TabsTrigger>
          <TabsTrigger value="reports">Reports</TabsTrigger>
          <TabsTrigger value="vitals">Vitals trend</TabsTrigger>
        </TabsList>
        {hasVisit && appointmentId && (
          <TabsContent value="current" forceMount hidden={tab !== 'current'}>
            <CurrentVisit patientId={patientId} appointmentId={appointmentId} />
          </TabsContent>
        )}
        <TabsContent value="history">
          <VisitHistory patientId={patientId} focusConsultationId={focusVisit} onOpenReport={(id) => openReport(id)} />
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
      </Tabs>
      <ReportViewer report={viewing} onClose={() => setViewing(null)} />
    </div>
  )
}
