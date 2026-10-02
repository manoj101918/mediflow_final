import { expect, test } from '@playwright/test'

import { api, apiToken, cancelTagged, clinicDate, newSignedInPage } from './helpers.ts'

// Needs the API running with RAG_FAKE_LLM=true (Playwright starts it that way when it is not
// already running) and the clinical seed (backend: python -m scripts.seed_clinical).
// Acts only on an appointment it books for tomorrow, and cancels it afterwards.
const TOMORROW = clinicDate(1)
const TAG = `E2E chart ${Date.now()}`
const PRAKASH = '2037da99-bae2-d71e-a051-2f8a85bb826f' // seed test patient
const DR_KHAN = 'd0c00000-0000-4000-8000-000000000003'

test.afterAll(async () => {
  await cancelTagged(await apiToken('reception1@mediflow.test'), TOMORROW, TAG)
})

test('doctor opens a checked-in patient, sees the history and gets a cited answer', async ({ browser }) => {
  // Front desk: book Prakash Hegde with Dr. Khan for tomorrow and check him in.
  const desk = await apiToken('reception1@mediflow.test')
  const day = await api<{ slots: { starts_at: string }[] }>(desk, `/doctors/${DR_KHAN}/slots?date=${TOMORROW}`)
  expect(day.slots.length).toBeGreaterThan(0)
  const booked = await api<{ id: string }>(desk, '/appointments', {
    method: 'POST',
    body: JSON.stringify({
      patient_id: PRAKASH,
      doctor_id: DR_KHAN,
      starts_at: day.slots.at(-1)!.starts_at,
      source: 'phone',
      reason_for_visit: TAG,
    }),
  })
  await api(desk, `/appointments/${booked.id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status: 'checked_in' }),
  })

  // Doctor: open the chart for that visit.
  const doctor = await newSignedInPage(browser, 'dr.khan@mediflow.test', '/doctor')
  await doctor.goto(`/doctor/patients/${PRAKASH}?appointment=${booked.id}`)
  await expect(doctor.getByRole('heading', { name: 'Prakash Hegde' })).toBeVisible()
  await expect(doctor.locator('[data-allergy="Penicillin"]')).toBeVisible()
  await expect(doctor.getByRole('tab', { name: 'Current visit' })).toHaveAttribute('data-state', 'active')

  // History across doctors (seeded visits by Dr. Sharma and Dr. Khan).
  await doctor.getByRole('tab', { name: 'Visit history' }).click()
  const visits = doctor.locator('li[data-consultation-id]')
  await expect(visits.first()).toBeVisible()
  expect(await visits.count()).toBeGreaterThanOrEqual(3)
  await expect(doctor.getByText('Dr. Anil Sharma').first()).toBeVisible()

  // Ask the assistant; the streamed answer cites a visit or report.
  const panel = doctor.getByTestId('chat-panel')
  await panel.getByLabel('Question').fill('What is the HbA1c trend?')
  await panel.getByRole('button', { name: 'Send' }).click()
  const answer = panel.locator('[data-chat-role="assistant"]').last()
  const sources = answer.locator('[data-citation-type="consultation"], [data-citation-type="report"]')
  await expect(sources.first()).toBeVisible()
  await expect(answer).toContainText(/HbA1c/i)
  await expect(panel.getByText("Answers come only from this patient's records.")).toBeVisible()

  // A citation opens what it cites.
  const first = sources.first()
  const type = await first.getAttribute('data-citation-type')
  await first.click()
  if (type === 'report') await expect(doctor.getByTestId('report-viewer')).toBeVisible()
  else await expect(doctor.locator('li[data-consultation-id].ring-2')).toBeVisible()
})
