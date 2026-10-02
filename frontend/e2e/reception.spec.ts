import { expect, test } from '@playwright/test'

import { apiToken, cancelTagged, clinicDate, newSignedInPage, signIn } from './helpers.ts'

// Bookings are made for tomorrow so they never disturb today's live queue, and every
// booking a test makes is cancelled afterwards (cancel, never delete: tokens are not reused).
const TOMORROW = clinicDate(1)
const TAG = `E2E ${Date.now()}`

test.afterAll(async () => {
  await cancelTagged(await apiToken('reception1@mediflow.test'), TOMORROW, TAG)
})

test('receptionist books an appointment and another receptionist sees it live', async ({ browser }) => {
  // Receptionist B watches tomorrow's appointments (subscribed to Realtime).
  const watcher = await newSignedInPage(browser, 'reception2@mediflow.test', '/reception')
  await watcher.goto(`/reception/appointments?from=${TOMORROW}&to=${TOMORROW}`)
  await expect(watcher.getByRole('heading', { name: 'Appointments' })).toBeVisible()
  await expect(watcher.locator('tbody tr').first()).toBeVisible()
  const watchedRow = watcher.locator('tbody tr', { hasText: TAG })
  await expect(watchedRow).toHaveCount(0)

  // Receptionist A books through the three-step sheet.
  const desk = await newSignedInPage(browser, 'reception1@mediflow.test', '/reception')
  await desk.getByRole('button', { name: /New appointment/ }).click()
  const sheet = desk.getByRole('dialog', { name: 'New appointment' })
  await sheet.getByLabel('Search patients').fill('Prakash')
  await sheet.getByRole('button', { name: /Prakash Hegde/ }).click()
  await sheet.getByRole('button', { name: /Dr\. Imran Khan/ }).click()
  await sheet.getByRole('button', { name: 'Next day' }).click()
  const slots = sheet.getByRole('radio')
  await expect(slots.first()).toBeVisible()
  await slots.last().click()
  await sheet.getByRole('button', { name: 'Continue' }).click()
  await sheet.getByRole('radio', { name: /Phone/ }).click()
  await sheet.getByLabel('Reason for visit').fill(TAG)
  await sheet.getByRole('button', { name: 'Book appointment' }).click()
  await expect(desk.getByText(/Booked token #\d+ for Prakash Hegde/)).toBeVisible()
  await expect(sheet).toBeHidden()

  // The booking shows on A's appointment list…
  await desk.goto(`/reception/appointments?from=${TOMORROW}&to=${TOMORROW}`)
  await expect(desk.locator('tbody tr', { hasText: TAG })).toContainText('Scheduled')

  // …and on B's screen without a reload, with a toast.
  await expect(watchedRow).toHaveCount(1)
  await expect(watchedRow).toContainText('Dr. Imran Khan')
  await expect(watcher.getByText(/New booking: token #\d+/)).toBeVisible()
})

test('each role is kept to its own dashboard', async ({ page }) => {
  await page.goto('/reception')
  await expect(page).toHaveURL(/\/login$/)

  await signIn(page, 'dr.iyer@mediflow.test')
  await expect(page).toHaveURL(/\/doctor$/)
  await page.goto('/reception/patients')
  await expect(page).toHaveURL(/\/doctor$/)
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/doctor$/)

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await page.goto('/doctor')
  await expect(page).toHaveURL(/\/login$/)
})
