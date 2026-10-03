import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BotIcon,
  Loader2Icon,
  MicIcon,
  RotateCcwIcon,
  SendIcon,
  SquareIcon,
  UserIcon,
  Volume2Icon,
  VolumeXIcon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiError } from '@/lib/api'
import {
  LANGUAGE_LABEL,
  SPEECH_LANG,
  fetchSimMessages,
  resetSimulator,
  sendVoiceTurn,
  simKeys,
} from '@/lib/bot'
import { formatTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { BotLanguage, VoiceTurn } from '@/types/api'

type Entry = { id: number; who: 'caller' | 'bot'; text: string; turn?: VoiceTurn }

const DEFAULT_PHONE = '9999000222'

/**
 * A browser demo of the future phone booking line: hold to talk, the backend transcribes,
 * the same conversation engine as WhatsApp answers (short spoken prompts), and the reply is
 * played back. Bookings are real pending requests with source "voice".
 */
export function VoiceSimulatorPage() {
  const queryClient = useQueryClient()
  const [phone, setPhone] = useState(DEFAULT_PHONE)
  const [language, setLanguage] = useState<BotLanguage>('te')
  const [speak, setSpeak] = useState(true)
  const [log, setLog] = useState<Entry[]>([])
  const [text, setText] = useState('')
  const nextId = useRef(0)
  const recorder = useRecorder()

  const add = (entry: Omit<Entry, 'id'>) => setLog((items) => [...items, { ...entry, id: nextId.current++ }])

  const turn = useMutation({
    mutationFn: sendVoiceTurn,
    onSuccess: (result, input) => {
      const said = input.replyId
        ? `(tapped) ${input.text ?? input.replyId}`
        : result.transcript || (result.voice_error ? '(could not understand the recording)' : '')
      if (said) add({ who: 'caller', text: said })
      add({ who: 'bot', text: result.replies.map((r) => r.text).join('\n'), turn: result })
      if (result.appointment_id) toast.success('Booking request created: see reception Today.')
      if (speak) play(result, language)
      void queryClient.invalidateQueries({ queryKey: simKeys.messages(phone) })
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'The simulator could not reach the server.'),
  })
  const reset = useMutation({
    mutationFn: () => resetSimulator(phone),
    onSuccess: () => {
      setLog([])
      toast.success('Conversation reset')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not reset.'),
  })
  const messages = useQuery({
    queryKey: simKeys.messages(phone),
    queryFn: ({ signal }) => fetchSimMessages(phone, signal),
    enabled: phone.replace(/\D/g, '').length >= 10,
    refetchInterval: 5_000,
  })

  const busy = turn.isPending || recorder.recording
  const last = [...log].reverse().find((e) => e.turn)?.turn

  async function stopAndSend() {
    const blob = await recorder.stop()
    if (blob && blob.size > 0) turn.mutate({ phone, language, audio: blob })
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4" data-testid="voice-sim">
      <div>
        <h1 className="text-xl font-semibold">Voice booking simulator</h1>
        <p className="text-sm text-muted-foreground">
          A free demo of the future phone line. Speak as a patient; the WhatsApp bot's engine answers with short spoken
          prompts. Bookings are real requests that reception must approve.
        </p>
      </div>
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-6">
          <div className="space-y-1.5">
            <Label htmlFor="sim-phone">Test caller phone</Label>
            <Input id="sim-phone" value={phone} onChange={(e) => setPhone(e.target.value)} className="w-44" inputMode="tel" />
          </div>
          <div className="space-y-1.5">
            <Label>Language</Label>
            <Select value={language} onValueChange={(v) => setLanguage(v as BotLanguage)}>
              <SelectTrigger className="w-36" aria-label="Language">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(LANGUAGE_LABEL) as BotLanguage[]).map((code) => (
                  <SelectItem key={code} value={code}>
                    {LANGUAGE_LABEL[code]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" onClick={() => setSpeak((v) => !v)} aria-pressed={speak}>
            {speak ? <Volume2Icon /> : <VolumeXIcon />}
            {speak ? 'Speaking replies' : 'Muted'}
          </Button>
          <Button variant="outline" onClick={() => reset.mutate()} disabled={reset.isPending}>
            <RotateCcwIcon />
            New call
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Call</CardTitle>
            <CardDescription>Hold the button while you speak (under 30 seconds), or type below.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ol className="max-h-[50svh] space-y-2 overflow-y-auto" data-testid="sim-log">
              {log.map((entry) => (
                <li
                  key={entry.id}
                  className={cn('flex gap-2 text-sm', entry.who === 'caller' && 'flex-row-reverse')}
                  data-sim-who={entry.who}
                >
                  {entry.who === 'bot' ? <BotIcon className="mt-1 size-4 shrink-0" /> : <UserIcon className="mt-1 size-4 shrink-0" />}
                  <span
                    className={cn(
                      'rounded-xl px-3 py-2 whitespace-pre-wrap',
                      entry.who === 'bot' ? 'bg-muted' : 'bg-primary text-primary-foreground',
                    )}
                  >
                    {entry.text}
                  </span>
                </li>
              ))}
              {log.length === 0 && <li className="text-sm text-muted-foreground">Press and hold to start the call.</li>}
            </ol>

            {last && last.replies.some((r) => r.options.length > 0) && (
              <div className="flex flex-wrap gap-2" data-testid="sim-options">
                {last.replies
                  .flatMap((r) => r.options)
                  .map((option, index) => (
                    <Button
                      key={option.id}
                      size="sm"
                      variant="secondary"
                      disabled={busy}
                      data-sim-option={option.id}
                      onClick={() => turn.mutate({ phone, language, replyId: option.id, text: option.title })}
                    >
                      {index + 1}. {option.title}
                    </Button>
                  ))}
              </div>
            )}

            <div className="flex flex-col items-center gap-2">
              <Button
                size="lg"
                className={cn('h-16 w-16 rounded-full', recorder.recording && 'bg-red-600 hover:bg-red-600')}
                aria-label={recorder.recording ? 'Release to send' : 'Hold to talk'}
                disabled={turn.isPending || !recorder.supported}
                onPointerDown={() => void recorder.start()}
                onPointerUp={() => void stopAndSend()}
                onPointerLeave={() => recorder.recording && void stopAndSend()}
              >
                {turn.isPending ? <Loader2Icon className="size-6 animate-spin" /> : recorder.recording ? <SquareIcon className="size-6" /> : <MicIcon className="size-6" />}
              </Button>
              <span className="text-xs text-muted-foreground">
                {!recorder.supported
                  ? 'This browser cannot record audio; type instead.'
                  : recorder.recording
                    ? 'Listening… release to send'
                    : 'Hold to talk'}
              </span>
            </div>

            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (!text.trim()) return
                turn.mutate({ phone, language, text: text.trim() })
                setText('')
              }}
            >
              <Input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="…or type what the caller says"
                aria-label="Caller says"
                data-testid="sim-text"
                maxLength={500}
              />
              <Button type="submit" disabled={busy || !text.trim()}>
                <SendIcon />
                Say
              </Button>
            </form>
            {last && (
              <p className="text-xs text-muted-foreground">
                Voice: {last.tts_provider === 'browser' ? 'browser speech (free)' : last.tts_provider} · state {last.state}
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-base">Messages to this caller</CardTitle>
            <CardDescription>Approvals and rejections from reception arrive here.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2 text-sm" data-testid="sim-outbox">
              {(messages.data ?? [])
                .filter((m) => m.kind !== 'reply' && m.kind !== 'notice')
                .map((m) => (
                  <li key={m.id} className="rounded-lg border p-2" data-outbox-kind={m.kind}>
                    <div className="mb-1 flex items-center gap-2">
                      <Badge variant={m.kind === 'approval' ? 'default' : 'secondary'}>{m.kind}</Badge>
                      <span className="text-xs text-muted-foreground">{formatTime(m.created_at)}</span>
                    </div>
                    <p className="whitespace-pre-wrap">{m.text}</p>
                  </li>
                ))}
              {(messages.data ?? []).every((m) => m.kind === 'reply' || m.kind === 'notice') && (
                <li className="text-muted-foreground">Nothing yet.</li>
              )}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function play(result: VoiceTurn, language: BotLanguage) {
  if (result.audio_base64 && result.audio_mime?.startsWith('audio/')) {
    void new Audio(`data:${result.audio_mime};base64,${result.audio_base64}`).play().catch(() => undefined)
    return
  }
  if (!result.speech_text || typeof window === 'undefined' || !('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(result.speech_text)
  utterance.lang = SPEECH_LANG[language]
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang === utterance.lang)
  if (voice) utterance.voice = voice
  window.speechSynthesis.speak(utterance)
}

/** Push-to-talk recording with MediaRecorder (opus in webm; Sarvam accepts it as is). */
function useRecorder() {
  const [recording, setRecording] = useState(false)
  const media = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const supported = typeof window !== 'undefined' && 'MediaRecorder' in window && !!navigator.mediaDevices
  useEffect(() => () => media.current?.stream.getTracks().forEach((t) => t.stop()), [])

  async function start() {
    if (!supported || recording) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunks.current = []
      recorder.ondataavailable = (e) => e.data.size > 0 && chunks.current.push(e.data)
      recorder.start()
      media.current = recorder
      setRecording(true)
    } catch {
      toast.error('Microphone access was denied.')
    }
  }

  function stop(): Promise<Blob | null> {
    const recorder = media.current
    if (!recorder || recorder.state === 'inactive') return Promise.resolve(null)
    return new Promise((resolve) => {
      recorder.onstop = () => {
        recorder.stream.getTracks().forEach((t) => t.stop())
        media.current = null
        setRecording(false)
        resolve(new Blob(chunks.current, { type: recorder.mimeType || 'audio/webm' }))
      }
      recorder.stop()
    })
  }

  return { recording, supported, start, stop }
}
