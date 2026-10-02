import { useQuery } from '@tanstack/react-query'
import { CalendarIcon, ChevronLeftIcon, ChevronRightIcon, PalmtreeIcon } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { doctorKeys, fetchSlots } from '@/lib/appointments'
import { addDays, clinicDate, clinicDateTime, formatTime, formatWeekdayDate } from '@/lib/format'

export interface SlotChoice {
  startsAt: string
  squeezeIn: boolean
}

interface SlotPickerProps {
  doctorId: string
  date: string
  onDateChange: (date: string) => void
  value: SlotChoice | null
  onChange: (value: SlotChoice | null) => void
}

function toLocalDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y!, m! - 1, d!)
}

function fromLocalDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Pick a free slot for a doctor on a day, or (front desk) squeeze in at any time. */
export function SlotPicker({
  doctorId,
  date,
  onDateChange,
  value,
  onChange,
}: SlotPickerProps) {
  const today = clinicDate()
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [squeezeTime, setSqueezeTime] = useState('')
  const squeezeIn = value?.squeezeIn ?? false

  const slotsQuery = useQuery({
    queryKey: doctorKeys.slots(doctorId, date),
    queryFn: ({ signal }) => fetchSlots(doctorId, date, signal),
    staleTime: 10_000,
  })
  const slots = slotsQuery.data?.slots ?? []
  const changeDate = (next: string) => {
    onChange(null)
    setSqueezeTime('')
    onDateChange(next)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          aria-label="Previous day"
          disabled={date <= today}
          onClick={() => changeDate(addDays(date, -1))}
        >
          <ChevronLeftIcon />
        </Button>
        <Popover open={calendarOpen} onOpenChange={setCalendarOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" className="min-w-44 justify-start font-normal">
              <CalendarIcon />
              {formatWeekdayDate(date)}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="single"
              selected={toLocalDate(date)}
              defaultMonth={toLocalDate(date)}
              disabled={{ before: toLocalDate(today) }}
              onSelect={(d) => {
                if (d) changeDate(fromLocalDate(d))
                setCalendarOpen(false)
              }}
            />
          </PopoverContent>
        </Popover>
        <Button
          variant="outline"
          size="icon"
          aria-label="Next day"
          onClick={() => changeDate(addDays(date, 1))}
        >
          <ChevronRightIcon />
        </Button>
        {date !== today && (
          <Button variant="ghost" size="sm" onClick={() => changeDate(today)}>
            Today
          </Button>
        )}
      </div>

      {!squeezeIn && (
        <div>
          {slotsQuery.isPending ? (
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-5">
              {Array.from({ length: 10 }, (_, i) => (
                <Skeleton key={i} className="h-8" />
              ))}
            </div>
          ) : slotsQuery.isError ? (
            <p className="text-sm text-destructive">{slotsQuery.error.message}</p>
          ) : slotsQuery.data?.on_leave ? (
            <p className="flex items-center gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
              <PalmtreeIcon className="size-4" /> The doctor is on leave this day.
            </p>
          ) : slots.length === 0 ? (
            <p className="rounded-lg bg-muted p-3 text-sm text-muted-foreground">
              No free slots this day. Try another day or squeeze the patient in.
            </p>
          ) : (
            <div
              role="radiogroup"
              aria-label="Free slots"
              className="grid max-h-56 grid-cols-4 gap-2 overflow-y-auto sm:grid-cols-5"
            >
              {slots.map((slot) => {
                const selected = value?.startsAt === slot.starts_at
                return (
                  <Button
                    key={slot.starts_at}
                    role="radio"
                    aria-checked={selected}
                    variant={selected ? 'default' : 'outline'}
                    size="sm"
                    className="tabular-nums"
                    onClick={() => onChange({ startsAt: slot.starts_at, squeezeIn: false })}
                  >
                    {formatTime(slot.starts_at)}
                  </Button>
                )
              })}
            </div>
          )}
        </div>
      )}

      <div className="space-y-2 rounded-lg border p-3">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="squeeze-in" className="font-normal">
            Squeeze in outside the listed slots
          </Label>
          <Switch
            id="squeeze-in"
            checked={squeezeIn}
            onCheckedChange={(checked) => {
              setSqueezeTime('')
              onChange(checked ? { startsAt: '', squeezeIn: true } : null)
            }}
          />
        </div>
        {squeezeIn && (
          <div className="flex items-center gap-2">
            <Input
              type="time"
              aria-label="Squeeze-in time"
              className="w-36"
              value={squeezeTime}
              onChange={(e) => {
                setSqueezeTime(e.target.value)
                onChange({
                  startsAt: e.target.value ? clinicDateTime(date, e.target.value) : '',
                  squeezeIn: true,
                })
              }}
            />
            <p className="text-xs text-muted-foreground">
              Still blocked if it overlaps another appointment.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
