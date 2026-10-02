import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlusIcon, CheckIcon, Loader2Icon, MessageSquareWarningIcon } from 'lucide-react'
import { toast } from 'sonner'

import { SourceBadge } from '@/components/appointments/Badges'
import { useNewAppointment } from '@/components/appointments/newAppointmentContext'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ApiError } from '@/lib/api'
import { formatPhone, formatTime, formatWeekdayDate } from '@/lib/format'
import { dismissInboundRequest, fetchInboundRequests, inboundKeys, inboundReason } from '@/lib/inbound'

/**
 * Bot requests that could not be booked automatically (taken slot, no doctor given, …).
 * The front desk books them by hand or marks them handled after calling back.
 */
export function InboundReview() {
  const queryClient = useQueryClient()
  const { openNewAppointment } = useNewAppointment()
  const query = useQuery({
    queryKey: inboundKeys.list('needs_review'),
    queryFn: ({ signal }) => fetchInboundRequests('needs_review', signal),
    // Requests that book nothing produce no realtime event, so poll.
    refetchInterval: 30_000,
  })
  const dismiss = useMutation({
    mutationFn: dismissInboundRequest,
    onSuccess: (r) => toast.success(`Marked ${r.parsed_patient_name ?? 'request'} as handled`),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong.'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: inboundKeys.list('needs_review') }),
  })

  const items = query.data ?? []
  if (items.length === 0) return null

  return (
    <Card className="border-rose-300 bg-rose-50/50 ring-rose-200 dark:border-rose-900 dark:bg-rose-500/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquareWarningIcon className="size-4 text-rose-700 dark:text-rose-300" />
          Bot requests to handle ({items.length})
        </CardTitle>
        <CardDescription>
          These could not be booked automatically. Book them yourself or call the patient back, then mark them handled.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-lg border bg-background">
          {items.map((r) => (
            <li key={r.id} data-inbound-id={r.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3">
              <div className="min-w-44 flex-1">
                <div className="font-medium">{r.parsed_patient_name ?? 'Unknown caller'}</div>
                <div className="text-xs text-muted-foreground tabular-nums">{formatPhone(r.caller_phone)}</div>
              </div>
              <div className="min-w-48 flex-1 text-sm">
                <div>
                  {r.requested_doctor_name ?? 'Any doctor'}
                  {r.requested_time && (
                    <span className="text-muted-foreground">
                      {' '}
                      · {formatWeekdayDate(r.requested_time)}, {formatTime(r.requested_time)}
                    </span>
                  )}
                </div>
                <div className="text-xs text-rose-800 dark:text-rose-300">{inboundReason(r.error)}</div>
              </div>
              <SourceBadge source={r.channel} />
              <div className="flex gap-1">
                <Button
                  size="sm"
                  onClick={() => openNewAppointment({ search: r.caller_phone?.replace(/^\+91/, '') ?? '' })}
                >
                  <CalendarPlusIcon /> Book
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={dismiss.isPending && dismiss.variables === r.id}
                  onClick={() => dismiss.mutate(r.id)}
                >
                  {dismiss.isPending && dismiss.variables === r.id ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
                  Mark handled
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
