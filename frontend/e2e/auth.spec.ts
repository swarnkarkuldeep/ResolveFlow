import { expect, test } from '@playwright/test'

import { DEMO_PASSWORD, login, signupFresh, uid } from './helpers'

test('a new owner can create a workspace and then sign out and back in', async ({ page }) => {
  const { email } = await signupFresh(page)
  await expect(page.getByText('No open tickets')).toBeVisible()
  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('correct-horse-battery')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
})

test('a wrong password gets one plain message and no hint about which field was wrong', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill(`nobody-${uid()}@e2e.test`)
  await page.getByLabel('Password').fill('not-the-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toHaveText('Email or password is incorrect.')
})

test('the demo owner can sign in and sees the seeded inbox', async ({ page }) => {
  await login(page, 'owner')
  await expect(page.getByRole('link', { name: /Password reset email missing|Menu PDF out of date|Simulated hello/ }).first()).toBeVisible()
  expect(DEMO_PASSWORD.length).toBeGreaterThan(9)
})

test('signed-out visitors are sent to sign in, and the theme toggle persists', async ({ page }) => {
  await page.goto('/inbox')
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await login(page, 'owner')
  const before = await page.evaluate(() => document.documentElement.dataset.theme)
  await page.getByRole('button', { name: /Switch to (light|dark) theme/ }).click()
  const after = await page.evaluate(() => document.documentElement.dataset.theme)
  expect(after).not.toBe(before)
  await page.reload()
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(after)
})
