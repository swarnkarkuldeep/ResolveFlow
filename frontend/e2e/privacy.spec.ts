import { expect, test } from '@playwright/test'

import { login } from './helpers'

test('an owner can set and clear a retention period, and agents have no Privacy page', async ({ page }) => {
  await login(page, 'owner')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Privacy' }).click()
  const select = page.getByLabel(/Remove content of resolved/)
  await select.selectOption('365')
  await page.getByRole('button', { name: 'Save retention' }).click()
  await expect(page.getByText('Retention saved')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel(/Remove content of resolved/)).toHaveValue('365')
  await expect(page.getByText(/tickets? (is|are) past the limit|No tickets are past the limit/)).toBeVisible()
  await page.getByLabel(/Remove content of resolved/).selectOption('')
  await page.getByRole('button', { name: 'Save retention' }).click()
  await expect(page.getByText('Retention saved')).toBeVisible()
})

test('an agent cannot open Privacy', async ({ page }) => {
  await login(page, 'agent')
  await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Privacy' })).toHaveCount(0)
  await page.goto('/privacy')
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
})
