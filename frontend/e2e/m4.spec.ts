import { expect, test } from '@playwright/test'

import type { Page } from '@playwright/test'

import { login, newTicket, otherContext, uid } from './helpers'

const nav = (page: Page, name: RegExp | string) => page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name })

test('search finds a ticket by what the customer wrote and opens it', async ({ page }) => {
  await login(page, 'owner')
  const word = `zebracrossing${uid()}`
  await newTicket(page, `Search target ${uid()}`, undefined, `The ${word} outside the shop is broken.`)
  await nav(page, 'Search').click()
  await page.getByLabel('Search tickets').fill(word)
  const results = page.getByRole('list', { name: 'Search results' })
  await expect(results.locator('mark')).toHaveText(word)
  await expect(results.getByText('Matched a message')).toBeVisible()
  await results.getByRole('link', { name: /Search target/ }).click()
  await expect(page.getByRole('heading', { name: /Search target/, level: 2 })).toBeVisible()
  await nav(page, 'Search').click()
  await page.getByLabel('Search tickets').fill(`nomatch${uid()}`)
  await expect(page.getByText(/No tickets match/)).toBeVisible()
})

test('assigning a ticket notifies the assignee, who can open and read it', async ({ page, browser }) => {
  await login(page, 'owner')
  const subject = `Notify me ${uid()}`
  await newTicket(page, subject)
  const agent = await otherContext(browser)
  await login(agent.page, 'agent')
  await page.locator('#prop-assignee').selectOption({ label: 'Lena Okafor' })
  await agent.page.goto('/notifications')
  const item = agent.page.getByRole('button', { name: new RegExp(`Assigned to you`) }).first()
  await expect(item).toBeVisible({ timeout: 30_000 })
  await expect(nav(agent.page, /Notifications, \d+ unread/)).toBeVisible()
  await item.click()
  await expect(agent.page.getByRole('heading', { level: 2 })).toBeVisible()
  await agent.page.goto('/notifications')
  const all = agent.page.getByRole('button', { name: 'Mark all read' })
  if (await all.isEnabled()) await all.click()
  await expect(agent.page.getByText('You are all caught up.')).toBeVisible()
  await agent.context.close()
})

test('notification settings persist across a reload', async ({ page }) => {
  await login(page, 'owner')
  await nav(page, /^Notifications/).click()
  const box = () => page.getByRole('checkbox', { name: 'A customer replies on my ticket: by email' })
  const before = await box().isChecked()
  await box().click()
  await expect(page.getByText('Notification settings saved')).toBeVisible()
  await page.reload()
  if (before) await expect(box()).not.toBeChecked()
  else await expect(box()).toBeChecked()
  await box().click() // put it back so the demo data stays as it was
  await expect(box()).toBeChecked({ checked: before })
})

test('analytics shows the demo workspace and changes range; the requester links to a history page', async ({ page }) => {
  await login(page, 'owner')
  await nav(page, 'Analytics').click()
  await expect(page.getByRole('heading', { name: 'Analytics', level: 1 })).toBeVisible()
  const summary = page.getByRole('region', { name: 'Service levels' })
  await expect(summary.getByText('First response on time')).toBeVisible()
  await page.getByRole('button', { name: 'Last 7 days' }).click()
  await expect(page.getByRole('button', { name: 'Last 7 days' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('region', { name: 'Volume' })).toBeVisible()

  await page.getByRole('link', { name: 'Inbox' }).click()
  await page.getByRole('list').first().getByRole('link').first().click()
  await page.getByRole('link', { name: /@/ }).first().click()
  await expect(page.getByRole('list', { name: 'Ticket history' })).toBeVisible()
})

test('an agent has no Analytics page', async ({ page }) => {
  await login(page, 'agent')
  await expect(nav(page, 'Analytics')).toHaveCount(0)
  await page.goto('/analytics')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
})
