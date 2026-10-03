import { expect, test, type Page } from '@playwright/test'

import { api, apiToken, nextOpenDay, newSignedInPage } from './helpers.ts'

// The simulator's own test caller (never the demo patients). Needs the API with
// RAG_FAKE_LLM=true (fake speech-to-text / text-to-speech) and its bot worker running.
const CALLER_PHONE = '9999000222'
const CALLER_NAME = 'Voice Simulator Patient' // the bot rejects digits in names
const DR_SHARMA = 'd0c00000-0000-4000-8000-000000000001'

let appointmentId: string | null = null

test.afterAll(async () => {
  if (!appointmentId) return
  const desk = await apiToken('reception1@mediflow.test')
  const current = await api<{ status: string }>(desk, `/appointments/${appointmentId}`)
  if (current.status === 'pending_confirmation') {
    await api(desk, `/appointments/${appointmentId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'E2E cleanup' }),
    })
  } else if (current.status === 'scheduled') {
    await api(desk, `/appointments/${appointmentId}/status`, {
      method: 'POST',
      body: JSON.stringify({ status: 'cancelled', note: 'E2E cleanup' }),
    })
  }
})

async function say(page: Page, words: string) {
  await page.getByTestId('sim-text').fill(words)
  await page.getByRole('button', { name: 'Say' }).click()
}

async function tap(page: Page, optionId: string) {
  const option = page.locator(`[data-sim-option="${optionId}"]`)
  await expect(option).toBeEnabled()
  await option.click()
}

/** Click the first offered option whose id starts with `prefix`. */
async function tapFirst(page: Page, prefix: string) {
  const option = page.locator(`[data-sim-option^="${prefix}"]`).first()
  await expect(option).toBeEnabled()
  await option.click()
}

test('voice simulator books a slot; reception approves; the caller hears the confirmation', async ({ browser }) => {
  const desk = await apiToken('reception1@mediflow.test')
  const day = (await nextOpenDay(desk, DR_SHARMA)).date

  const admin = await newSignedInPage(browser, 'admin@mediflow.test', '/admin')
  await admin.goto('/admin/voice-simulator')
  await admin.getByLabel('Test caller phone').fill(CALLER_PHONE)
  await admin.getByRole('combobox', { name: 'Language' }).click()
  await admin.getByRole('option', { name: 'English' }).click()
  await admin.getByRole('button', { name: 'Speaking replies' }).click() // mute playback in CI
  await admin.getByRole('button', { name: 'New call' }).click()

  await say(admin, 'hello')
  await tap(admin, 'menu:book')
  // The caller may already be registered (earlier runs) or be asked for a name.
  const someoneElse = admin.locator('[data-sim-option="p:new"]')
  const askName = admin.getByTestId('sim-log').getByText("Please type the patient's full name.").last()
  await expect(someoneElse.or(askName)).toBeVisible()
  if (await someoneElse.isVisible()) {
    const existing = admin.locator('[data-sim-option^="p:"]').filter({ hasText: 'Voice' })
    if (await existing.count()) await existing.first().click()
    else {
      await someoneElse.click()
      await say(admin, CALLER_NAME)
    }
  } else {
    await say(admin, CALLER_NAME)
  }

  // Spoken menus offer three choices at a time ("more" pages through the rest).
  await expect(admin.locator('[data-sim-option^="d:"]').first()).toBeVisible()
  while (!(await admin.locator(`[data-sim-option="d:${DR_SHARMA}"]`).count())) await tap(admin, 'more')
  await tap(admin, `d:${DR_SHARMA}`)
  await expect(admin.locator('[data-sim-option^="day:"]').first()).toBeVisible()
  while (!(await admin.locator(`[data-sim-option="day:${day}"]`).count())) await tap(admin, 'more')
  await tap(admin, `day:${day}`)
  await tapFirst(admin, 't:')
  await tapFirst(admin, 'r:')
  await expect(admin.getByTestId('sim-log')).toContainText('Please confirm:')
  await say(admin, 'yes')
  await expect(admin.getByTestId('sim-log')).toContainText('Request received. Reception will confirm shortly.')

  type PendingRow = { id: string; source: string; patient: { full_name: string }; created_at: string }
  const pending = await api<{ items: PendingRow[] }>(
    desk,
    `/appointments?status=pending_confirmation&date_from=${day}&date_to=${day}&page_size=100`,
  )
  const mine = pending.items
    .filter((a: PendingRow) => a.source === 'voice' && a.patient.full_name === CALLER_NAME)
    .sort((a: PendingRow, b: PendingRow) => b.created_at.localeCompare(a.created_at))
  const newest = mine[0]
  expect(newest).toBeDefined()
  appointmentId = newest!.id

  // Reception sees the voice booking waiting for confirmation, with its chat, and approves.
  const reception = await newSignedInPage(browser, 'reception1@mediflow.test', '/reception')
  const row = reception.locator(`[data-pending-appointment-id="${appointmentId}"]`)
  await expect(row).toBeVisible()
  await expect(row.getByText('Voice bot')).toBeVisible()
  await row.getByRole('button', { name: 'View chat' }).click()
  await expect(reception.getByTestId('chat-transcript')).toContainText('Request received.')
  await reception.keyboard.press('Escape')
  await row.getByRole('button', { name: 'Approve' }).click()
  await expect(reception.getByText('Patient notified on voice simulator.')).toBeVisible()

  // The confirmation (with the token number) reaches the simulated caller.
  const approval = admin.locator('[data-outbox-kind="approval"]').first()
  await expect(approval).toContainText('Your appointment is confirmed.', { timeout: 20_000 })
  await expect(approval).toContainText('Token number:')
})
