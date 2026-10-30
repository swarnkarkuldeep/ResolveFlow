import { expect, test } from '@playwright/test'

import { login, mailTo, newTicket, otherContext, signupFresh, uid } from './helpers'

test('invite a teammate by email, accept in a fresh browser, and see role-appropriate navigation', async ({ page, browser, request }) => {
  await signupFresh(page, 'Team')
  await page.getByRole('link', { name: 'People' }).click()
  const email = `agent-${uid()}@e2e.test`
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Role', { exact: true }).selectOption('agent')
  await page.getByRole('button', { name: 'Send invitation' }).click()
  await expect(page.getByRole('region', { name: 'Pending invitations' }).getByText(email)).toBeVisible()

  const mail = await mailTo(request, email, 'invited you')
  const link = mail.text.match(/https?:\/\/\S+accept-invite\?token=[\w-]+/)?.[0]
  expect(link, 'invitation email contains the accept link').toBeTruthy()

  const { context, page: invitee } = await otherContext(browser)
  await invitee.goto(link!)
  await invitee.getByLabel('Your name').fill('Ana Agent')
  await invitee.getByLabel('Password').fill('correct-horse-battery')
  await invitee.getByRole('button', { name: 'Join workspace' }).click()
  await expect(invitee.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
  const nav = invitee.getByRole('navigation', { name: 'Main' })
  await expect(nav.getByRole('link', { name: 'People' })).toBeVisible()
  await expect(nav.getByRole('link', { name: 'Channels' })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: 'Audit log' })).toHaveCount(0)

  // The same link cannot be used twice.
  const again = await otherContext(browser)
  await again.page.goto(link!)
  await again.page.getByLabel('Your name').fill('Someone Else')
  await again.page.getByLabel('Password').fill('correct-horse-battery')
  await again.page.getByRole('button', { name: 'Join workspace' }).click()
  await expect(again.page.getByRole('alert')).toContainText('expired or was already used')

  // The owner sees the new member, can demote them, and the change is audited.
  await page.reload()
  await expect(page.getByText('Ana Agent')).toBeVisible()
  const changed = page.waitForResponse((r) => r.url().includes('/api/members/') && r.request().method() === 'PATCH')
  await page.getByLabel('Role for Ana Agent').selectOption('viewer')
  await changed
  await page.getByRole('link', { name: 'Audit log' }).click()
  await expect(page.getByText('Role: agent → viewer')).toBeVisible()
  await expect(page.getByText(`Invited ${email} as agent`)).toBeVisible()
  await context.close()
  await again.context.close()
})

test('a viewer can read tickets but has no composer, no editing and no bulk selection', async ({ page }) => {
  await login(page, 'viewer')
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await page.getByRole('link').filter({ hasText: /./ }).filter({ has: page.locator('span.truncate') }).first().click()
  await expect(page.getByRole('heading', { level: 2 })).toBeVisible()
  await expect(page.getByText(/view-only access/)).toBeVisible()
  await expect(page.getByLabel('Message')).toHaveCount(0)
  await expect(page.locator('#prop-status')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'New ticket' })).toHaveCount(0)
})

test('deactivating a member signs them out immediately', async ({ page, browser, request }) => {
  await signupFresh(page, 'Deactivate')
  await page.getByRole('link', { name: 'People' }).click()
  const email = `temp-${uid()}@e2e.test`
  await page.getByLabel('Email').fill(email)
  await page.getByRole('button', { name: 'Send invitation' }).click()
  const mail = await mailTo(request, email, 'invited you')
  const link = mail.text.match(/https?:\/\/\S+accept-invite\?token=[\w-]+/)![0]
  const member = await otherContext(browser)
  await member.page.goto(link)
  await member.page.getByLabel('Your name').fill('Temp Person')
  await member.page.getByLabel('Password').fill('correct-horse-battery')
  await member.page.getByRole('button', { name: 'Join workspace' }).click()
  await expect(member.page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()

  await page.reload()
  await page.getByRole('button', { name: 'Deactivate Temp Person' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Deactivate' }).click()
  await expect(page.getByText('Deactivated')).toBeVisible()

  await member.page.reload()
  await expect(member.page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await member.context.close()
})

test('another workspace cannot open this workspace’s ticket by its link', async ({ page, browser }) => {
  await signupFresh(page, 'Alpha')
  await newTicket(page, `Private ${uid()}`)
  const url = page.url()
  const { context, page: outsider } = await otherContext(browser)
  await signupFresh(outsider, 'Bravo')
  await outsider.goto(url)
  await expect(outsider.getByText('Ticket not found')).toBeVisible()
  await expect(outsider.getByText(/Private/)).toHaveCount(0)
  await context.close()
})

test('the audit log shows what was just done and exports a CSV', async ({ page }) => {
  await login(page, 'owner')
  const subject = `Audited ${uid()}`
  await newTicket(page, subject)
  await page.getByRole('link', { name: 'Audit log' }).click()
  await expect(page.getByText('Ticket created (manual)').first()).toBeVisible()
  await page.getByLabel('Item type').selectOption('ticket')
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Export CSV' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe('audit-log.csv')
})
