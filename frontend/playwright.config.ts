import { defineConfig } from '@playwright/test'

// Runs against the real stack (docker compose up). Locally set E2E_CHANNEL=chrome to reuse the
// installed Chrome; CI installs Playwright's chromium instead.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    channel: process.env.E2E_CHANNEL || undefined,
    trace: 'retain-on-failure',
    viewport: { width: 1360, height: 860 },
  },
})
