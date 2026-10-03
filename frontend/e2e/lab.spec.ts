import { expect, test } from '@playwright/test'

import { api, apiToken, cancelTagged, newSignedInPage, nextOpenDay } from './helpers.ts'

// Doctor orders HbA1c + lipid profile -> lab collects, enters (one high), supervisor verifies
// -> doctor sees the results inbox, the flagged value, the PDF and a cited chatbot answer.
// Needs the API in RAG_FAKE_LLM=true mode (see playwright.config.ts) and scripts.seed_lab.
// Uses its own patient ("E2E Lab Patient", created once) and a booking from tomorrow on,
// cancelled afterwards; released lab results stay on that test patient.
const TAG = `E2E lab ${Date.now()}`
const DR_SHARMA = 'd0c00000-0000-4000-8000-000000000001'
const PHONE = '+919999000111'
let bookedDay = ''

test.afterAll(async () => {
  if (bookedDay) await cancelTagged(await apiToken('reception1@mediflow.test'), bookedDay, TAG)
})

test('lab order from consultation to released, flagged, cited result', async ({ browser }) => {
  test.setTimeout(240_000)
  const desk = await apiToken('reception1@mediflow.test')
  const found = await api<{ items: { id: string; phone: string }[] }>(desk, `/patients?q=${encodeURIComponent('E2E Lab Patient')}`)
  const patient =
    found.items.find((p) => p.phone === PHONE) ??
    (await api<{ id: string }>(desk, '/patients', {
      method: 'POST',
      body: JSON.stringify({ full_name: 'E2E Lab Patient', phone: PHONE, gender: 'male', date_of_birth: '1975-03-10' }),
    }))

  // Next working day from tomorrow on (never today: the dev clinic is shared).
  const open = await nextOpenDay(desk, DR_SHARMA)
  bookedDay = open.date
  const slot = open.slots.at(-1)
  const booked = await api<{ id: string }>(desk, '/appointments', {
    method: 'POST',
    body: JSON.stringify({ patient_id: patient.id, doctor_id: DR_SHARMA, starts_at: slot!.starts_at, source: 'phone', reason_for_visit: TAG }),
  })
  await api(desk, `/appointments/${booked.id}/status`, { method: 'POST', body: JSON.stringify({ status: 'checked_in' }) })

  // Doctor orders.
  const doctor = await newSignedInPage(browser, 'dr.sharma@mediflow.test', '/doctor')
  await doctor.goto(`/doctor/patients/${patient.id}?appointment=${booked.id}`)
  const panel = doctor.getByTestId('order-tests')
  await panel.getByRole('button', { name: 'HbA1c', exact: true }).click()
  await panel.getByRole('button', { name: 'Lipid profile', exact: true }).click()
  await panel.getByRole('button', { name: 'Order 2 tests' }).click()
  const order = panel.locator('[data-lab-order-id]').first()
  await expect(order.locator('[data-lab-item-id]')).toHaveCount(2)
  const orderId = (await order.getAttribute('data-lab-order-id'))!

  // Lab technician collects and enters results.
  const tech = await newSignedInPage(browser, 'lab1@mediflow.test', '/lab')
  await tech.getByLabel('Search worklist').fill('E2E Lab')
  await tech.locator(`[data-lab-order-id="${orderId}"] a`).click()
  await expect(tech.getByTestId('lab-patient-name')).toHaveText('E2E Lab Patient')
  await tech.getByRole('button', { name: /^Collect 2 selected/ }).click()
  await expect(tech.locator('tr[data-sample-code]')).toHaveCount(2)
  const items = tech.locator('[data-lab-item-status="sample_collected"]')
  const hba1c = items.filter({ hasText: 'HbA1c' })
  await hba1c.locator('tr[data-parameter="HBA1C"] input').fill('7.8')
  await expect(hba1c.locator('[data-live-flag="high"]')).toBeVisible()
  await hba1c.getByRole('button', { name: 'Submit for verification' }).click()
  const lipid = tech.locator('[data-lab-item-status="sample_collected"]').filter({ hasText: 'Lipid profile' })
  for (const [code, value] of [['CHOL', '180'], ['TG', '120'], ['HDL', '48'], ['LDL', '96']] as const) {
    await lipid.locator(`tr[data-parameter="${code}"] input`).fill(value)
  }
  await lipid.getByRole('button', { name: 'Submit for verification' }).click()
  await expect(tech.locator('[data-lab-item-status="result_entered"]')).toHaveCount(2)

  // Supervisor verifies and releases.
  const head = await newSignedInPage(browser, 'labhead@mediflow.test', '/lab')
  await head.goto(`/lab/orders/${orderId}`)
  for (let i = 0; i < 2; i++) {
    await head.locator('[data-lab-item-status="result_entered"]').first().getByRole('button', { name: 'Verify and release' }).click()
    await expect(head.locator('[data-lab-item-status="released"]')).toHaveCount(i + 1)
  }

  // Doctor: inbox -> chart with the flagged value -> PDF -> cited answer.
  await doctor.goto('/doctor')
  const row = doctor.getByTestId('lab-inbox').locator(`[data-lab-order-id="${orderId}"]`)
  await expect(row).toBeVisible()
  await row.getByRole('link').click()
  const value = doctor.locator(`[data-lab-order-id="${orderId}"] [data-parameter="HBA1C"] [data-flag]`)
  await expect(value).toHaveAttribute('data-flag', 'high')
  await doctor.getByRole('tab', { name: 'Reports' }).click()
  await expect(doctor.locator('[data-lab-report="generated"]', { hasText: 'Lab order' }).first()).toBeVisible({ timeout: 90_000 })

  const chat = doctor.getByTestId('chat-panel')
  await chat.getByLabel('Question').fill('What was the latest HbA1c lab result?')
  await chat.getByRole('button', { name: 'Send' }).click()
  const answer = chat.locator('[data-chat-role="assistant"]').last()
  await expect(answer.locator('[data-citation-type="lab_result"]').first()).toBeVisible({ timeout: 60_000 })
  await answer.locator('[data-citation-type="lab_result"]').first().click()
  await expect(doctor.getByRole('tab', { name: 'Lab results' })).toHaveAttribute('data-state', 'active')

  await api(await apiToken('dr.sharma@mediflow.test'), `/lab/orders/${orderId}/review`, { method: 'POST' })
})
