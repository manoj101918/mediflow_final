import { api } from '@/lib/api'
import type {
  BotAlert,
  BotConversationDetail,
  BotConversationSummary,
  BotLanguage,
  BotStatus,
  KeywordKind,
  KeywordList,
  SimMessage,
  VoiceTurn,
} from '@/types/api'

/**
 * Booking-bot queries. Inbox, transcripts and alerts live under 'bot' and are polled (bot
 * tables are backend-only, so there is no Realtime for them). "View chat" for an appointment
 * lives under 'appointments' so appointment refreshes include it.
 */
export const botKeys = {
  all: ['bot'] as const,
  conversations: (handoff: boolean) => ['bot', 'conversations', handoff] as const,
  conversation: (id: string) => ['bot', 'conversation', id] as const,
  alerts: ['bot', 'alerts'] as const,
  status: ['bot', 'status'] as const,
  keywords: ['bot', 'keywords'] as const,
  forAppointment: (id: string) => ['appointments', 'conversation', id] as const,
}

export const INBOX_POLL_MS = 10_000

export const fetchConversations = (handoff: boolean, signal?: AbortSignal) =>
  api<BotConversationSummary[]>('/bot/conversations', { query: { handoff: String(handoff) }, signal })

export const fetchConversation = (id: string, signal?: AbortSignal) =>
  api<BotConversationDetail>(`/bot/conversations/${id}`, { signal })

export const replyToConversation = (id: string, text: string) =>
  api<{ status: string }>(`/bot/conversations/${id}/reply`, { method: 'POST', body: { text } })

export const resumeBot = (id: string) =>
  api<void>(`/bot/conversations/${id}/resume`, { method: 'POST' })

export const fetchAppointmentConversation = (appointmentId: string, signal?: AbortSignal) =>
  api<{ conversation_id: string | null }>(`/bot/appointments/${appointmentId}/conversation`, { signal })

export const fetchBotAlerts = (signal?: AbortSignal) => api<BotAlert[]>('/bot/alerts', { signal })

export const acknowledgeBotAlert = (id: string) =>
  api<void>(`/bot/alerts/${id}/ack`, { method: 'POST' })

export const fetchBotStatus = (signal?: AbortSignal) => api<BotStatus>('/admin/bot/status', { signal })

export const fetchKeywords = (signal?: AbortSignal) => api<KeywordList[]>('/admin/bot/keywords', { signal })

export const saveKeywords = (kind: KeywordKind, language: BotLanguage, words: string[] | null) =>
  api<KeywordList[]>('/admin/bot/keywords', { method: 'PUT', body: { kind, language, words } })

export const LANGUAGE_LABEL: Record<BotLanguage, string> = {
  te: 'Telugu',
  hi: 'Hindi',
  en: 'English',
}

export const HANDOFF_REASON_LABEL: Record<string, string> = {
  button: 'Asked for reception',
  parse_failed: "Bot couldn't understand",
  emergency: 'Emergency',
  staff: 'Taken over',
}

/** First names on the phone, or the phone itself. */
export function conversationTitle(c: { names: string[]; phone: string }): string {
  return c.names.length ? c.names.join(', ') : c.phone
}

// --- Voice booking simulator (admin) ---

export const simKeys = {
  messages: (phone: string) => ['bot', 'sim-messages', phone] as const,
}

export function sendVoiceTurn(input: {
  phone: string
  language: BotLanguage
  audio?: Blob
  text?: string
  replyId?: string
}) {
  const form = new FormData()
  form.set('phone', input.phone)
  form.set('language', input.language)
  if (input.audio) form.set('audio', input.audio, 'recording.webm')
  if (input.text) form.set('text', input.text)
  if (input.replyId) form.set('reply_id', input.replyId)
  return api<VoiceTurn>('/admin/voice-sim/turn', { method: 'POST', body: form })
}

export const fetchSimMessages = (phone: string, signal?: AbortSignal) =>
  api<SimMessage[]>('/admin/voice-sim/messages', { query: { phone }, signal })

export const resetSimulator = (phone: string) =>
  api<void>('/admin/voice-sim/reset', { method: 'POST', body: { phone } })

export const SPEECH_LANG: Record<BotLanguage, string> = { te: 'te-IN', hi: 'hi-IN', en: 'en-IN' }
