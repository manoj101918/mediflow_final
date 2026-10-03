import { toast } from 'sonner'

import type { BotNotification } from '@/types/api'

/**
 * After approving or rejecting a bot booking, tell reception whether the patient was
 * messaged. Outside WhatsApp's free 24-hour window nothing is sent: reception has to call.
 */
export function showNotificationToast(notification: BotNotification | null | undefined) {
  if (!notification) return
  const { status, phone, channel } = notification
  const where = channel === 'whatsapp' ? 'WhatsApp' : 'voice simulator'
  switch (status) {
    case 'queued':
      toast.info(`Patient notified on ${where}.`)
      return
    case 'window_closed':
      toast.warning(`Window closed: call the patient (${phone}).`, { duration: 15_000 })
      return
    case 'opted_out':
      toast.warning(`Patient opted out of messages: call ${phone}.`, { duration: 15_000 })
      return
    case 'limit':
      toast.warning(`Free WhatsApp messages used up this month: call ${phone}.`, {
        duration: 15_000,
      })
      return
    default:
      toast.warning(`Patient not messaged: call ${phone}.`, { duration: 15_000 })
  }
}
