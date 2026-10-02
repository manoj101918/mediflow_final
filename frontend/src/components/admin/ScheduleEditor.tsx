import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CopyIcon, Loader2Icon, PlusIcon, XIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { adminKeys, replaceSchedules } from '@/lib/admin'
import { ApiError } from '@/lib/api'
import { WEEKDAYS } from '@/lib/format'
import type { Doctor } from '@/types/api'

interface Shift {
  start: string
  end: string
}
type Week = Shift[][]

function fromDoctor(doctor: Doctor): Week {
  const week: Week = WEEKDAYS.map(() => [])
  for (const s of doctor.schedules) {
    week[s.weekday]!.push({ start: s.start_time.slice(0, 5), end: s.end_time.slice(0, 5) })
  }
  return week.map((day) => day.sort((a, b) => a.start.localeCompare(b.start)))
}

/** Problem with a day's shifts, or null. Mirrors the API's validation. */
function dayError(shifts: Shift[]): string | null {
  if (shifts.some((s) => !s.start || !s.end)) return 'Fill in both times.'
  if (shifts.some((s) => s.start >= s.end)) return 'A shift must end after it starts.'
  const sorted = [...shifts].sort((a, b) => a.start.localeCompare(b.start))
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i]!.start < sorted[i - 1]!.end) return 'Shifts overlap.'
  }
  return null
}

/** Weekly working hours: any number of shifts per weekday (e.g. morning + evening). */
export function ScheduleEditor({ doctor }: { doctor: Doctor }) {
  const queryClient = useQueryClient()
  const initial = useMemo(() => fromDoctor(doctor), [doctor])
  const [week, setWeek] = useState<Week>(initial)
  const errors = week.map(dayError)
  const dirty = JSON.stringify(week) !== JSON.stringify(initial)

  const save = useMutation({
    mutationFn: () =>
      replaceSchedules(
        doctor.id,
        week.flatMap((shifts, weekday) =>
          shifts.map((s) => ({ weekday, start_time: s.start, end_time: s.end })),
        ),
      ),
    onSuccess: () => toast.success(`Saved weekly hours for ${doctor.full_name}`),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not save the schedule.'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: adminKeys.doctors.slice(0, 1) }),
  })

  const update = (weekday: number, fn: (shifts: Shift[]) => Shift[]) =>
    setWeek((w) => w.map((shifts, i) => (i === weekday ? fn(shifts) : shifts)))

  const copyMondayToWeekdays = () =>
    setWeek((w) => w.map((shifts, i) => (i >= 1 && i <= 5 ? w[0]!.map((s) => ({ ...s })) : shifts)))

  return (
    <div className="space-y-3">
      <div className="divide-y rounded-lg border">
        {WEEKDAYS.map((name, weekday) => {
          const shifts = week[weekday]!
          return (
            <div key={name} className="flex flex-wrap items-start gap-x-4 gap-y-2 p-3">
              <div className="w-24 pt-1.5 text-sm font-medium">{name}</div>
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                {shifts.length === 0 && <span className="pt-1.5 text-sm text-muted-foreground">Off</span>}
                {shifts.map((shift, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Input
                      type="time"
                      aria-label={`${name} shift ${i + 1} start`}
                      className="h-8 w-32"
                      value={shift.start}
                      onChange={(e) =>
                        update(weekday, (s) => s.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))
                      }
                    />
                    <span className="text-muted-foreground">to</span>
                    <Input
                      type="time"
                      aria-label={`${name} shift ${i + 1} end`}
                      className="h-8 w-32"
                      value={shift.end}
                      onChange={(e) =>
                        update(weekday, (s) => s.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))
                      }
                    />
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Remove ${name} shift ${i + 1}`}
                      onClick={() => update(weekday, (s) => s.filter((_, j) => j !== i))}
                    >
                      <XIcon />
                    </Button>
                  </div>
                ))}
                {errors[weekday] && <p className="text-xs text-destructive">{errors[weekday]}</p>}
              </div>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Add ${name} shift`}
                onClick={() =>
                  update(weekday, (s) => [
                    ...s,
                    s.length ? { start: s[s.length - 1]!.end, end: '' } : { start: '09:00', end: '13:00' },
                  ])
                }
              >
                <PlusIcon /> Shift
              </Button>
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap justify-between gap-2">
        <Button variant="outline" size="sm" onClick={copyMondayToWeekdays}>
          <CopyIcon /> Copy Monday to Tue–Sat
        </Button>
        <div className="flex gap-2">
          {dirty && (
            <Button variant="ghost" size="sm" onClick={() => setWeek(initial)}>
              Discard changes
            </Button>
          )}
          <Button size="sm" disabled={!dirty || errors.some(Boolean) || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2Icon className="animate-spin" />}
            Save weekly hours
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Changing hours does not move existing appointments; new bookings follow the new hours.
      </p>
    </div>
  )
}
