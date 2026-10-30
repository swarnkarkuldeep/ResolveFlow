// Captures the README screenshots from the running demo stack (docker compose up).
//   cd frontend && E2E_CHANNEL=chrome node scripts/screenshots.mjs
// Output: ../docs/images/*.png. Uses only the seeded synthetic demo data.
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL ?? 'http://localhost:3000'
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '../../docs/images')
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: process.env.E2E_CHANNEL || undefined })

async function session(role, { theme = 'light' } = {}) {
  const context = await browser.newContext({ viewport: { width: 1360, height: 860 }, deviceScaleFactor: 1.5 })
  await context.addInitScript((t) => localStorage.setItem('rf-theme', t), theme)
  const page = await context.newPage()
  await page.goto(`${BASE}/login`)
  await page.getByLabel('Email').fill(`${role}@brightwork.test`)
  await page.getByLabel('Password').fill('resolveflow-demo')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('heading', { name: 'Inbox', level: 1 }).waitFor()
  return { context, page }
}

const shot = async (page, name) => {
  await page.waitForTimeout(700)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  console.log('captured', name)
}

// Sign-in page
{
  const context = await browser.newContext({ viewport: { width: 1360, height: 860 }, deviceScaleFactor: 1.5 })
  const page = await context.newPage()
  await page.goto(`${BASE}/login`)
  await page.getByRole('button', { name: 'Sign in' }).waitFor()
  await shot(page, 'login')
  // Public contact form, then submit a refund request so the automations have something to explain
  await page.goto(`${BASE}/form/brightwork`)
  await page.getByLabel('Your name').fill('Maya Fernandez')
  await page.getByLabel('Email').fill('maya.fernandez@example.test')
  await page.getByLabel('Subject').fill('Refund for my order')
  await page.getByLabel('Message').fill('The tap I ordered last week arrived cracked. Could I please get a refund?')
  await shot(page, 'public-form')
  await page.getByRole('button', { name: 'Send message' }).click()
  await page.getByText('Thanks, we have your message').waitFor()
  await context.close()
}

// Owner views
{
  const { context, page } = await session('owner')
  await page.waitForTimeout(500)
  await page.getByRole('link', { name: /Refund for my order/ }).first().click()
  await page.getByRole('region', { name: 'Service levels' }).waitFor()
  const why = page.getByRole('region', { name: 'Automations on this ticket' })
  await why.getByText(/Automations that ran/).click()
  await shot(page, 'inbox-ticket')

  await page.getByRole('link', { name: 'Automations', exact: true }).click()
  await page.getByRole('heading', { name: 'Automations', level: 1 }).waitFor()
  await shot(page, 'automations')

  await page.getByRole('link', { name: 'Refund requests' }).click()
  const tester = page.getByRole('region', { name: 'Test it' })
  await tester.getByLabel('Subject (test ticket)').fill('Refund for my order')
  await tester.getByRole('button', { name: 'Run test' }).click()
  await tester.getByText('This automation would run.').waitFor()
  await shot(page, 'automation-editor')

  await page.getByRole('link', { name: 'Service levels', exact: true }).click()
  await page.getByRole('heading', { name: /Service levels/, level: 1 }).waitFor()
  await shot(page, 'service-levels')

  await page.getByRole('link', { name: 'Analytics', exact: true }).click()
  await page.getByRole('heading', { name: 'Analytics', level: 1 }).waitFor()
  await shot(page, 'analytics')

  await page.getByRole('link', { name: 'Search', exact: true }).click()
  await page.getByLabel('Search tickets').fill('refund')
  await page.getByRole('list', { name: 'Search results' }).waitFor()
  await shot(page, 'search')

  await page.getByRole('link', { name: 'People', exact: true }).click()
  await page.getByRole('heading', { name: 'People', level: 1 }).waitFor()
  await shot(page, 'people')

  await page.getByRole('link', { name: 'Privacy', exact: true }).click()
  await page.getByRole('heading', { name: 'Privacy', level: 1 }).waitFor()
  await shot(page, 'privacy')
  await context.close()
}

// An agent's notifications
{
  const { context, page } = await session('agent')
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /^Notifications/ }).click()
  await page.getByRole('heading', { name: 'Notifications', level: 1 }).waitFor()
  await shot(page, 'notifications')
  await context.close()
}

// Dark theme
{
  const { context, page } = await session('owner', { theme: 'dark' })
  await page.getByRole('list').first().getByRole('link').first().click()
  await page.getByRole('region', { name: 'Service levels' }).waitFor()
  await shot(page, 'inbox-dark')
  await context.close()
}

await browser.close()
