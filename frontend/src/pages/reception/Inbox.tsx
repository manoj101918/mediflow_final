import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BotIcon,
  Loader2Icon,
  MessageSquareTextIcon,
  PhoneIcon,
  PlayIcon,
  SendIcon,
  SirenIcon,
} from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { ChatTranscript } from '@/components/bot/ChatTranscript'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import {
  HANDOFF_REASON_LABEL,
  INBOX_POLL_MS,
  LANGUAGE_LABEL,
  botKeys,
  conversationTitle,
  fetchConversation,
  fetchConversations,
  replyToConversation,
  resumeBot,
} from '@/lib/bot'
import { formatTime, formatWeekdayDate, clinicDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { BotConversationSummary } from '@/types/api'

function when(value: string | null): string {
  if (!value) return ''
  return clinicDate(value) === clinicDate() ? formatTime(value) : formatWeekdayDate(value)
}

/** Conversations the bot handed to reception: emergencies first, then newest. */
export function InboxPage() {
  const [params, setParams] = useSearchParams()
  const [showAll, setShowAll] = useState(false)
  const list = useQuery({
    queryKey: botKeys.conversations(!showAll),
    queryFn: ({ signal }) => fetchConversations(!showAll, signal),
    refetchInterval: INBOX_POLL_MS,
  })
  const conversations = list.data ?? []
  const selected = params.get('c') ?? conversations[0]?.id ?? null

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Bot inbox</h1>
          <p className="text-sm text-muted-foreground">
            Patients who asked for reception, emergencies, and chats the bot couldn't follow.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Show waiting only' : 'Show recent chats'}
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(260px,340px)_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">{showAll ? 'Recent chats' : `Waiting (${conversations.length})`}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {list.isPending ? (
              <Loader2Icon className="mx-auto my-6 size-5 animate-spin text-muted-foreground" />
            ) : conversations.length === 0 ? (
              <p className="px-4 pb-4 text-sm text-muted-foreground">Nobody is waiting for reception.</p>
            ) : (
              <ul className="divide-y" data-testid="bot-inbox">
                {conversations.map((c) => (
                  <ConversationRow
                    key={c.id}
                    conversation={c}
                    active={c.id === selected}
                    onSelect={() => setParams({ c: c.id })}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        {selected ? (
          <ConversationPanel key={selected} id={selected} />
        ) : (
          <Card className="grid min-h-60 place-items-center text-sm text-muted-foreground">
            <span className="flex items-center gap-2">
              <MessageSquareTextIcon className="size-4" /> Select a conversation
            </span>
          </Card>
        )}
      </div>
    </div>
  )
}

function ConversationRow({
  conversation: c,
  active,
  onSelect,
}: {
  conversation: BotConversationSummary
  active: boolean
  onSelect: () => void
}) {
  return (
    <li data-conversation-id={c.id} data-handoff-status={c.handoff_status}>
      <button
        type="button"
        onClick={onSelect}
        className={cn('flex w-full flex-col gap-0.5 px-4 py-3 text-left hover:bg-muted/60', active && 'bg-muted')}
      >
        <span className="flex items-center gap-2">
          {c.emergency && <SirenIcon className="size-4 text-red-600" />}
          <span className="font-medium">{conversationTitle(c)}</span>
          <span className="ml-auto text-xs text-muted-foreground">{when(c.handoff_at ?? c.last_inbound_at)}</span>
        </span>
        <span className="flex items-center gap-2 text-xs text-muted-foreground">
          {c.handoff_reason && (
            <span className={cn(c.emergency && 'font-medium text-red-700 dark:text-red-300')}>
              {HANDOFF_REASON_LABEL[c.handoff_reason] ?? c.handoff_reason}
            </span>
          )}
          {c.channel !== 'whatsapp' && <span>· Voice</span>}
        </span>
        {c.last_message && <span className="line-clamp-1 text-sm text-muted-foreground">{c.last_message}</span>}
      </button>
    </li>
  )
}

function ConversationPanel({ id }: { id: string }) {
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const detail = useQuery({
    queryKey: botKeys.conversation(id),
    queryFn: ({ signal }) => fetchConversation(id, signal),
    refetchInterval: INBOX_POLL_MS,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: botKeys.all })
  const send = useMutation({
    mutationFn: () => replyToConversation(id, draft.trim()),
    onSuccess: (result) => {
      setDraft('')
      toast.success(result.status === 'sent' ? 'Message sent' : 'Message queued')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not send.'),
    onSettled: refresh,
  })
  const resume = useMutation({
    mutationFn: () => resumeBot(id),
    onSuccess: () => toast.success('The bot will answer this patient again'),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not resume the bot.'),
    onSettled: refresh,
  })

  if (detail.isPending) {
    return (
      <Card className="grid min-h-60 place-items-center">
        <Loader2Icon className="size-5 animate-spin text-muted-foreground" />
      </Card>
    )
  }
  if (!detail.data) {
    return <Card className="p-6 text-sm text-muted-foreground">This conversation could not be loaded.</Card>
  }
  const c = detail.data
  const canWrite = c.window_open && !c.opted_out
  return (
    <Card data-conversation-detail={c.id}>
      <CardHeader className="gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">{conversationTitle(c)}</CardTitle>
          {c.emergency && <Badge variant="destructive">Emergency</Badge>}
          {c.handoff_status === 'open' ? (
            <Badge variant="outline">Bot paused</Badge>
          ) : (
            <Badge variant="secondary" className="gap-1">
              <BotIcon className="size-3" /> Bot active
            </Badge>
          )}
          {c.handoff_status === 'open' && (
            <Button size="sm" variant="outline" className="ml-auto" disabled={resume.isPending} onClick={() => resume.mutate()}>
              {resume.isPending ? <Loader2Icon className="animate-spin" /> : <PlayIcon />}
              Resume bot
            </Button>
          )}
        </div>
        <CardDescription className="flex flex-wrap items-center gap-x-3">
          <a href={`tel:${c.phone}`} className="flex items-center gap-1 tabular-nums underline-offset-2 hover:underline">
            <PhoneIcon className="size-3" /> {c.phone}
          </a>
          <span>{c.channel === 'whatsapp' ? 'WhatsApp' : 'Voice simulator'}</span>
          {c.language && <span>{LANGUAGE_LABEL[c.language]}</span>}
          {c.handoff_reason && <span>{HANDOFF_REASON_LABEL[c.handoff_reason]}</span>}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="max-h-[55svh] overflow-y-auto rounded-lg bg-muted/40 p-3">
          <ChatTranscript messages={c.messages} />
        </div>
        {canWrite ? (
          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (draft.trim()) send.mutate()
            }}
          >
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder="Reply as reception (no medical advice over chat)"
              aria-label="Reply"
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-emerald-700 dark:text-emerald-300" data-window="open">
                {c.channel === 'whatsapp' ? '24-hour window open: replies are free.' : 'Simulator conversation.'}
              </span>
              <Button type="submit" disabled={!draft.trim() || send.isPending}>
                {send.isPending ? <Loader2Icon className="animate-spin" /> : <SendIcon />}
                Send
              </Button>
            </div>
          </form>
        ) : (
          <div
            className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-500/10 dark:text-amber-100"
            data-window="closed"
          >
            <PhoneIcon className="size-4" />
            {c.opted_out
              ? 'The patient opted out of messages.'
              : "Window closed: WhatsApp's free 24-hour reply window has ended."}{' '}
            <a href={`tel:${c.phone}`} className="font-medium underline">
              Call the patient
            </a>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
