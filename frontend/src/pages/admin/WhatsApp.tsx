import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  CircleSlashIcon,
  CopyIcon,
  Loader2Icon,
  RotateCcwIcon,
  SaveIcon,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api'
import { LANGUAGE_LABEL, botKeys, fetchBotStatus, fetchKeywords, saveKeywords } from '@/lib/bot'
import { formatTime, formatWeekdayDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { BotUsage, KeywordKind, KeywordList } from '@/types/api'

const KIND_LABEL: Record<KeywordKind, { title: string; help: string }> = {
  emergency: {
    title: 'Emergency',
    help: 'Any of these words anywhere in a message: the patient is told to call 108 / 112 and reception gets a red alert.',
  },
  stop: { title: 'Opt-out (STOP)', help: 'The whole message must be one of these: the patient is unsubscribed on every channel.' },
  start: { title: 'Opt-in (START)', help: 'The whole message must be one of these: an opted-out patient is subscribed again.' },
}

export function WhatsAppPage() {
  const status = useQuery({
    queryKey: botKeys.status,
    queryFn: ({ signal }) => fetchBotStatus(signal),
    refetchInterval: 30_000,
  })
  const s = status.data
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">WhatsApp booking bot</h1>
        <p className="text-sm text-muted-foreground">
          Direct Meta Cloud API. Only free replies inside WhatsApp's 24-hour window are sent; paid templates are
          {s?.whatsapp.paid_templates_allowed ? ' enabled.' : ' switched off.'}
        </p>
      </div>
      {status.isPending ? (
        <Loader2Icon className="mx-auto size-5 animate-spin text-muted-foreground" />
      ) : !s ? (
        <p className="text-sm text-destructive">Could not load the bot status.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                {s.whatsapp.connected ? (
                  <CheckCircle2Icon className="size-4 text-emerald-600" />
                ) : (
                  <CircleSlashIcon className="size-4 text-muted-foreground" />
                )}
                Connection
              </CardTitle>
              <CardDescription>
                {!s.whatsapp.configured
                  ? 'Not configured: set the WHATSAPP_* values in backend/.env (see the README).'
                  : s.whatsapp.connected
                    ? `Connected${s.whatsapp.fake ? ' (fake sender)' : ''}`
                    : `Not reachable: ${s.whatsapp.error ?? 'unknown error'}`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm" data-testid="whatsapp-status">
              <Row label="Business number">
                {s.whatsapp.display_phone_number ?? '—'}
                {s.whatsapp.verified_name ? ` · ${s.whatsapp.verified_name}` : ''}
              </Row>
              <Row label="Webhook URL">
                {s.whatsapp.webhook_url ? (
                  <span className="flex items-center gap-1">
                    <code className="truncate text-xs">{s.whatsapp.webhook_url}</code>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-6"
                      aria-label="Copy webhook URL"
                      onClick={() => {
                        void navigator.clipboard.writeText(s.whatsapp.webhook_url ?? '')
                        toast.success('Copied')
                      }}
                    >
                      <CopyIcon className="size-3" />
                    </Button>
                  </span>
                ) : (
                  'Set PUBLIC_BASE_URL (your tunnel URL)'
                )}
              </Row>
              <Row label="Webhook last seen">
                {s.whatsapp.webhook_last_seen_at
                  ? `${formatWeekdayDate(s.whatsapp.webhook_last_seen_at)}, ${formatTime(s.whatsapp.webhook_last_seen_at)}`
                  : 'Never'}
              </Row>
              <Row label="Bot clinic">{s.clinic_configured ? 'This clinic' : 'INBOUND_CLINIC_ID is another clinic'}</Row>
              <Row label="Understanding">{s.llm_enabled ? 'Groq LLM (free tier) + rules' : 'Rules only (free)'}</Row>
              <Row label="Speech">
                STT {s.stt_provider} · TTS {s.tts_provider}
              </Row>
            </CardContent>
          </Card>
          <UsageCard usage={s.usage} />
        </div>
      )}
      <KeywordEditor />
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0">{children}</span>
    </div>
  )
}

function UsageCard({ usage }: { usage: BotUsage }) {
  const percent = usage.limit ? Math.min(100, Math.round((usage.sent / usage.limit) * 100)) : 100
  const reserveAt = usage.limit ? (usage.reserve_from / usage.limit) * 100 : 100
  const month = new Date(`${usage.month}T00:00:00Z`).toLocaleString('en-IN', { month: 'long', year: 'numeric', timeZone: 'UTC' })
  return (
    <Card className={cn(usage.warn && 'border-amber-300 dark:border-amber-800')} data-testid="usage-meter">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {usage.warn && <AlertTriangleIcon className="size-4 text-amber-600" />}
          Free messages this month
        </CardTitle>
        <CardDescription>
          Meta gives each business number {usage.limit.toLocaleString('en-IN')} free service messages a month ({month}).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="text-2xl font-semibold tabular-nums" data-usage-sent={usage.sent}>
          {usage.sent.toLocaleString('en-IN')} <span className="text-base font-normal text-muted-foreground">/ {usage.limit.toLocaleString('en-IN')}</span>
        </div>
        <div className="relative h-3 overflow-hidden rounded-full bg-muted" role="meter" aria-valuenow={usage.sent} aria-valuemin={0} aria-valuemax={usage.limit} aria-label="Free messages used">
          <div
            className={cn('h-full rounded-full', usage.exhausted ? 'bg-red-600' : usage.warn ? 'bg-amber-500' : 'bg-emerald-600')}
            style={{ width: `${percent}%` }}
          />
          <div className="absolute inset-y-0 w-0.5 bg-foreground/50" style={{ left: `${reserveAt}%` }} title="Reserve for essential messages" />
        </div>
        <p className="text-muted-foreground">
          {usage.exhausted
            ? 'Used up: nothing more is sent until next month. Reception must call patients.'
            : usage.sent >= usage.reserve_from
              ? 'Only essential messages now (confirmations, emergencies, opt-out, handoff).'
              : usage.warn
                ? 'Over 80% used. Menus stop at the reserve line; essential messages continue.'
                : `Menus stop at ${usage.reserve_from}; the rest is kept for essential messages.`}
        </p>
      </CardContent>
    </Card>
  )
}

function KeywordEditor() {
  const lists = useQuery({ queryKey: botKeys.keywords, queryFn: ({ signal }) => fetchKeywords(signal) })
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Keyword lists</CardTitle>
        <CardDescription>All languages are checked whatever language the patient chose (people mix languages).</CardDescription>
      </CardHeader>
      <CardContent>
        {lists.isPending ? (
          <Loader2Icon className="mx-auto size-5 animate-spin text-muted-foreground" />
        ) : (
          <Tabs defaultValue="emergency">
            <TabsList>
              {(Object.keys(KIND_LABEL) as KeywordKind[]).map((kind) => (
                <TabsTrigger key={kind} value={kind}>
                  {KIND_LABEL[kind].title}
                </TabsTrigger>
              ))}
            </TabsList>
            {(Object.keys(KIND_LABEL) as KeywordKind[]).map((kind) => (
              <TabsContent key={kind} value={kind} className="space-y-3 pt-2">
                <p className="text-sm text-muted-foreground">{KIND_LABEL[kind].help}</p>
                <div className="grid gap-3 md:grid-cols-3">
                  {(lists.data ?? [])
                    .filter((l) => l.kind === kind)
                    .map((list) => (
                      <KeywordBox key={`${list.kind}-${list.language}-${list.words.join('|')}`} list={list} />
                    ))}
                </div>
              </TabsContent>
            ))}
          </Tabs>
        )}
      </CardContent>
    </Card>
  )
}

function KeywordBox({ list }: { list: KeywordList }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState(list.words.join('\n'))
  const save = useMutation({
    mutationFn: (words: string[] | null) => saveKeywords(list.kind, list.language, words),
    onSuccess: (data, words) => {
      queryClient.setQueryData(botKeys.keywords, data)
      toast.success(words === null ? 'Default list restored' : 'Keywords saved')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not save.'),
  })
  const words = text.split('\n').map((w) => w.trim()).filter(Boolean)
  return (
    <div className="space-y-2" data-keyword-list={`${list.kind}-${list.language}`}>
      <div className="flex items-center gap-2 text-sm font-medium">
        {LANGUAGE_LABEL[list.language]}
        <Badge variant={list.custom ? 'default' : 'secondary'}>{list.custom ? 'Custom' : 'Default'}</Badge>
      </div>
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={8}
        aria-label={`${KIND_LABEL[list.kind].title} words, ${LANGUAGE_LABEL[list.language]}`}
        placeholder="One word or phrase per line"
      />
      <div className="flex gap-2">
        <Button size="sm" disabled={save.isPending} onClick={() => save.mutate(words)}>
          {save.isPending ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
          Save
        </Button>
        {list.custom && (
          <Button size="sm" variant="outline" disabled={save.isPending} onClick={() => save.mutate(null)}>
            <RotateCcwIcon />
            Default
          </Button>
        )}
      </div>
    </div>
  )
}
