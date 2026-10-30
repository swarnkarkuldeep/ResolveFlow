import { expect, test } from '@playwright/test'

import { login, mailTo, newTicket, signupFresh, uid } from './helpers'

test('create a ticket, reply (it really arrives by email), add a note, and triage it', async ({ page, request }) => {
  await login(page, 'owner')
  const subject = `Leaking tap ${uid()}`
  const customer = await newTicket(page, subject)

  // Reply: the worker sends it through SMTP to Mailpit.
  await page.getByLabel('Message').fill('We will be there on Tuesday morning.')
  await page.getByRole('button', { name: 'Send reply' }).click()
  const thread = page.getByRole('region', { name: 'Conversation' })
  await expect(thread.getByText('We will be there on Tuesday morning.')).toBeVisible()
  await expect(thread.getByText('Sent', { exact: true })).toBeVisible({ timeout: 20_000 })
  const mail = await mailTo(request, customer, `Re: ${subject}`)
  expect(mail.text).toContain('We will be there on Tuesday morning.')

  // Internal note stays internal.
  await page.getByRole('tab', { name: 'Internal note' }).click()
  await page.getByLabel('Message').fill('Customer prefers mornings.')
  await page.getByRole('button', { name: 'Add note' }).click()
  await expect(thread.getByText('Internal note')).toBeVisible()
  await expect(thread.getByText('Customer prefers mornings.')).toBeVisible()

  // Properties.
  await page.locator('#prop-priority').selectOption('urgent')
  await page.locator('#prop-status').selectOption('pending')
  await page.getByRole('button', { name: 'Assign to me' }).click()
  await expect(page.locator('#prop-assignee')).not.toHaveValue('')
  await page.getByLabel('Add tag').fill('vip')
  await page.getByLabel('Add tag').press('Enter')
  await expect(page.getByRole('button', { name: 'Remove tag vip' })).toBeVisible()

  // The audit history records it, and survives a reload.
  await page.reload()
  await page.locator('summary', { hasText: 'History' }).click()
  await expect(page.getByText(/Priority: normal → urgent/)).toBeVisible()
  await expect(page.getByText('Replied to the customer')).toBeVisible()
  await expect(page.locator('#prop-priority')).toHaveValue('urgent')
})

test('keyboard: j/k move, Enter opens, e resolves, ? lists the shortcuts', async ({ page }) => {
  await login(page, 'owner')
  const a = `Keyboard A ${uid()}`
  const b = `Keyboard B ${uid()}`
  await newTicket(page, a)
  await newTicket(page, b)
  await page.keyboard.press('Escape')
  await page.locator('body').click({ position: { x: 700, y: 400 } })
  await page.keyboard.press('j')
  await page.keyboard.press('k')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible()
  await page.keyboard.press('?')
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toContainText('Mark as resolved')
  await page.keyboard.press('Escape')
  await page.locator('body').click({ position: { x: 700, y: 400 } })
  await page.keyboard.press('e')
  await expect(page.getByText(/Ticket marked resolved/)).toBeVisible()
})

test('bulk resolve removes the selected tickets from the open queue', async ({ page }) => {
  await signupFresh(page, 'Bulk')
  const a = `Bulk A ${uid()}`
  const b = `Bulk B ${uid()}`
  await newTicket(page, a)
  await newTicket(page, b)
  await page.goto('/inbox')
  await expect(page.getByRole('link', { name: new RegExp(a) })).toBeVisible()
  await page.locator('body').click({ position: { x: 900, y: 500 } })
  await page.keyboard.press('x')
  await page.keyboard.press('j')
  await page.keyboard.press('x')
  await expect(page.getByText('2 selected')).toBeVisible()
  await page.getByLabel('Set status').selectOption('resolved')
  await expect(page.getByText('2 tickets marked resolved')).toBeVisible()
  await expect(page.getByRole('link', { name: new RegExp(a) })).toHaveCount(0)
  await page.getByRole('tab', { name: 'Done' }).click()
  await expect(page.getByRole('link', { name: new RegExp(a) })).toBeVisible()
  await expect(page.getByRole('link', { name: new RegExp(b) })).toBeVisible()
})

test('merging moves the conversation into the surviving ticket', async ({ page }) => {
  await signupFresh(page, 'Merge')
  const keep = `Keep ${uid()}`
  const dupe = `Duplicate ${uid()}`
  await newTicket(page, keep, 'same@customer.test', 'First message')
  await newTicket(page, dupe, 'same@customer.test', 'Second message about the same thing')
  await page.getByRole('button', { name: 'Merge…' }).click()
  const dialog = page.getByRole('dialog', { name: /Merge ticket/ })
  const value = await dialog.getByLabel('Merge into').locator('option', { hasText: keep }).getAttribute('value')
  await dialog.getByLabel('Merge into').selectOption(value!)
  await dialog.getByRole('button', { name: 'Merge tickets' }).click()
  await expect(page.getByRole('heading', { name: keep, level: 2 })).toBeVisible()
  const thread = page.getByRole('region', { name: 'Conversation' })
  await expect(thread.getByText('Second message about the same thing')).toBeVisible()
  await expect(thread.getByText('First message')).toBeVisible()
  await expect(thread.getByText(/Merged ticket #\d+ into this one/)).toBeVisible()
})

test('a customer email (simulated through the real webhook path) becomes a ticket', async ({ page }) => {
  await login(page, 'owner')
  await page.getByRole('link', { name: 'Channels' }).click()
  await expect(page.getByText(/^inbound-[a-f0-9]{16}@/)).toBeVisible()
  const subject = `Simulated ${uid()}`
  await page.getByLabel('From email').fill(`walk-${uid()}@customer.test`)
  await page.getByLabel('From name').fill('Walt Walkin')
  await page.getByLabel('Subject').fill(subject)
  await page.getByLabel('Message').fill('Is anyone there? This came in by email.')
  await page.getByRole('button', { name: 'Send simulated email' }).click()
  await page.getByRole('link', { name: 'Open the ticket' }).click()
  await expect(page.getByRole('heading', { name: subject, level: 2 })).toBeVisible()
  await expect(page.getByText('Email', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Conversation' }).getByText(/This came in by email\./)).toBeVisible()
})
