import { useQuery } from '@tanstack/react-query'
import { PalmtreeIcon, PlusIcon, SearchIcon } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { AppointmentTable } from '@/components/appointments/AppointmentTable'
import { InboundReview } from '@/components/appointments/InboundReview'
import { useNewAppointment } from '@/components/appointments/newAppointmentContext'
import { PendingConfirmation } from '@/components/appointments/PendingConfirmation'
import { SummaryCards } from '@/components/appointments/SummaryCards'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useHotkeys } from '@/hooks/useHotkeys'
import { useNow } from '@/hooks/useNow'
import {
  appointmentKeys,
  doctorKeys,
  fetchDayAppointments,
  fetchDoctors,
} from '@/lib/appointments'
import { clinicDate, formatWeekdayDate } from '@/lib/format'
import { fetchLabSummary, labKeys } from '@/lib/labs'
import type { Appointment, AppointmentStatus } from '@/types/api'

const VIEWS = {
  active: {
    label: 'Active',
    statuses: ['pending_confirmation', 'scheduled', 'checked_in', 'in_consultation'],
  },
  waiting: { label: 'Waiting', statuses: ['checked_in'] },
  with_doctor: { label: 'With doctor', statuses: ['in_consultation'] },
  completed: { label: 'Completed', statuses: ['completed'] },
  closed: { label: 'No-show / cancelled', statuses: ['no_show', 'cancelled'] },
  all: { label: 'All', statuses: null },
} satisfies Record<string, { label: string; statuses: AppointmentStatus[] | null }>

type View = keyof typeof VIEWS

function inView(view: View, a: Appointment): boolean {
  const statuses: AppointmentStatus[] | null = VIEWS[view].statuses
  return statuses === null || statuses.includes(a.status)
}

function matchesSearch(a: Appointment, search: string): boolean {
  const q = search.trim().toLowerCase()
  if (!q) return true
  const digits = q.replace(/\D/g, '')
  return (
    a.patient.full_name.toLowerCase().includes(q) ||
    (digits.length >= 3 && (a.patient.phone ?? '').includes(digits)) ||
    (/^\d+$/.test(q) && a.token_number === Number(q))
  )
}

export function TodayPage() {
  const today = clinicDate(useNow())
  // Lab test counts per appointment. Reception has no lab Realtime (the order row carries the
  // doctor's clinical note), so poll; appointment changes refresh it too.
  const labSummary = useQuery({
    queryKey: labKeys.summary(today),
    queryFn: ({ signal }) => fetchLabSummary(today, signal),
    refetchInterval: 30_000,
  })
  const labCounts = useMemo(
    () => new Map((labSummary.data ?? []).map((c) => [c.appointment_id, c])),
    [labSummary.data],
  )
  const [view, setView] = useState<View>('active')
  const [doctorId, setDoctorId] = useState('all')
  const [search, setSearch] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const { openNewAppointment } = useNewAppointment()
  useHotkeys({ '/': () => searchRef.current?.focus() })

  const dayQuery = useQuery({
    queryKey: appointmentKeys.day(today),
    queryFn: ({ signal }) => fetchDayAppointments(today, signal),
    // Realtime keeps this fresh; polling is only a safety net if the socket drops.
    refetchInterval: 60_000,
  })
  const doctorsQuery = useQuery({
    queryKey: doctorKeys.all,
    queryFn: ({ signal }) => fetchDoctors(signal),
    staleTime: 5 * 60_000,
  })

  const forDoctor = useMemo(
    () =>
      (dayQuery.data ?? []).filter((a) => doctorId === 'all' || a.doctor.id === doctorId),
    [dayQuery.data, doctorId],
  )
  const visible = useMemo(
    () => forDoctor.filter((a) => inView(view, a) && matchesSearch(a, search)),
    [forDoctor, view, search],
  )
  const onLeave = doctorsQuery.data?.filter((d) => d.on_leave_today) ?? []

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Today</h1>
          <p className="text-sm text-muted-foreground">{formatWeekdayDate(today)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {onLeave.length > 0 && (
            <p className="flex items-center gap-1.5 text-sm text-amber-800 dark:text-amber-300">
              <PalmtreeIcon className="size-4" />
              On leave today: {onLeave.map((d) => d.full_name).join(', ')}
            </p>
          )}
          <Button onClick={() => openNewAppointment()}>
            <PlusIcon /> New appointment
            <kbd className="ml-1 hidden rounded bg-primary-foreground/20 px-1 text-[10px] sm:inline">N</kbd>
          </Button>
        </div>
      </div>

      <SummaryCards appointments={dayQuery.isPending ? undefined : forDoctor} />
      <InboundReview />
      <PendingConfirmation today={today} />

      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Tabs
            value={view}
            onValueChange={(v) => setView(v as View)}
            className="max-w-full overflow-x-auto"
          >
            <TabsList className="w-max">
              {(Object.keys(VIEWS) as View[]).map((key) => (
                <TabsTrigger key={key} value={key} className="gap-1.5">
                  {VIEWS[key].label}
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {forDoctor.filter((a) => inView(key, a)).length}
                  </span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className="ml-auto flex w-full flex-wrap gap-2 sm:w-auto">
            <Select value={doctorId} onValueChange={setDoctorId}>
              <SelectTrigger className="w-full sm:w-48" aria-label="Doctor">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All doctors</SelectItem>
                {doctorsQuery.data?.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.full_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="relative w-full sm:w-64">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                ref={searchRef}
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && setSearch('')}
                placeholder="Name, phone or token"
                aria-label="Search today's appointments"
                className="pl-8"
              />
              <kbd className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 rounded border bg-muted px-1.5 text-[10px] text-muted-foreground sm:block">
                /
              </kbd>
            </div>
          </div>
        </div>

        {dayQuery.isError ? (
          <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            {dayQuery.error.message}
          </p>
        ) : (
          <AppointmentTable
            appointments={visible}
            labCounts={labCounts}
            loading={dayQuery.isPending}
            empty={
              search
                ? 'No appointments match your search.'
                : view === 'active'
                  ? 'No one is waiting. New bookings appear here instantly.'
                  : 'Nothing here yet.'
            }
          />
        )}
      </div>
    </div>
  )
}
