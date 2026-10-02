import {
  CalendarClockIcon,
  CheckIcon,
  FileUpIcon,
  Loader2Icon,
  LogInIcon,
  MoreHorizontalIcon,
  PlayIcon,
  UserXIcon,
  XIcon,
} from 'lucide-react'
import { useState } from 'react'

import { ReasonDialog } from '@/components/appointments/ReasonDialog'
import { ReportUploadDialog } from '@/components/chart/ReportUploadDialog'
import { RescheduleDialog } from '@/components/appointments/RescheduleDialog'
import { useAppointmentMutation, who } from '@/components/appointments/useAppointmentMutation'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  ALLOWED_TRANSITIONS,
  RESCHEDULABLE,
  approveAppointment,
  changeStatus,
  rejectAppointment,
} from '@/lib/appointments'
import type { Appointment, AppointmentStatus } from '@/types/api'

const DONE_MESSAGE: Partial<Record<AppointmentStatus, string>> = {
  checked_in: 'checked in',
  in_consultation: 'is with the doctor',
  completed: 'visit completed',
  no_show: 'marked as no-show',
  cancelled: 'cancelled',
}

/** The single most likely next step for the front desk, shown as the row's main button. */
const PRIMARY: Partial<Record<AppointmentStatus, { to: AppointmentStatus; label: string }>> = {
  scheduled: { to: 'checked_in', label: 'Check in' },
  checked_in: { to: 'in_consultation', label: 'Start' },
  in_consultation: { to: 'completed', label: 'Complete' },
}

const PRIMARY_ICON = { checked_in: LogInIcon, in_consultation: PlayIcon, completed: CheckIcon }

type DialogKind = 'cancel' | 'reject' | 'reschedule' | 'upload' | null

export function RowActions({ appointment }: { appointment: Appointment }) {
  const [dialog, setDialog] = useState<DialogKind>(null)
  const { id, status } = appointment
  const allowed = ALLOWED_TRANSITIONS[status]

  const statusMutation = useAppointmentMutation(
    ({ to, note }: { to: AppointmentStatus; note?: string }) => changeStatus(id, to, note),
    (a) => `${who(a)} ${DONE_MESSAGE[a.status] ?? 'updated'}`,
  )
  const approve = useAppointmentMutation(
    () => approveAppointment(id),
    (a) => `${who(a)} confirmed`,
  )
  const reject = useAppointmentMutation(
    (reason: string) => rejectAppointment(id, reason),
    (a) => `${who(a)} rejected`,
  )
  const busy = statusMutation.isPending || approve.isPending || reject.isPending

  const primary = PRIMARY[status]
  const PrimaryIcon = primary ? PRIMARY_ICON[primary.to as keyof typeof PRIMARY_ICON] : null
  const pending = status === 'pending_confirmation'
  const canReschedule = RESCHEDULABLE.includes(status)
  const canNoShow = allowed.includes('no_show')
  const canCancel = allowed.includes('cancelled') && !pending

  return (
    <div className="flex items-center justify-end gap-1">
      {pending ? (
        <Button size="sm" disabled={busy} onClick={() => approve.mutate(undefined)}>
          {approve.isPending ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
          Approve
        </Button>
      ) : primary ? (
        <Button
          size="sm"
          variant={primary.to === 'checked_in' ? 'default' : 'secondary'}
          disabled={busy}
          onClick={() => statusMutation.mutate({ to: primary.to })}
        >
          {statusMutation.isPending ? (
            <Loader2Icon className="animate-spin" />
          ) : (
            PrimaryIcon && <PrimaryIcon />
          )}
          {primary.label}
        </Button>
      ) : null}

      {/* Uploading a report is always possible, so the menu is always there. */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" disabled={busy} aria-label="More actions">
            <MoreHorizontalIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem onSelect={() => setDialog('upload')}>
            <FileUpIcon /> Upload report
          </DropdownMenuItem>
          {(canReschedule || canNoShow) && <DropdownMenuSeparator />}
          {canReschedule && (
            <DropdownMenuItem onSelect={() => setDialog('reschedule')}>
              <CalendarClockIcon /> Reschedule
            </DropdownMenuItem>
          )}
          {canNoShow && (
            <DropdownMenuItem onSelect={() => statusMutation.mutate({ to: 'no_show' })}>
              <UserXIcon /> Mark no-show
            </DropdownMenuItem>
          )}
          {(canCancel || pending) && <DropdownMenuSeparator />}
          {canCancel && (
            <DropdownMenuItem variant="destructive" onSelect={() => setDialog('cancel')}>
              <XIcon /> Cancel appointment
            </DropdownMenuItem>
          )}
          {pending && (
            <DropdownMenuItem variant="destructive" onSelect={() => setDialog('reject')}>
              <XIcon /> Reject booking
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {dialog === 'upload' && (
        <ReportUploadDialog
          patientId={appointment.patient.id}
          patientName={appointment.patient.full_name}
          open
          onOpenChange={() => setDialog(null)}
        />
      )}
      {dialog === 'reschedule' && (
        <RescheduleDialog appointment={appointment} open onOpenChange={() => setDialog(null)} />
      )}
      <ReasonDialog
        open={dialog === 'cancel'}
        onOpenChange={(open) => !open && setDialog(null)}
        title={`Cancel ${who(appointment)}?`}
        description="The slot becomes free again. The token number is not reused."
        confirmLabel="Cancel appointment"
        pending={statusMutation.isPending}
        onConfirm={(note) =>
          statusMutation.mutate({ to: 'cancelled', note }, { onSuccess: () => setDialog(null) })
        }
      />
      <ReasonDialog
        open={dialog === 'reject'}
        onOpenChange={(open) => !open && setDialog(null)}
        title={`Reject ${who(appointment)}?`}
        description="The bot booking is declined and its slot is released."
        confirmLabel="Reject booking"
        pending={reject.isPending}
        onConfirm={(reason) => reject.mutate(reason, { onSuccess: () => setDialog(null) })}
      />
    </div>
  )
}
