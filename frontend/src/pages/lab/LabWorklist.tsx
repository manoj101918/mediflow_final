import { useQuery } from '@tanstack/react-query'
import { SearchIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { LabOrderStatusBadge, LabPriorityBadge } from '@/components/labs/LabBadges'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { formatDate, formatPatientMeta, formatPhone, formatTime } from '@/lib/format'
import { LAB_ITEM_STATUS_LABEL, fetchLabSettings, fetchWorklist, labKeys } from '@/lib/labs'
import { cn } from '@/lib/utils'
import type { LabItemStatus, LabWorklistRow, LabWorklistTab } from '@/types/api'

const TABS: { value: LabWorklistTab; label: string; empty: string }[] = [
  { value: 'to_collect', label: 'To collect', empty: 'No samples waiting to be collected.' },
  { value: 'in_progress', label: 'In progress', empty: 'Nothing waiting for results.' },
  { value: 'awaiting_verification', label: 'Awaiting verification', empty: 'Nothing to verify.' },
  { value: 'released_today', label: 'Released today', empty: 'Nothing released yet today.' },
  { value: 'rejected', label: 'Rejected / recollect', empty: 'No rejected samples.' },
]

const ROW_ACCENT = {
  stat: 'border-l-4 border-l-red-600',
  urgent: 'border-l-4 border-l-amber-500',
  routine: 'border-l-4 border-l-transparent',
}

export function LabWorklistPage() {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as LabWorklistTab | null) ?? 'to_collect'
  const [search, setSearch] = useState('')
  const q = useDebouncedValue(search.trim(), 250)

  const settings = useQuery({ queryKey: ['labs', 'settings'], queryFn: ({ signal }) => fetchLabSettings(signal) })
  const tabs = TABS.filter((t) => t.value !== 'awaiting_verification' || settings.data?.lab_requires_verification !== false)
  const rows = useQuery({
    queryKey: labKeys.worklist(tab, q),
    queryFn: ({ signal }) => fetchWorklist(tab, q, signal),
    refetchInterval: 60_000,
  })

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Lab worklist</h1>
          <p className="text-sm text-muted-foreground">STAT and urgent orders stay on top. The list updates live.</p>
        </div>
        <div className="relative w-full max-w-sm">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Search worklist"
            placeholder="Patient, phone, order no. or sample code"
            className="pl-8"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <TabsList className="flex-wrap">
          {tabs.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card>
        <CardContent className="p-0">
          {rows.isPending ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-14" />
              <Skeleton className="h-14" />
            </div>
          ) : rows.isError ? (
            <p className="p-4 text-sm text-destructive">{rows.error.message}</p>
          ) : rows.data.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {q ? 'No orders match your search.' : TABS.find((t) => t.value === tab)?.empty}
            </p>
          ) : (
            <ul className="divide-y" aria-label="Lab orders">
              {rows.data.map((row) => (
                <WorklistItem key={row.order_id} row={row} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function WorklistItem({ row }: { row: LabWorklistRow }) {
  const counts = Object.entries(row.counts).filter(([status]) => status !== 'cancelled') as [LabItemStatus, number][]
  return (
    <li className={cn('hover:bg-muted/50', ROW_ACCENT[row.priority])} data-lab-order-id={row.order_id}>
      <Link to={`/lab/orders/${row.order_id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
        <div className="min-w-48 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{row.patient_name}</span>
            <span className="text-sm text-muted-foreground">
              {formatPatientMeta(row.patient_gender, row.patient_age)} · {formatPhone(row.patient_phone)}
            </span>
          </div>
          <div className="text-sm text-muted-foreground">{row.tests.join(', ')}</div>
        </div>
        <div className="text-sm">
          <div className="font-mono text-xs">{row.order_number}</div>
          <div className="text-xs text-muted-foreground">{row.ordering_doctor_name}</div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <LabPriorityBadge priority={row.priority} hideRoutine />
          <LabOrderStatusBadge status={row.status} />
        </div>
        <div className="w-40 text-right text-xs text-muted-foreground">
          <div>
            {formatDate(row.created_at)}, {formatTime(row.created_at)}
          </div>
          <div>{counts.map(([status, n]) => `${n} ${LAB_ITEM_STATUS_LABEL[status].toLowerCase()}`).join(' · ')}</div>
          {row.sample_codes.length > 0 && <div className="font-mono">{row.sample_codes.join(', ')}</div>}
        </div>
      </Link>
    </li>
  )
}
