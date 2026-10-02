import { useQuery } from '@tanstack/react-query'
import { ClockIcon, PalmtreeIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { doctorKeys, fetchDoctors } from '@/lib/appointments'
import { WEEKDAYS, clinicDate, clinicWeekday, formatClock, formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Doctor, Schedule } from '@/types/api'

function shifts(schedules: Schedule[], weekday: number): string {
  const day = schedules.filter((s) => s.weekday === weekday)
  return day.length
    ? day.map((s) => `${formatClock(s.start_time)} – ${formatClock(s.end_time)}`).join(', ')
    : ''
}

export function DoctorsPage() {
  const query = useQuery({
    queryKey: doctorKeys.all,
    queryFn: ({ signal }) => fetchDoctors(signal),
    staleTime: 60_000,
  })
  const today = clinicDate()
  const weekday = clinicWeekday(today)

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Doctors</h1>
        <p className="text-sm text-muted-foreground">Weekly hours and upcoming leave. Changes are made by the admin.</p>
      </div>
      {query.isPending ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      ) : query.isError ? (
        <p className="text-sm text-destructive">{query.error.message}</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {query.data.map((d) => (
            <DoctorCard key={d.id} doctor={d} weekday={weekday} />
          ))}
        </div>
      )}
    </div>
  )
}

function DoctorCard({ doctor: d, weekday }: { doctor: Doctor; weekday: number }) {
  const todayHours = shifts(d.schedules, weekday)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {d.full_name}
          {d.on_leave_today ? (
            <Badge className="bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200">
              <PalmtreeIcon /> On leave today
            </Badge>
          ) : todayHours ? (
            <Badge className="bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200">
              <ClockIcon /> In today
            </Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              Off today
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          {d.specialization} · ₹{d.consultation_fee} · {d.default_slot_minutes}-minute slots
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <table className="w-full text-sm">
          <tbody>
            {WEEKDAYS.map((name, i) => {
              const hours = shifts(d.schedules, i)
              return (
                <tr key={name} className={cn(i === weekday && 'font-medium')}>
                  <td className="w-28 py-0.5 pr-2 text-muted-foreground">
                    {name}
                    {i === weekday && <span className="ml-1 text-xs text-primary">(today)</span>}
                  </td>
                  <td className={cn('py-0.5', !hours && 'text-muted-foreground')}>{hours || 'Off'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {d.upcoming_leaves.length > 0 && (
          <div className="space-y-1 rounded-lg bg-muted/60 p-3 text-sm">
            <div className="text-xs font-medium text-muted-foreground">Upcoming leave</div>
            {d.upcoming_leaves.map((leave) => (
              <div key={leave.id}>
                {formatDate(leave.leave_date)}
                {leave.reason && <span className="text-muted-foreground"> · {leave.reason}</span>}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
