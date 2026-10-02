import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangleIcon, CheckIcon, Loader2Icon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useRealtimeLabAlerts } from '@/hooks/useRealtimeLabs'
import { ApiError } from '@/lib/api'
import { formatTime } from '@/lib/format'
import { LAB_FLAG_LABEL, acknowledgeLabAlert, fetchLabAlerts, labKeys } from '@/lib/labs'
import type { LabAlert } from '@/types/api'

/**
 * Critical lab values for the signed-in doctor, on every doctor screen until acknowledged.
 * New alerts arrive through Realtime (the alert row carries ids only; values come from FastAPI).
 */
export function CriticalAlertBanner() {
  const alerts = useQuery({
    queryKey: labKeys.alerts,
    queryFn: ({ signal }) => fetchLabAlerts(signal),
    refetchInterval: 60_000,
  })
  useRealtimeLabAlerts(() => toast.error('Critical lab value', { description: 'A new critical result needs your attention.' }))

  const open = alerts.data ?? []
  if (open.length === 0) return null
  return (
    <div
      role="alert"
      className="border-b border-red-300 bg-red-50 px-4 py-3 text-red-950 dark:border-red-900 dark:bg-red-950/60 dark:text-red-50"
      data-testid="critical-alerts"
    >
      <div className="mx-auto max-w-[1600px] space-y-2">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <AlertTriangleIcon className="size-4" />
          {open.length === 1 ? 'Critical lab value' : `${open.length} critical lab values`} awaiting acknowledgement
        </p>
        <ul className="space-y-2">
          {open.map((alert) => (
            <AlertRow key={alert.id} alert={alert} />
          ))}
        </ul>
      </div>
    </div>
  )
}

function AlertRow({ alert }: { alert: LabAlert }) {
  const queryClient = useQueryClient()
  const [noting, setNoting] = useState(false)
  const [note, setNote] = useState('')
  const ack = useMutation({
    mutationFn: () => acknowledgeLabAlert(alert.id, note.trim() || null),
    onSuccess: () => toast.success('Critical value acknowledged'),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not acknowledge.'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: labKeys.alerts }),
  })
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm" data-alert-id={alert.id}>
      <span className="font-medium">
        <Link to={`/doctor/patients/${alert.patient_id}`} className="underline-offset-2 hover:underline">
          {alert.patient_name}
        </Link>
      </span>
      <span>
        {alert.parameter_name}{' '}
        <strong className="tabular-nums">
          {alert.value} {alert.unit}
        </strong>{' '}
        ({alert.flag ? LAB_FLAG_LABEL[alert.flag] : 'critical'}
        {alert.range_label ? `, reference ${alert.range_label}` : ''})
      </span>
      <span className="text-xs opacity-80">
        {alert.order_number} · {formatTime(alert.created_at)}
      </span>
      <span className="ml-auto flex items-center gap-2">
        {noting && (
          <Input
            aria-label="Acknowledgement note"
            placeholder="Note (optional)"
            className="h-8 w-56 bg-background text-foreground"
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        )}
        {!noting && (
          <Button size="sm" variant="ghost" className="h-8" onClick={() => setNoting(true)}>
            Add note
          </Button>
        )}
        <Button size="sm" className="h-8" onClick={() => ack.mutate()} disabled={ack.isPending}>
          {ack.isPending ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
          Acknowledge
        </Button>
      </span>
    </li>
  )
}
