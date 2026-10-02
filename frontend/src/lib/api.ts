import { env } from '@/lib/env'
import { supabase } from '@/lib/supabase'
import type { ApiErrorBody } from '@/types/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  query?: Record<string, QueryValue>
  signal?: AbortSignal
}

function buildUrl(path: string, query?: Record<string, QueryValue>): URL {
  const url = new URL(`/api${path}`, env.apiUrl)
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  }
  return url
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as ApiErrorBody).error?.code === 'string'
  )
}

async function handleUnauthorized(): Promise<void> {
  await supabase.auth.signOut({ scope: 'local' })
  if (window.location.pathname !== '/login') {
    window.location.replace('/login?expired=1')
  }
}

/** Calls the FastAPI backend with the current Supabase access token. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(0, 'NETWORK', 'Cannot reach the server. Check your connection.')
  }

  if (response.status === 401) {
    await handleUnauthorized()
    throw new ApiError(401, 'UNAUTHENTICATED', 'Your session has expired. Sign in again.')
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    if (isErrorBody(body)) {
      throw new ApiError(response.status, body.error.code, body.error.message, body.error.details)
    }
    throw new ApiError(response.status, 'ERROR', 'Something went wrong.')
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}
