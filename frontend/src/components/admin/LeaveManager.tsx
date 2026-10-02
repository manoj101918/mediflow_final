import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2Icon, PalmtreeIcon, Trash2Icon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { addLeave, deleteLeave } from '@/lib/admin'
import { ApiError } from '@/lib/api'
import { clinicDate, formatWeekdayDate } from '@/lib/format'
import type { Doctor } from '@/types/api'

export function LeaveManager({ doctor }: { doctor: Doctor }) {
  const queryClient = useQueryClient()
  const today = clinicDate()
  const [date, setDate] = useState('')
  const [reason, setReason] = useState('')
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['doctors'] })
  const onError = (e: Error) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong.')

  const add = useMutation({
    mutationFn: () => addLeave(doctor.id, date, reason.trim() || null),
    onSuccess: (leave) => {
      setDate('')
      setReason('')
      if (leave.affected_appointments > 0) {
        toast.warning(`Leave added for ${formatWeekdayDate(leave.leave_date)}`, {
          description: `${leave.affected_appointments} appointment(s) are already booked that day. Ask the front desk to reschedule them.`,
          duration: 10_000,
        })
      } else {
        toast.success(`Leave added for ${formatWeekdayDate(leave.leave_date)}`)
      }
    },
    onError,
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (leaveId: string) => deleteLeave(leaveId),
    onSuccess: () => toast.success('Leave removed'),
    onError,
    onSettled: refresh,
  })

  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (date) add.mutate()
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="leave-date">Date</Label>
          <Input id="leave-date" type="date" min={today} value={date} onChange={(e) => setDate(e.target.value)} className="w-40" />
        </div>
        <div className="min-w-48 flex-1 space-y-1.5">
          <Label htmlFor="leave-reason">Reason (optional)</Label>
          <Input id="leave-reason" value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} placeholder="Conference, personal…" />
        </div>
        <Button type="submit" disabled={!date || add.isPending}>
          {add.isPending ? <Loader2Icon className="animate-spin" /> : <PalmtreeIcon />}
          Add leave
        </Button>
      </form>

      {doctor.upcoming_leaves.length === 0 ? (
        <p className="text-sm text-muted-foreground">No leave in the next 60 days.</p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {doctor.upcoming_leaves.map((leave) => (
            <li key={leave.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
              <span>
                {formatWeekdayDate(leave.leave_date)}
                {leave.reason && <span className="text-muted-foreground"> · {leave.reason}</span>}
              </span>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`Remove leave on ${leave.leave_date}`}
                disabled={remove.isPending && remove.variables === leave.id}
                onClick={() => remove.mutate(leave.id)}
              >
                <Trash2Icon />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
