import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { StatusPage } from '../pages/StatusPage'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <StatusPage />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('StatusPage', () => {
  it('renders each check from the API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          status: 'degraded',
          checks: [
            { name: 'db', ok: true, detail: 'ok' },
            { name: 'scheduler', ok: false, detail: 'stale: 300s' },
          ],
        }),
      }),
    )
    renderPage()
    expect(await screen.findByText('db')).toBeInTheDocument()
    expect(await screen.findByText('scheduler')).toBeInTheDocument()
    expect(screen.getByText('stale: 300s')).toBeInTheDocument()
  })

  it('shows an error state when the API is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')))
    renderPage()
    expect(await screen.findByText(/unable to reach/i)).toBeInTheDocument()
  })
})
