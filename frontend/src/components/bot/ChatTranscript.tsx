import { MicIcon } from 'lucide-react'

import { formatTime, formatWeekdayDate, clinicDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { BotTranscriptMessage } from '@/types/api'

/** A WhatsApp-style transcript: patient on the left, bot / reception on the right. */
export function ChatTranscript({ messages }: { messages: BotTranscriptMessage[] }) {
  if (messages.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">No messages yet.</p>
  }
  return (
    <ol className="flex flex-col gap-2" data-testid="chat-transcript">
      {messages.map((m, index) => {
        const day = clinicDate(m.created_at)
        const previous = messages[index - 1]
        const showDay = previous === undefined || day !== clinicDate(previous.created_at)
        const inbound = m.direction === 'inbound'
        const voice = m.type === 'audio' || m.transcript !== null
        const text = m.transcript ?? m.text ?? (voice ? '(voice note)' : `(${m.type})`)
        return (
          <li key={m.id} className="flex flex-col" data-message-direction={m.direction}>
            {showDay && (
              <span className="my-2 self-center rounded-full bg-muted px-3 py-0.5 text-xs text-muted-foreground">
                {day === clinicDate() ? 'Today' : formatWeekdayDate(m.created_at)}
              </span>
            )}
            <div
              className={cn(
                'max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap shadow-xs',
                inbound
                  ? 'self-start rounded-bl-sm bg-background ring-1 ring-border'
                  : 'self-end rounded-br-sm bg-emerald-50 ring-1 ring-emerald-200 dark:bg-emerald-950/40 dark:ring-emerald-900',
              )}
            >
              {voice && inbound && (
                <span className="mb-1 flex items-center gap-1 text-xs text-muted-foreground">
                  <MicIcon className="size-3" /> Voice note (transcript)
                </span>
              )}
              {text}
              <span className="mt-1 block text-right text-[11px] text-muted-foreground">
                {formatTime(m.created_at)}
                {!inbound && m.status !== 'sent' ? ` · ${m.status}` : ''}
              </span>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
