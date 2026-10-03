import { useQuery } from '@tanstack/react-query'
import { InboxIcon } from 'lucide-react'

import { SourceBadge } from '@/components/appointments/Badges'
import { RowActions } from '@/components/appointments/RowActions'
import { ViewChatButton } from '@/components/bot/ViewChatButton'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { api } from '@/lib/api'
import { appointmentKeys } from '@/lib/appointments'
import { addDays, formatTime, formatWeekdayDate } from '@/lib/format'
import type { Appointment, Page } from '@/types/api'

const LOOKAHEAD_DAYS = 30

/** Bot bookings (WhatsApp / voice) for today onward that the front desk must confirm. */
export function PendingConfirmation({ today }: { today: string }) {
  const query = useQuery({
    queryKey: [...appointmentKeys.all, 'pending', today],
    queryFn: ({ signal }) =>
      api<Page<Appointment>>('/appointments', {
        query: {
          status: 'pending_confirmation',
          date_from: today,
          date_to: addDays(today, LOOKAHEAD_DAYS),
          page_size: 50,
        },
        signal,
      }),
  })
  const items = query.data?.items ?? []
  if (items.length === 0) return null

  return (
    <Card className="border-amber-300 bg-amber-50/60 ring-amber-200 dark:border-amber-800 dark:bg-amber-500/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <InboxIcon className="size-4 text-amber-700 dark:text-amber-300" />
          Waiting for confirmation ({query.data?.total})
        </CardTitle>
        <CardDescription>
          Bookings from WhatsApp and the voice bot hold their slot until you approve or reject them.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-lg border bg-background">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3" data-pending-appointment-id={a.id}>
              <div className="min-w-40 flex-1">
                <div className="font-medium">{a.patient.full_name}</div>
                <div className="text-xs text-muted-foreground">
                  {a.reason_for_visit ?? 'No reason given'}
                </div>
              </div>
              <div className="text-sm">
                <div className="tabular-nums">
                  {a.appointment_date === today ? 'Today' : formatWeekdayDate(a.starts_at)},{' '}
                  {formatTime(a.starts_at)}
                </div>
                <div className="text-xs text-muted-foreground">{a.doctor.full_name}</div>
              </div>
              <div className="flex flex-col items-start gap-0.5">
                <SourceBadge source={a.source} />
                <ViewChatButton appointment={a} />
              </div>
              <RowActions appointment={a} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
