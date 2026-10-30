import { expect } from '@playwright/test'
import type { APIRequestContext, Browser, Page } from '@playwright/test'

export const MAILPIT = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'
export const DEMO_PASSWORD = 'resolveflow-demo'

export type DemoRole = 'owner' | 'admin' | 'agent' | 'viewer'

export const uid = () => Math.random().toString(36).slice(2, 8)

export async function login(page: Page, role: DemoRole = 'owner') {
  await page.goto('/login')
  await page.getByLabel('Email').fill(`${role}@brightwork.test`)
  await page.getByLabel('Password').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
}

/** Creates a fresh workspace (and owner) so a test never depends on, or pollutes, the demo data. */
export async function signupFresh(page: Page, label = 'E2E') {
  const id = uid()
  await page.goto('/signup')
  await page.getByLabel('Your name').fill(`${label} Owner ${id}`)
  await page.getByLabel('Workspace name').fill(`${label} Workspace ${id}`)
  await page.getByLabel('Email').fill(`owner-${id}@e2e.test`)
  await page.getByLabel('Password').fill('correct-horse-battery')
  await page.getByRole('button', { name: 'Create workspace' }).click()
  await expect(page.getByRole('heading', { name: 'Inbox', level: 1 })).toBeVisible()
  return { id, email: `owner-${id}@e2e.test` }
}

export async function newTicket(page: Page, subject: string, email = `cust-${uid()}@customer.test`, body = 'Please help, this is an end-to-end test request.') {
  await page.getByRole('button', { name: 'New ticket' }).click()
  const dialog = page.getByRole('dialog', { name: 'New ticket' })
  await dialog.getByLabel('Customer email').fill(email)
  await dialog.getByLabel('Customer name').fill('Cora E2E')
  await dialog.getByLabel('Subject').fill(subject)
  await dialog.getByLabel('What happened').fill(body)
  await dialog.getByRole('button', { name: 'Create ticket' }).click()
  await expect(page.getByRole('heading', { name: subject, level: 2 })).toBeVisible()
  return email
}

export async function mailTo(request: APIRequestContext, address: string, subjectPart: string) {
  let found: { Subject: string; Snippet: string; ID: string } | undefined
  await expect
    .poll(
      async () => {
        const res = await request.get(`${MAILPIT}/api/v1/messages?limit=100`)
        const body = (await res.json()) as { messages: { Subject: string; Snippet: string; ID: string; To: { Address: string }[] }[] }
        found = body.messages.find((m) => m.To.some((t) => t.Address === address) && m.Subject.includes(subjectPart))
        return !!found
      },
      { message: `mail to ${address} with subject containing "${subjectPart}"`, timeout: 20_000 },
    )
    .toBe(true)
  const full = await (await request.get(`${MAILPIT}/api/v1/message/${found!.ID}`)).json()
  return { subject: found!.Subject, text: String(full.Text) }
}

export async function otherContext(browser: Browser) {
  const context = await browser.newContext()
  return { context, page: await context.newPage() }
}
