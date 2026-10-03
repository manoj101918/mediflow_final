import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, Loader2Icon, SirenIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api'
import {
  INBOX_POLL_MS,
  acknowledgeBotAlert,
  botKeys,
  conversationTitle,
  fetchBotAlerts,
} from '@/lib/bot'
import { formatTime } from '@/lib/format'
import type { BotAlert } from '@/types/api'

/**
 * Emergencies reported to the bot, on every reception screen until acknowledged. The patient
 * was already told to call 108/112; reception should call them back too. Polled (bot tables
 * are backend-only, no Realtime).
 */
export function EmergencyBanner() {
  const alerts = useQuery({
    queryKey: botKeys.alerts,
    queryFn: ({ signal }) => fetchBotAlerts(signal),
    refetchInterval: INBOX_POLL_MS,
  })
  const emergencies = (alerts.data ?? []).filter((a) => a.kind === 'emergency')

  // A toast for each emergency that appears while the screen is open.
  const seen = useRef<Set<string> | null>(null)
  useEffect(() => {
    if (!alerts.data) return
    const current = alerts.data.filter((a) => a.kind === 'emergency')
    if (seen.current !== null) {
      for (const alert of current) {
        if (!seen.current.has(alert.id)) {
          toast.error('Emergency reported to the bot', { description: conversationTitle(alert) })
        }
      }
    }
    seen.current = new Set(current.map((a) => a.id))
  }, [alerts.data])

  if (emergencies.length === 0) return null
  return (
    <div
      role="alert"
      className="border-b border-red-300 bg-red-50 px-4 py-3 text-red-950 dark:border-red-900 dark:bg-red-950/60 dark:text-red-50"
      data-testid="bot-emergencies"
    >
      <div className="mx-auto max-w-[1600px] space-y-2">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <SirenIcon className="size-4" />
          {emergencies.length === 1 ? 'Emergency' : `${emergencies.length} emergencies`} reported to
          the bot: the patient was told to call 108 / 112. Please call them.
        </p>
        <ul className="space-y-1.5">
          {emergencies.map((alert) => (
            <EmergencyRow key={alert.id} alert={alert} />
          ))}
        </ul>
      </div>
    </div>
  )
}

function EmergencyRow({ alert }: { alert: BotAlert }) {
  const queryClient = useQueryClient()
  const ack = useMutation({
    mutationFn: () => acknowledgeBotAlert(alert.id),
    onSuccess: () => toast.success('Emergency acknowledged'),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not acknowledge.'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: botKeys.all }),
  })
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" data-bot-alert-id={alert.id}>
      <Link to={`/reception/inbox?c=${alert.conversation_id}`} className="font-medium underline-offset-2 hover:underline">
        {conversationTitle(alert)}
      </Link>
      <a href={`tel:${alert.phone}`} className="tabular-nums underline-offset-2 hover:underline">
        {alert.phone}
      </a>
      {alert.excerpt && <span className="italic opacity-90">“{alert.excerpt}”</span>}
      <span className="text-xs opacity-80">{formatTime(alert.created_at)}</span>
      <Button
        size="sm"
        variant="outline"
        className="ml-auto border-red-300 bg-background"
        disabled={ack.isPending}
        onClick={() => ack.mutate()}
      >
        {ack.isPending ? <Loader2Icon className="animate-spin" /> : <CheckIcon />}
        Called / handled
      </Button>
    </li>
  )
}
