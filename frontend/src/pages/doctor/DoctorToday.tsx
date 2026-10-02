import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, ClipboardListIcon, Loader2Icon, PlayIcon, UserRoundIcon } from 'lucide-react'
import { useCallback, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { useAuth } from '@/auth/context'
import { StatusBadge } from '@/components/appointments/Badges'
import { useAppointmentMutation } from '@/components/appointments/useAppointmentMutation'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useNow } from '@/hooks/useNow'
import { type AppointmentChange, useRealtimeAppointments } from '@/hooks/useRealtimeAppointments'
import { ApiError } from '@/lib/api'
import { appointmentKeys, changeStatus, fetchDayAppointments } from '@/lib/appointments'
import { completeVisit, fetchVisit } from '@/lib/records'
import { clinicDate, formatPatientMeta, formatTime, formatWeekdayDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Appointment, AppointmentStatus } from '@/types/api'

const byToken = (a: Appointment, b: Appointment) => a.token_number - b.token_number
const byTime = (a: Appointment, b: Appointment) => a.starts_at.localeCompare(b.starts_at) || byToken(a, b)

function greeting(now: Date): string {
  const hour = Number(new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' }).format(now))
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
}

export function DoctorTodayPage() {
  const { me } = useAuth()
  const now = useNow()
  const today = clinicDate(now)
  const queryClient = useQueryClient()

  const announce = useCallback(
    (change: AppointmentChange) => {
      if (change.eventType !== 'UPDATE' || change.new.status !== 'checked_in') return
      const list = queryClient.getQueryData<Appointment[]>(appointmentKeys.day(today))
      const name = list?.find((a) => a.id === change.new.id)?.patient.full_name
      toast.info(`Token #${change.new.token_number} has arrived`, { description: name })
    },
    [queryClient, today],
  )
  useRealtimeAppointments({ onChange: announce })

  const query = useQuery({
    queryKey: appointmentKeys.day(today),
    queryFn: ({ signal }) => fetchDayAppointments(today, signal),
    enabled: Boolean(me?.doctor_id),
    refetchInterval: 60_000,
  })

  const navigate = useNavigate()
  const chartPath = (a: Appointment) => `/doctor/patients/${a.patient.id}?appointment=${a.id}`

  const move = useAppointmentMutation(
    ({ id, to }: { id: string; to: AppointmentStatus }) => changeStatus(id, to),
    (a) => `Consultation started with ${a.patient.full_name}`,
  )
  const start = (a: Appointment) =>
    move.mutate({ id: a.id, to: 'in_consultation' }, { onSuccess: () => navigate(chartPath(a)) })

  // Completing finalizes the visit notes; warn first when none were written.
  const [confirmEmpty, setConfirmEmpty] = useState<Appointment | null>(null)
  const complete = useMutation({
    mutationFn: (a: Appointment) => completeVisit(a.id),
    onSuccess: (_, a) => {
      setConfirmEmpty(null)
      toast.success(`Finished with ${a.patient.full_name}`)
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Something went wrong.'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: appointmentKeys.all }),
  })
  const requestComplete = async (a: Appointment) => {
    try {
      const visit = await fetchVisit(a.id)
      if (visit.consultation) complete.mutate(a)
      else setConfirmEmpty(a)
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Something went wrong.')
    }
  }
  const busyId = move.isPending
    ? move.variables?.id
    : complete.isPending
      ? complete.variables?.id
      : undefined

  if (!me?.doctor_id) {
    return (
      <div className="mx-auto max-w-2xl rounded-xl border bg-background p-6 text-center">
        <h1 className="text-lg font-semibold">Your login is not linked to a doctor</h1>
        <p className="text-sm text-muted-foreground">Ask the clinic admin to link your account to your doctor profile.</p>
      </div>
    )
  }

  const all = query.data ?? []
  const current = all.filter((a) => a.status === 'in_consultation').sort(byToken)
  const waiting = all.filter((a) => a.status === 'checked_in').sort(byToken)
  const later = all.filter((a) => a.status === 'scheduled' || a.status === 'pending_confirmation').sort(byTime)
  const finished = all.filter((a) => ['completed', 'no_show', 'cancelled'].includes(a.status)).sort(byTime)
  const seen = all.filter((a) => a.status === 'completed').length

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {greeting(now)}, {me.full_name}
          </h1>
          <p className="text-sm text-muted-foreground">{formatWeekdayDate(today)}</p>
        </div>
        <div className="flex gap-4 text-sm">
          <Stat label="Waiting" value={waiting.length} tone="text-sky-700 dark:text-sky-300" />
          <Stat label="Later today" value={later.length} />
          <Stat label="Seen" value={seen} tone="text-emerald-700 dark:text-emerald-300" />
        </div>
      </div>

      {query.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-48" />
        </div>
      ) : query.isError ? (
        <p className="text-sm text-destructive">{query.error.message}</p>
      ) : (
        <>
          <Card className={cn(current.length > 0 && 'ring-2 ring-violet-300 dark:ring-violet-700')}>
            <CardHeader>
              <CardTitle>With you now</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {current.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {waiting.length ? 'Start the next patient from the waiting list.' : 'No one is with you.'}
                </p>
              ) : (
                current.map((a) => (
                  <PatientRow key={a.id} appointment={a} large chartPath={chartPath(a)}>
                    <Button asChild size="lg" variant="outline">
                      <Link to={chartPath(a)}>
                        <ClipboardListIcon />
                        Open chart
                      </Link>
                    </Button>
                    <Button
                      size="lg"
                      disabled={busyId === a.id}
                      onClick={() => void requestComplete(a)}
                    >
                      {busyId === a.id ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
                      Complete
                    </Button>
                  </PatientRow>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Waiting ({waiting.length})</CardTitle>
              <CardDescription>Checked in at the front desk, in token order.</CardDescription>
            </CardHeader>
            <CardContent>
              {waiting.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nobody is waiting. Arrivals appear here instantly.</p>
              ) : (
                <ul className="divide-y">
                  {waiting.map((a, i) => (
                    <li key={a.id} className="py-2 first:pt-0 last:pb-0">
                      <PatientRow appointment={a} chartPath={chartPath(a)}>
                        <Button
                          variant={i === 0 ? 'default' : 'outline'}
                          disabled={busyId === a.id}
                          onClick={() => start(a)}
                        >
                          {busyId === a.id ? <Loader2Icon className="animate-spin" /> : <PlayIcon />}
                          {i === 0 ? 'Call next' : 'Start'}
                        </Button>
                      </PatientRow>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Later today ({later.length})</CardTitle>
              <CardDescription>Booked, not arrived yet.</CardDescription>
            </CardHeader>
            <CardContent>
              {later.length === 0 ? (
                <p className="text-sm text-muted-foreground">No more bookings today.</p>
              ) : (
                <ul className="divide-y text-sm">
                  {later.map((a) => (
                    <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2">
                      <span className="w-20 tabular-nums text-muted-foreground">{formatTime(a.starts_at)}</span>
                      <span className="w-10 font-semibold tabular-nums">#{a.token_number}</span>
                      <span className="min-w-40 flex-1">
                        {a.patient.full_name}
                        <span className="text-muted-foreground"> · {a.reason_for_visit ?? 'No reason given'}</span>
                      </span>
                      <StatusBadge status={a.status} />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {finished.length > 0 && (
            <details className="rounded-xl border bg-background p-4">
              <summary className="cursor-pointer text-sm font-medium">Finished ({finished.length})</summary>
              <ul className="mt-3 divide-y text-sm">
                {finished.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-muted-foreground">
                    <span className="w-20 tabular-nums">{formatTime(a.starts_at)}</span>
                    <span className="w-10 tabular-nums">#{a.token_number}</span>
                    <span className="flex-1 text-foreground">{a.patient.full_name}</span>
                    <StatusBadge status={a.status} />
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
      <ConfirmDialog
        open={confirmEmpty != null}
        onOpenChange={(open) => !open && setConfirmEmpty(null)}
        title="Complete without notes?"
        description={`No consultation notes or prescription were recorded for ${confirmEmpty?.patient.full_name ?? 'this patient'}. Complete the visit anyway?`}
        confirmLabel="Complete without notes"
        pending={complete.isPending}
        onConfirm={() => confirmEmpty && complete.mutate(confirmEmpty)}
      />
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="text-right">
      <div className={cn('text-2xl font-semibold tabular-nums', tone)}>{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  )
}

function PatientRow({
  appointment: a,
  large,
  chartPath,
  children,
}: {
  appointment: Appointment
  large?: boolean
  /** When set, the patient's name opens their chart. */
  chartPath?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-4" data-appointment-id={a.id} data-status={a.status}>
      <div
        className={cn(
          'flex shrink-0 items-center justify-center rounded-lg bg-muted font-semibold tabular-nums',
          large ? 'size-14 text-2xl' : 'size-10 text-lg',
        )}
        aria-label={`Token ${a.token_number}`}
      >
        {a.token_number}
      </div>
      <div className="min-w-0 flex-1">
        <div className={cn('flex items-center gap-2 font-medium', large && 'text-lg')}>
          <UserRoundIcon className="size-4 text-muted-foreground" />
          {chartPath ? (
            <Link to={chartPath} className="hover:underline" data-open-chart>
              {a.patient.full_name}
            </Link>
          ) : (
            a.patient.full_name
          )}
          <span className="text-sm font-normal text-muted-foreground">
            {formatPatientMeta(a.patient.gender, a.patient.age)}
          </span>
        </div>
        <div className="text-sm text-muted-foreground">
          {formatTime(a.starts_at)} · {a.reason_for_visit ?? 'No reason given'}
        </div>
        {a.notes && <div className="mt-1 text-xs text-amber-800 dark:text-amber-300">Note: {a.notes}</div>}
      </div>
      {children}
    </div>
  )
}
