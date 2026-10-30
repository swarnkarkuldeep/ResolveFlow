import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { AuthProvider } from './app/auth'
import { ToastProvider } from './app/Toasts'
import type { Me, Role } from './lib/types'
import { permissionsFor } from './lib/permissions'

type Reply = { status?: number; body?: unknown }
export type Handler = (url: string, init: RequestInit) => Reply | undefined

export interface FetchStub {
  calls: { url: string; init: RequestInit }[]
  fn: ReturnType<typeof vi.fn>
}

/** Stubs `fetch` at the network edge; everything above it (api client, auth, UI) is real. */
export function stubFetch(handler: Handler): FetchStub {
  const calls: FetchStub['calls'] = []
  const fn = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init: init ?? {} })
    const reply = handler(u, init ?? {}) ?? { status: 404, body: { detail: { code: 'not_found', message: 'Not found.' } } }
    const status = reply.status ?? 200
    return { ok: status < 400, status, text: async () => (reply.body === undefined ? '' : JSON.stringify(reply.body)) } as Response
  })
  vi.stubGlobal('fetch', fn)
  return { calls, fn }
}

export function meFor(role: Role, overrides: Partial<Me> = {}): Me {
  return {
    user: { id: 'u1', email: `${role}@brightwork.test`, name: `${role[0].toUpperCase()}${role.slice(1)} Person` },
    workspaces: [{ id: 'w1', name: 'Brightwork Studio', slug: 'brightwork', role }],
    active_workspace: { id: 'w1', name: 'Brightwork Studio', slug: 'brightwork', role },
    role,
    permissions: permissionsFor(role),
    csrf_token: 'csrf-test',
    ...overrides,
  }
}

export function renderApp(ui: ReactElement, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          <AuthProvider>{ui}</AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
