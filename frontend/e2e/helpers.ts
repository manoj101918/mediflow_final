import type { Browser, Page } from '@playwright/test'

export const PASSWORD = process.env.E2E_PASSWORD ?? 'Clinic@12345'
const API = process.env.E2E_API_URL ?? process.env.VITE_API_URL ?? 'http://localhost:8000'

/** Clinic-local (IST) date, YYYY-MM-DD, `offsetDays` from today. */
export function clinicDate(offsetDays = 0): string {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())
  return new Date(Date.parse(`${today}T12:00:00Z`) + offsetDays * 86_400_000).toISOString().slice(0, 10)
}

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

export async function newSignedInPage(browser: Browser, email: string, landing: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage()
  await signIn(page, email)
  await page.waitForURL(`**${landing}`)
  return page
}

/** An access token for direct API calls in setup / cleanup. */
export async function apiToken(email: string): Promise<string> {
  const url = process.env.VITE_SUPABASE_URL
  const key = process.env.VITE_SUPABASE_PUBLISHABLE_KEY
  if (!url || !key) throw new Error('VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY are not set (.env.local)')
  const response = await fetch(`${url}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password: PASSWORD }),
  })
  if (!response.ok) throw new Error(`Sign-in for ${email} failed: ${response.status}`)
  return ((await response.json()) as { access_token: string }).access_token
}

export async function api<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}/api${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  })
  if (!response.ok) throw new Error(`${init.method ?? 'GET'} ${path} failed: ${response.status} ${await response.text()}`)
  return (await response.json()) as T
}

interface AppointmentLite {
  id: string
  status: string
  reason_for_visit: string | null
}

/** Cancel (never delete) every still-scheduled appointment a test created, by its reason tag. */
export async function cancelTagged(token: string, date: string, tag: string): Promise<number> {
  const page = await api<{ items: AppointmentLite[] }>(token, `/appointments?date=${date}&page_size=200`)
  const mine = page.items.filter((a) => a.reason_for_visit === tag && a.status === 'scheduled')
  for (const a of mine) {
    await api(token, `/appointments/${a.id}/status`, {
      method: 'POST',
      body: JSON.stringify({ status: 'cancelled', note: 'E2E cleanup' }),
    })
  }
  return mine.length
}
