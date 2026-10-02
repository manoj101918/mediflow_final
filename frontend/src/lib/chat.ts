import { api, apiFetch, raiseForStatus } from '@/lib/api'
import type { ChatMessage, ChatSession, ChatStreamEvent } from '@/types/api'

export const chatKeys = {
  all: ['patient-chat'] as const,
  sessions: (patientId: string) => ['patient-chat', patientId, 'sessions'] as const,
  messages: (sessionId: string) => ['patient-chat', 'messages', sessionId] as const,
}

export const fetchChatSessions = (patientId: string, signal?: AbortSignal) =>
  api<ChatSession[]>(`/patients/${patientId}/chat/sessions`, { signal })

export const fetchChatMessages = (sessionId: string, signal?: AbortSignal) =>
  api<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`, { signal })

/** Parse one SSE block ("event: x\ndata: {...}"). */
function parseBlock(block: string): ChatStreamEvent | null {
  let event = ''
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (!event) return null
  return { event, data: data ? JSON.parse(data) : {} } as ChatStreamEvent
}

/**
 * Ask the assistant and stream the answer. Uses fetch + ReadableStream (EventSource cannot
 * send the Authorization header). Yields events until `done` or `error`.
 */
export async function* streamChat(
  patientId: string,
  body: { message: string; session_id?: string | null },
  signal?: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
  const response = await apiFetch(`/patients/${patientId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  await raiseForStatus(response)
  if (!response.body) throw new Error('Streaming is not supported by this browser.')

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value.replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const event = parseBlock(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      if (event) yield event
      boundary = buffer.indexOf('\n\n')
    }
  }
  const tail = parseBlock(buffer)
  if (tail) yield tail
}

export const SUGGESTED_QUESTIONS = [
  'Summarise previous visits',
  'Current medications and allergies',
  'What did the latest report show?',
  'What changed since the last visit?',
] as const
