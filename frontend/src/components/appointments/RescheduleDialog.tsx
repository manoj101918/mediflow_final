import { Loader2Icon } from 'lucide-react'
import { useState } from 'react'

import { SlotPicker, type SlotChoice } from '@/components/appointments/SlotPicker'
import { useAppointmentMutation, who } from '@/components/appointments/useAppointmentMutation'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { rescheduleAppointment } from '@/lib/appointments'
import { clinicDate, formatTime, formatWeekdayDate } from '@/lib/format'
import type { Appointment } from '@/types/api'

interface RescheduleDialogProps {
  appointment: Appointment
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function RescheduleDialog({ appointment, open, onOpenChange }: RescheduleDialogProps) {
  const today = clinicDate()
  const [date, setDate] = useState(() =>
    appointment.appointment_date < today ? today : appointment.appointment_date,
  )
  const [choice, setChoice] = useState<SlotChoice | null>(null)

  const mutation = useAppointmentMutation(
    (c: SlotChoice) => rescheduleAppointment(appointment.id, c.startsAt, c.squeezeIn),
    (a) => `${who(a)} moved to ${formatWeekdayDate(a.starts_at)}, ${formatTime(a.starts_at)}`,
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Reschedule {who(appointment)}</DialogTitle>
          <DialogDescription>
            {appointment.doctor.full_name} · currently {formatWeekdayDate(appointment.starts_at)}{' '}
            at {formatTime(appointment.starts_at)}
          </DialogDescription>
        </DialogHeader>
        <SlotPicker
          doctorId={appointment.doctor.id}
          date={date}
          onDateChange={setDate}
          value={choice}
          onChange={setChoice}
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            disabled={!choice?.startsAt || mutation.isPending}
            onClick={() =>
              choice && mutation.mutate(choice, { onSuccess: () => onOpenChange(false) })
            }
          >
            {mutation.isPending && <Loader2Icon className="animate-spin" />}
            Move appointment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
