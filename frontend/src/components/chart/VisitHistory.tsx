import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDownIcon, FileTextIcon, Loader2Icon, MessageSquarePlusIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { VisitDetails } from '@/components/chart/VisitDetails'
import { LabOrderResults } from '@/components/labs/LabOrderResults'
import { usePatientLabResults } from '@/hooks/usePatientLabResults'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { addAddendum, fetchHistory, recordKeys } from '@/lib/records'
import { INGESTION_META } from '@/lib/reports'
import { cn } from '@/lib/utils'
import type { HistoryVisit, LabOrder } from '@/types/api'

const ALL = 'all'

interface Props {
  patientId: string
  /** Expand and scroll to this visit (e.g. from a chatbot citation). */
  focus?: { id: string; token: number } | null
  onOpenReport: (reportId: string) => void
}

export function VisitHistory({ patientId, focus, onOpenReport }: Props) {
  const history = useQuery({
    queryKey: recordKeys.history(patientId),
    queryFn: ({ signal }) => fetchHistory(patientId, signal),
  })
  const labs = usePatientLabResults(patientId)
  const [doctor, setDoctor] = useState(ALL)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  const visits = useMemo(() => history.data ?? [], [history.data])
  const doctors = useMemo(
    () => [...new Map(visits.map((v) => [v.doctor_id, v.doctor_name])).entries()],
    [visits],
  )
  const shown = visits.filter(
    (v) =>
      (doctor === ALL || v.doctor_id === doctor) &&
      (!from || v.visit_date >= from) &&
      (!to || v.visit_date <= to),
  )

  if (history.isPending) return <Skeleton className="h-64" />
  if (history.isError) return <p className="text-sm text-destructive">{history.error.message}</p>
  if (visits.length === 0) {
    return <p className="rounded-xl border bg-background p-6 text-sm text-muted-foreground">No previous visits.</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label className="text-xs">Doctor</Label>
          <Select value={doctor} onValueChange={setDoctor}>
            <SelectTrigger className="w-48" aria-label="Filter by doctor">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All doctors</SelectItem>
              {doctors.map(([id, name]) => (
                <SelectItem key={id} value={id}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="history-from" className="text-xs">From</Label>
          <Input id="history-from" type="date" className="w-40" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="history-to" className="text-xs">To</Label>
          <Input id="history-to" type="date" className="w-40" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <span className="pb-2 text-sm text-muted-foreground">
          {shown.length} of {visits.length} visits
        </span>
      </div>
      <ol className="space-y-2">
        {shown.map((visit, index) => (
          <VisitCard
            key={visit.consultation_id}
            visit={visit}
            patientId={patientId}
            defaultOpen={index === 0}
            focusToken={focus?.id === visit.consultation_id ? focus.token : null}
            onOpenReport={onOpenReport}
            labOrders={(labs.data ?? []).filter((o) => o.appointment_id === visit.appointment_id)}
          />
        ))}
      </ol>
    </div>
  )
}

function VisitCard({
  visit,
  patientId,
  defaultOpen,
  focusToken,
  onOpenReport,
  labOrders,
}: {
  visit: HistoryVisit
  labOrders: LabOrder[]
  patientId: string
  defaultOpen: boolean
  focusToken: number | null
  onOpenReport: (reportId: string) => void
}) {
  // null = not toggled by the doctor yet; a focused (cited) visit is always shown open.
  const [toggled, setToggled] = useState<boolean | null>(null)
  const focused = focusToken != null
  const open = focused || (toggled ?? defaultOpen)
  const setOpen = (update: (open: boolean) => boolean) => setToggled(update(open))
  const ref = useRef<HTMLLIElement>(null)

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [focused, focusToken])

  return (
    <li
      ref={ref}
      className={cn('rounded-xl border bg-background', focused && 'ring-2 ring-primary')}
      data-consultation-id={visit.consultation_id}
    >
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 p-3 text-left"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="w-28 font-medium tabular-nums">{formatDate(visit.visit_date)}</span>
        <span className="text-sm">
          {visit.doctor_name}
          <span className="text-muted-foreground"> · {visit.doctor_specialization}</span>
        </span>
        <span className="min-w-40 flex-1 truncate text-sm text-muted-foreground">
          {visit.diagnosis ?? visit.chief_complaint ?? 'No diagnosis recorded'}
        </span>
        {visit.addenda.length > 0 && <Badge variant="outline">{visit.addenda.length} addendum</Badge>}
        <ChevronDownIcon className={cn('size-4 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="space-y-3 border-t p-3">
          <VisitDetails visit={visit} />
          {labOrders.length > 0 && (
            <div className="space-y-2 rounded-lg bg-muted/40 p-2" data-visit-labs>
              <p className="text-xs font-medium text-muted-foreground">Lab tests ordered at this visit</p>
              {labOrders.map((order) => (
                <LabOrderResults key={order.id} order={order} onOpenReport={onOpenReport} compact />
              ))}
            </div>
          )}
          {visit.reports.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {visit.reports.map((report) => (
                <Button key={report.id} variant="outline" size="sm" onClick={() => onOpenReport(report.id)}>
                  <FileTextIcon />
                  {report.title}
                  <span className={cn('rounded px-1 text-[10px]', INGESTION_META[report.ingestion_status].className)}>
                    {INGESTION_META[report.ingestion_status].label}
                  </span>
                </Button>
              ))}
            </div>
          )}
          {visit.addenda.length > 0 && (
            <ul className="space-y-1 rounded-lg bg-amber-50 p-2 text-sm dark:bg-amber-500/10">
              {visit.addenda.map((addendum) => (
                <li key={addendum.id}>
                  <span className="text-xs text-muted-foreground">
                    Addendum by {addendum.author_name}, {formatDate(addendum.created_at)}:
                  </span>{' '}
                  <span className="whitespace-pre-wrap">{addendum.text}</span>
                </li>
              ))}
            </ul>
          )}
          <AddendumForm consultationId={visit.consultation_id} patientId={patientId} />
        </div>
      )}
    </li>
  )
}

function AddendumForm({ consultationId, patientId }: { consultationId: string; patientId: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const add = useMutation({
    mutationFn: () => addAddendum(consultationId, text.trim()),
    onSuccess: () => {
      toast.success('Addendum added')
      setText('')
      setOpen(false)
      void queryClient.invalidateQueries({ queryKey: recordKeys.history(patientId) })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not add.'),
  })

  if (!open) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
        <MessageSquarePlusIcon />
        Add addendum
      </Button>
    )
  }
  return (
    <div className="space-y-2">
      <Textarea
        rows={2}
        value={text}
        maxLength={5000}
        placeholder="Correction or later finding (the original record stays unchanged)"
        onChange={(e) => setText(e.target.value)}
        aria-label="Addendum"
      />
      <div className="flex gap-2">
        <Button size="sm" onClick={() => add.mutate()} disabled={!text.trim() || add.isPending}>
          {add.isPending && <Loader2Icon className="animate-spin" />}
          Save addendum
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
