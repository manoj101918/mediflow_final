import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircleIcon,
  FileTextIcon,
  FlaskConicalIcon,
  Loader2Icon,
  MessageSquarePlusIcon,
  SendHorizontalIcon,
  ShieldCheckIcon,
  SparklesIcon,
  StethoscopeIcon,
  UserRoundIcon,
} from 'lucide-react'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'

import { AnswerText } from '@/components/chat/AnswerText'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { SUGGESTED_QUESTIONS, chatKeys, fetchChatMessages, fetchChatSessions, streamChat } from '@/lib/chat'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ChatMessage, Citation } from '@/types/api'

interface UiMessage {
  key: string
  id?: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  error?: string | null
  pending?: boolean
}

const NEW = 'new'

function fromServer(m: ChatMessage): UiMessage {
  return {
    key: m.id,
    id: m.id,
    role: m.role,
    content: m.content,
    citations: m.citations,
    error: m.error_code ? m.content : null,
  }
}

let localKey = 0
const nextKey = () => `local-${++localKey}`

export function ChatPanel({
  patientId,
  onCite,
}: {
  patientId: string
  onCite: (citation: Citation) => void
}) {
  const queryClient = useQueryClient()
  const sessions = useQuery({
    queryKey: chatKeys.sessions(patientId),
    queryFn: ({ signal }) => fetchChatSessions(patientId, signal),
  })
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadingSession, setLoadingSession] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const update = (key: string, patch: (m: UiMessage) => UiMessage) =>
    setMessages((all) => all.map((m) => (m.key === key ? patch(m) : m)))

  const openSession = async (id: string) => {
    abort.current?.abort()
    if (id === NEW) {
      setSessionId(null)
      setMessages([])
      return
    }
    setSessionId(id)
    setLoadingSession(true)
    try {
      const loaded = await queryClient.fetchQuery({
        queryKey: chatKeys.messages(id),
        queryFn: ({ signal }) => fetchChatMessages(id, signal),
        staleTime: 0,
      })
      setMessages(loaded.map(fromServer))
    } finally {
      setLoadingSession(false)
    }
  }

  const send = async (text: string) => {
    const question = text.trim()
    if (!question || busy) return
    setDraft('')
    setBusy(true)
    const answerKey = nextKey()
    setMessages((all) => [
      ...all,
      { key: nextKey(), role: 'user', content: question, citations: [] },
      { key: answerKey, role: 'assistant', content: '', citations: [], pending: true },
    ])
    const controller = new AbortController()
    abort.current = controller
    try {
      for await (const event of streamChat(patientId, { message: question, session_id: sessionId }, controller.signal)) {
        if (event.event === 'token') {
          update(answerKey, (m) => ({ ...m, content: m.content + event.data.text }))
        } else if (event.event === 'citations') {
          update(answerKey, (m) => ({ ...m, citations: event.data.citations }))
        } else if (event.event === 'done') {
          setSessionId(event.data.session_id)
          update(answerKey, (m) => ({ ...m, id: event.data.message_id, pending: false }))
        } else if (event.event === 'error') {
          setSessionId(event.data.session_id)
          update(answerKey, (m) => ({ ...m, pending: false, error: event.data.message }))
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      const message = error instanceof ApiError ? error.message : 'Could not reach the assistant.'
      update(answerKey, (m) => ({ ...m, pending: false, error: message }))
    } finally {
      update(answerKey, (m) => ({ ...m, pending: false }))
      setBusy(false)
      void queryClient.invalidateQueries({ queryKey: chatKeys.sessions(patientId) })
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send(draft)
    }
  }

  return (
    <section
      className="flex h-[calc(100svh-7rem)] min-h-[32rem] flex-col rounded-xl border bg-background"
      aria-label="Ask about this patient"
      data-testid="chat-panel"
    >
      <header className="flex items-center gap-2 border-b p-3">
        <SparklesIcon className="size-4 text-primary" />
        <h2 className="flex-1 text-sm font-semibold">Ask about this patient</h2>
        {(sessions.data?.length ?? 0) > 0 && (
          <Select value={sessionId ?? NEW} onValueChange={(v) => void openSession(v)} disabled={busy}>
            <SelectTrigger size="sm" className="max-w-40" aria-label="Past conversations">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value={NEW}>New conversation</SelectItem>
              {sessions.data!.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button
          variant="ghost"
          size="icon"
          aria-label="New conversation"
          title="New conversation"
          disabled={busy}
          onClick={() => void openSession(NEW)}
        >
          <MessageSquarePlusIcon />
        </Button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3" aria-live="polite">
        {loadingSession ? (
          <Loader2Icon className="mx-auto mt-8 animate-spin text-muted-foreground" />
        ) : messages.length === 0 ? (
          <div className="space-y-3 pt-4">
            <p className="text-sm text-muted-foreground">
              Ask about previous visits, medicines, allergies or reports. Every answer cites the
              record it comes from.
            </p>
            <div className="flex flex-col gap-2">
              {SUGGESTED_QUESTIONS.map((q) => (
                <Button
                  key={q}
                  variant="outline"
                  className="h-auto justify-start whitespace-normal py-2 text-left"
                  onClick={() => void send(q)}
                  disabled={busy}
                >
                  {q}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m) => <Bubble key={m.key} message={m} onCite={onCite} />)
        )}
        <div ref={bottom} />
      </div>

      <footer className="space-y-2 border-t p-3">
        <div className="flex items-end gap-2">
          <Textarea
            rows={2}
            value={draft}
            maxLength={2000}
            placeholder="e.g. What is the HbA1c trend?"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Question"
            className="min-h-0 resize-none"
          />
          <Button size="icon" onClick={() => void send(draft)} disabled={busy || !draft.trim()} aria-label="Send">
            {busy ? <Loader2Icon className="animate-spin" /> : <SendHorizontalIcon />}
          </Button>
        </div>
        <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <ShieldCheckIcon className="size-3" />
          Answers come only from this patient&apos;s records.
        </p>
      </footer>
    </section>
  )
}

function Bubble({ message: m, onCite }: { message: UiMessage; onCite: (c: Citation) => void }) {
  if (m.role === 'user') {
    return (
      <div className="flex justify-end gap-2" data-chat-role="user">
        <p className="max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{m.content}</p>
        <UserRoundIcon className="mt-1 size-4 shrink-0 text-muted-foreground" />
      </div>
    )
  }
  return (
    <div className="flex gap-2" data-chat-role="assistant" data-chat-message-id={m.id ?? ''}>
      <StethoscopeIcon className="mt-1 size-4 shrink-0 text-primary" />
      <div className="min-w-0 flex-1 space-y-2 rounded-lg bg-muted/50 px-3 py-2">
        {m.content ? (
          <AnswerText text={m.content} citations={m.citations} onCite={onCite} />
        ) : m.pending ? (
          <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2Icon className="size-4 animate-spin" />
            Reading the records…
          </span>
        ) : null}
        {m.error && (
          <p className="flex items-start gap-1.5 text-sm text-destructive" role="alert">
            <AlertCircleIcon className="mt-0.5 size-4 shrink-0" />
            {m.error}
          </p>
        )}
        {m.citations.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t pt-2" aria-label="Sources">
            {m.citations.map((c) => (
              <button
                key={c.n}
                type="button"
                onClick={() => onCite(c)}
                className={cn(
                  'inline-flex max-w-full items-center gap-1 rounded-md border bg-background px-1.5 py-0.5',
                  'text-[11px] hover:bg-muted',
                )}
                data-citation={c.n}
                data-citation-type={c.source_type}
                title={c.label}
              >
                <span className="font-semibold text-primary">{c.n}</span>
                {c.source_type === 'report' && <FileTextIcon className="size-3" />}
                {c.source_type === 'lab_result' && <FlaskConicalIcon className="size-3" />}
                <span className="truncate">{c.label}</span>
                {c.date && c.source_type !== 'summary' && (
                  <span className="text-muted-foreground">· {formatDate(c.date)}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
