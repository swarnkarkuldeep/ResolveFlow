import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { login, newTicket, signupFresh, uid } from './helpers'

/** Builds "when a ticket arrives and the subject contains <word>, set priority high and add a tag". */
async function buildRule(page: Page, name: string, word: string, tag: string) {
  await page.getByRole('link', { name: 'Automations' }).click()
  await page.getByRole('link', { name: 'New automation' }).click()
  await page.getByLabel('Name', { exact: true }).fill(name)
  const conditions = page.getByRole('group', { name: 'Conditions' })
  if ((await conditions.getByLabel('Field').count()) === 0) await conditions.getByRole('button', { name: 'Add condition' }).first().click()
  await conditions.getByLabel('Field').first().selectOption('subject')
  await conditions.getByLabel('Operator').first().selectOption('contains')
  await conditions.getByLabel('Value').first().fill(word)
  const actions = page.getByRole('group', { name: 'Actions', exact: true })
  const first = actions.getByRole('group', { name: 'Action 1' })
  await first.getByLabel('Action type').selectOption('set_priority')
  await first.getByLabel('Priority').selectOption('high')
  await actions.getByRole('button', { name: 'Add action' }).click()
  const second = actions.getByRole('group', { name: 'Action 2' })
  await second.getByLabel('Action type').selectOption('add_tag')
  await second.getByLabel('Tag').fill(tag)
  await page.getByRole('button', { name: 'Save automation' }).click()
  await expect(page.getByText('Not live yet', { exact: false }).or(page.getByText(/is not live yet/))).toBeVisible()
}

async function testAndActivate(page: Page, subject: string) {
  const tester = page.getByRole('region', { name: 'Test it' })
  await tester.getByLabel('Subject (test ticket)').fill(subject)
  await tester.getByRole('button', { name: 'Run test' }).click()
  await expect(tester.getByText('This automation would run.')).toBeVisible()
  await tester.getByRole('button', { name: 'Record as test' }).click()
  await expect(tester.getByText('Test passed')).toBeVisible()
  await page.getByRole('button', { name: 'Make live' }).click()
  await expect(page.getByText(/Version \d+ is live\./)).toBeVisible()
}

test('a tested automation runs on a new ticket and the ticket explains why', async ({ page }) => {
  await signupFresh(page, 'Rules')
  await buildRule(page, 'Refund requests', 'refund', 'refund')
  await testAndActivate(page, 'Refund for my order')

  await page.getByRole('link', { name: 'Inbox' }).click()
  const subject = `Refund please ${uid()}`
  await newTicket(page, subject)
  await expect(page.locator('#prop-priority')).toHaveValue('high')
  const why = page.getByRole('region', { name: 'Automations on this ticket' })
  await why.getByText(/Automations that ran/).click()
  await expect(why.getByText('Refund requests')).toBeVisible()
  await expect(why.getByText(/version 1/)).toBeVisible()
})

test('editing a live automation locks Make live until the new version is tested, and archiving stops it', async ({ page }) => {
  await signupFresh(page, 'Relock')
  await buildRule(page, 'Billing', 'invoice', 'billing')
  await testAndActivate(page, 'Invoice question')

  await page.getByRole('group', { name: 'Action 2' }).getByLabel('Tag').fill('billing-v2')
  await page.getByRole('button', { name: 'Save automation' }).click()
  await expect(page.getByText(/Version 2 is not live yet/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Make live' })).toBeDisabled()

  // The first version is tested, so it can be rolled back to; the new one needs its own test.
  await page.getByRole('region', { name: 'Test it' }).getByLabel('Subject (test ticket)').fill('Invoice again')
  await page.getByRole('region', { name: 'Test it' }).getByRole('button', { name: 'Record as test' }).click()
  await expect(page.getByRole('button', { name: 'Make live' })).toBeEnabled()
  await page.getByRole('button', { name: 'Make live' }).click()
  await expect(page.getByText(/Version 2 is live\./)).toBeVisible()
  await page.getByRole('button', { name: 'Roll back to version 1' }).click()
  await expect(page.getByText(/Version 1 is live|Version 2 is not live yet/)).toBeVisible()

  await page.getByRole('link', { name: 'All automations' }).click()
  await page.getByRole('button', { name: /Archive Billing/ }).click()
  await page.getByRole('link', { name: 'Inbox' }).click()
  await newTicket(page, `Invoice ${uid()}`)
  await expect(page.locator('#prop-priority')).toHaveValue('normal')
  await expect(page.getByRole('region', { name: 'Automations on this ticket' })).toHaveCount(0)
})

test('an agent has no Automations page', async ({ page }) => {
  await login(page, 'agent')
  await expect(page.getByRole('link', { name: 'Automations' })).toHaveCount(0)
})
