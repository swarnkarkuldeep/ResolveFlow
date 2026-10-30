import { expect, test } from '@playwright/test'

import { login, newTicket, signupFresh, uid } from './helpers'

const panel = (page: import('@playwright/test').Page) => page.getByRole('region', { name: 'Service levels' })

test('a new ticket shows its first-response and resolution deadlines', async ({ page }) => {
  await signupFresh(page, 'Sla')
  await newTicket(page, `Deadlines ${uid()}`)
  await expect(panel(page).getByText(/First response: due/)).toBeVisible()
  await expect(panel(page).getByText(/Resolution: due/)).toBeVisible()
  await panel(page).getByText('How is this calculated?').click()
  await expect(panel(page).getByText(/Business hours only \(Mon–Fri 09:00–17:00, UTC\)/)).toBeVisible()
  await expect(panel(page).getByText('Clock started')).toBeVisible()
})

test('waiting on the customer pauses the clock and resuming brings the deadline back', async ({ page }) => {
  await signupFresh(page, 'Pause')
  await newTicket(page, `Pause ${uid()}`)
  await page.locator('#prop-status').selectOption('pending')
  await expect(panel(page).getByText(/First response: paused, waiting on the customer/)).toBeVisible()
  await panel(page).getByText('How is this calculated?').click()
  await expect(panel(page).getByText('Paused: waiting on the customer')).toBeVisible()
  await page.locator('#prop-status').selectOption('open')
  await expect(panel(page).getByText(/First response: due/)).toBeVisible()
  await expect(panel(page).getByText('Resumed')).toBeVisible()
})

test('the first reply meets the first-response target and resolving meets the resolution target', async ({ page }) => {
  await signupFresh(page, 'Met')
  await newTicket(page, `Met ${uid()}`)
  await page.getByLabel('Message').fill('On it, thanks for flagging this.')
  await page.getByRole('button', { name: 'Send reply' }).click()
  await expect(panel(page).getByText(/First response: met/)).toBeVisible()
  await expect(panel(page).getByText(/Resolution: due/)).toBeVisible()
  await page.locator('#prop-status').selectOption('resolved')
  await expect(panel(page).getByText(/Resolution: met/)).toBeVisible()
})

test('changing a target on the Service levels page changes the deadline of an open ticket', async ({ page }) => {
  await signupFresh(page, 'Targets')
  await newTicket(page, `Urgent ${uid()}`)
  await page.locator('#prop-priority').selectOption('urgent')
  const line = panel(page).getByText(/First response: due/)
  await expect(line).toBeVisible()
  const before = await line.textContent()

  await page.getByRole('link', { name: 'Service levels' }).click()
  const urgent = page.getByLabel('Urgent: first response (minutes)')
  await urgent.fill('240')
  await expect(page.getByText('4 h').first()).toBeVisible()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Service levels saved')).toBeVisible()

  await page.getByRole('link', { name: 'Inbox' }).click()
  await page.getByRole('link', { name: /Urgent / }).first().click()
  await expect(panel(page).getByText(/First response: due/)).toBeVisible()
  const after = await panel(page).getByText(/First response: due/).textContent()
  expect(after).not.toBe(before)
})

test('the time zone shown in the explanation follows the setting', async ({ page }) => {
  await signupFresh(page, 'Zone')
  await newTicket(page, `Zone ${uid()}`)
  await page.getByRole('link', { name: 'Service levels' }).click()
  await page.getByLabel('Time zone').selectOption('Europe/London')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Service levels saved')).toBeVisible()
  await page.getByRole('link', { name: 'Inbox' }).click()
  await page.getByRole('link', { name: /Zone / }).first().click()
  await panel(page).getByText('How is this calculated?').click()
  await expect(panel(page).getByText(/Mon–Fri 09:00–17:00, Europe\/London/)).toBeVisible()
})

test('turning service levels off removes the deadlines from the ticket', async ({ page }) => {
  await signupFresh(page, 'Off')
  await newTicket(page, `Off ${uid()}`)
  await expect(panel(page)).toBeVisible()
  await page.getByRole('link', { name: 'Service levels' }).click()
  await page.getByLabel('Track service levels').uncheck()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Service levels saved')).toBeVisible()
  await page.getByRole('link', { name: 'Inbox' }).click()
  await page.getByRole('link', { name: /Off / }).first().click()
  await expect(page.getByRole('heading', { level: 2 }).first()).toBeVisible()
  await expect(panel(page)).toHaveCount(0)
})

test('the At risk and Breached views load, and seeded history shows real breaches', async ({ page }) => {
  await login(page, 'owner')
  await page.getByRole('tab', { name: 'Breached' }).click()
  await expect(page.getByRole('region', { name: 'Tickets' }).getByText(/Breached .* ago/).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('tab', { name: 'At risk' }).click()
  await expect(page.getByRole('region', { name: 'Tickets' })).toBeVisible()
})

test('fresh workspaces start with empty risk views, and only owners and admins can see Service levels', async ({ page }) => {
  await signupFresh(page, 'Views')
  await page.getByRole('tab', { name: 'At risk' }).click()
  await expect(page.getByText('Nothing at risk')).toBeVisible()
  await page.getByRole('tab', { name: 'Breached' }).click()
  await expect(page.getByText('No breaches')).toBeVisible()

  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await login(page, 'agent')
  await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Service levels' })).toHaveCount(0)
  await page.goto('/service-levels')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
})
