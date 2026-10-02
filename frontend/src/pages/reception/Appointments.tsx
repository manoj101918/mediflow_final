import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { PlusIcon, SearchIcon } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'

import { AppointmentTable } from '@/components/appointments/AppointmentTable'
import { useNewAppointment } from '@/components/appointments/newAppointmentContext'
import { Pager } from '@/components/common/Pager'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { api } from '@/lib/api'
import {
  SOURCE_META,
  STATUS_META,
  STATUS_ORDER,
  appointmentKeys,
  doctorKeys,
  fetchDoctors,
} from '@/lib/appointments'
import { addDays, clinicDate, formatDate } from '@/lib/format'
import type { Appointment, AppointmentSource, Page } from '@/types/api'

const PAGE_SIZE = 50
const MAX_RANGE_DAYS = 62
const ALL = 'all'

type Preset = 'today' | 'tomorrow' | 'next7' | 'last7' | 'custom'
const PRESETS: { id: Exclude<Preset, 'custom'>; label: string; range: (t: string) => [string, string] }[] = [
  { id: 'today', label: 'Today', range: (t) => [t, t] },
  { id: 'tomorrow', label: 'Tomorrow', range: (t) => [addDays(t, 1), addDays(t, 1)] },
  { id: 'next7', label: 'Next 7 days', range: (t) => [t, addDays(t, 6)] },
  { id: 'last7', label: 'Last 7 days', range: (t) => [addDays(t, -6), t] },
]

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000)
}

export function AppointmentsPage() {
  const today = clinicDate()
  const { openNewAppointment } = useNewAppointment()
  const [params, setParams] = useSearchParams()
  const from = params.get('from') ?? today
  const to = params.get('to') ?? addDays(today, 6)
  const doctor = params.get('doctor') ?? ALL
  const status = params.get('status') ?? ALL
  const source = params.get('source') ?? ALL
  const page = Number(params.get('page') ?? '1') || 1
  const [search, setSearch] = useState(params.get('q') ?? '')
  const q = useDebouncedValue(search.trim(), 300)

  const update = (changes: Record<string, string | null>, resetPage = true) =>
    setParams(
      (p) => {
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === ALL || value === '') p.delete(key)
          else p.set(key, value)
        }
        if (resetPage) p.delete('page')
        return p
      },
      { replace: true },
    )

  const rangeError =
    to < from
      ? 'The end date is before the start date.'
      : daysBetween(from, to) > MAX_RANGE_DAYS
        ? `Choose at most ${MAX_RANGE_DAYS} days.`
        : null
  const activePreset: Preset =
    PRESETS.find((p) => {
      const [f, t] = p.range(today)
      return f === from && t === to
    })?.id ?? 'custom'

  const doctorsQuery = useQuery({
    queryKey: doctorKeys.all,
    queryFn: ({ signal }) => fetchDoctors(signal),
    staleTime: 5 * 60_000,
  })
  const filters = { date_from: from, date_to: to, doctor_id: doctor, status, source, q, page }
  const query = useQuery({
    queryKey: [...appointmentKeys.all, 'list', filters],
    queryFn: ({ signal }) =>
      api<Page<Appointment>>('/appointments', {
        query: {
          date_from: from,
          date_to: to,
          doctor_id: doctor === ALL ? undefined : doctor,
          status: status === ALL ? undefined : status,
          source: source === ALL ? undefined : source,
          q: q || undefined,
          page,
          page_size: PAGE_SIZE,
        },
        signal,
      }),
    enabled: rangeError === null,
    placeholderData: keepPreviousData,
  })

  return (
    <div className="mx-auto max-w-7xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Appointments</h1>
          <p className="text-sm text-muted-foreground">
            {from === to ? formatDate(from) : `${formatDate(from)} – ${formatDate(to)}`}
          </p>
        </div>
        <Button onClick={() => openNewAppointment()}>
          <PlusIcon /> New appointment
        </Button>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-wrap gap-1" role="group" aria-label="Date range">
          {PRESETS.map((p) => (
            <Button
              key={p.id}
              size="sm"
              variant={activePreset === p.id ? 'default' : 'outline'}
              onClick={() => {
                const [f, t] = p.range(today)
                update({ from: f, to: t })
              }}
            >
              {p.label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 text-sm">
          <Input
            type="date"
            aria-label="From"
            className="h-8 w-38"
            value={from}
            onChange={(e) => e.target.value && update({ from: e.target.value })}
          />
          <span className="text-muted-foreground">to</span>
          <Input
            type="date"
            aria-label="To"
            className="h-8 w-38"
            value={to}
            onChange={(e) => e.target.value && update({ to: e.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <FilterSelect
          label="Doctor"
          value={doctor}
          onChange={(v) => update({ doctor: v })}
          options={[[ALL, 'All doctors'], ...(doctorsQuery.data ?? []).map((d) => [d.id, d.full_name] as [string, string])]}
        />
        <FilterSelect
          label="Status"
          value={status}
          onChange={(v) => update({ status: v })}
          options={[[ALL, 'Any status'], ...STATUS_ORDER.map((s) => [s, STATUS_META[s].label] as [string, string])]}
        />
        <FilterSelect
          label="Source"
          value={source}
          onChange={(v) => update({ source: v })}
          options={[
            [ALL, 'Any source'],
            ...(Object.keys(SOURCE_META) as AppointmentSource[]).map((s) => [s, SOURCE_META[s].label] as [string, string]),
          ]}
        />
        <div className="relative w-full sm:w-64">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              update({ q: e.target.value })
            }}
            placeholder="Patient name, phone or token"
            aria-label="Search appointments"
            className="pl-8"
          />
        </div>
      </div>

      {rangeError ? (
        <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{rangeError}</p>
      ) : query.isError ? (
        <p className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{query.error.message}</p>
      ) : (
        <>
          <AppointmentTable
            appointments={query.data?.items ?? []}
            loading={query.isPending}
            showDate={from !== to}
            empty="No appointments match these filters."
          />
          {query.data && (
            <Pager
              page={page}
              pageSize={PAGE_SIZE}
              total={query.data.total}
              onPageChange={(next) => update({ page: String(next) }, false)}
            />
          )}
        </>
      )}
    </div>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: [string, string][]
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-full sm:w-44" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map(([v, text]) => (
          <SelectItem key={v} value={v}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
