import { expect, test } from '@playwright/test'

import { otherContext, signupFresh, uid } from './helpers'

test('a customer submits the public form without signing in and the team sees the ticket', async ({ page, browser }) => {
  await signupFresh(page, 'Form')
  await page.getByRole('link', { name: 'Channels' }).click()
  const formUrl = (await page.getByText(/\/form\/[\w-]+$/).first().textContent())!.trim()
  expect(formUrl).toContain('/form/')

  const { context, page: customer } = await otherContext(browser)
  await customer.goto(new URL(formUrl).pathname)
  await expect(customer.getByRole('heading', { name: /Contact Form Workspace/ })).toBeVisible()
  const subject = `Quote ${uid()}`
  await customer.getByLabel('Your name').fill('Frankie Form')
  await customer.getByLabel('Email').fill('frankie@customer.test')
  await customer.getByLabel('Subject').fill(subject)
  await customer.getByLabel('Message').fill('Could someone call me about a bathroom refit?')
  await customer.getByRole('button', { name: 'Send message' }).click()
  await expect(customer.getByText('Thanks, we have your message')).toBeVisible()
  await expect(customer.getByText('#1')).toBeVisible()

  await page.getByRole('link', { name: 'Inbox' }).click()
  await page.getByRole('link', { name: new RegExp(subject) }).click()
  await expect(page.getByRole('heading', { name: subject, level: 2 })).toBeVisible()
  await expect(page.getByText('Web form', { exact: true })).toBeVisible()
  await context.close()
})

test('the form says plainly when it does not exist', async ({ page }) => {
  await page.goto('/form/definitely-not-a-workspace')
  await expect(page.getByText('This form isn’t available')).toBeVisible()
})
