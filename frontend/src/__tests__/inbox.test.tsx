import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import { KEYS } from '../features/inbox/keys'
import type { Role, TicketItem } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'
import type { Handler } from '../test-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

function ticket(n: number, overrides: Partial<TicketItem> = {}): TicketItem {
  return {
    id: `t${n}`,
    number: n,
    subject: `Subject ${n}`,
    status: 'open',
    priority: 'normal',
    channel: 'email',
    requester: { id: `c${n}`, email: `c${n}@customer.test`, name: `Customer ${n}` },
    assignee: null,
    tags: [],
    snippet: `Snippet for ${n}`,
    last_activity_at: new Date(Date.now() - n * 3600_000).toISOString(),
    created_at: new Date(Date.now() - n * 3600_000).toISOString(),
    possible_duplicate_of: null,
    merged_into_id: null,
    ...overrides,
  }
}

/** A tiny in-memory server for the endpoints the inbox uses (fetch is the only thing faked). */
function server(initial: TicketItem[], role: Role = 'owner', failBulk = false) {
  const data = [...initial]
  const handler: Handler = (url, init) => {
    const u = new URL(url, 'http://x')
    const method = init.method ?? 'GET'
    if (u.pathname === '/api/auth/me') return { body: meFor(role) }
    if (u.pathname === '/api/members')
      return { body: [{ user_id: 'u1', email: 'a@b.test', name: 'Owner Person', role: 'owner', active: true }, { user_id: 'u2', email: 'l@b.test', name: 'Lena Okafor', role: 'agent', active: true }] }
    if (u.pathname === '/api/tickets' && method === 'GET') {
      const statuses = u.searchParams.get('status')?.split(',')
      const assignee = u.searchParams.get('assignee')
      const priority = u.searchParams.get('priority')
      const items = data.filter(
        (t) =>
          (!statuses || statuses.includes(t.status)) &&
          (!assignee || (assignee === 'none' ? t.assignee === null : assignee === 'me' ? t.assignee?.id === 'u1' : true)) &&
          (!priority || t.priority === priority),
      )
      return { body: { items, next_cursor: null } }
    }
    if (u.pathname === '/api/tickets/bulk') {
      if (failBulk) return { status: 422, body: { detail: { code: 'bad_assignee', message: 'That person is not an active member of this workspace.' } } }
      const body = JSON.parse(String(init.body))
      for (const t of data) if (body.ids.includes(t.id) && body.action === 'status') t.status = body.value
      return { body: { updated: body.ids, skipped: [] } }
    }
    const m = u.pathname.match(/^\/api\/tickets\/([^/]+)$/)
    if (m && method === 'PATCH') {
      const t = data.find((x) => x.id === m[1])!
      Object.assign(t, JSON.parse(String(init.body)))
      return { body: t }
    }
    if (m && method === 'GET') return { body: { ...data.find((x) => x.id === m[1]), messages: [] } }
    if (/^\/api\/tickets\/[^/]+\/activity$/.test(u.pathname)) return { body: [] }
  }
  return { data, handler }
}

const rows = () => screen.getAllByRole('listitem')

describe('inbox', () => {
  it('switches views and requests the matching tickets', async () => {
    const s = server([ticket(1), ticket(2, { assignee: { id: 'u1', name: 'Owner Person' } })])
    const stub = stubFetch(s.handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.click(screen.getByRole('tab', { name: 'Unassigned' }))
    await waitFor(() => expect(stub.calls.some((c) => c.url.includes('assignee=none'))).toBe(true))
    expect(await screen.findByText('Subject 1')).toBeInTheDocument()
    expect(screen.queryByText('Subject 2')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Mine' }))
    expect(await screen.findByText('Subject 2')).toBeInTheDocument()
  })

  it('moves with j/k and opens the highlighted ticket with Enter', async () => {
    const s = server([ticket(1), ticket(2), ticket(3)])
    stubFetch(s.handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.keyboard('j')
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByTestId('ticket-pane')).toHaveAttribute('data-ticket-id', 't2')
    await userEvent.keyboard('k')
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByTestId('ticket-pane')).toHaveAttribute('data-ticket-id', 't1')
  })

  it('selects with x and shows the bulk bar with the count', async () => {
    stubFetch(server([ticket(1), ticket(2)]).handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.keyboard('x')
    expect(await screen.findByText('1 selected')).toBeInTheDocument()
    await userEvent.keyboard('j')
    await userEvent.keyboard('x')
    expect(await screen.findByText('2 selected')).toBeInTheDocument()
  })

  it('bulk status posts the exact request and updates the list', async () => {
    const stub = stubFetch(server([ticket(1), ticket(2)]).handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.keyboard('x')
    await userEvent.selectOptions(await screen.findByLabelText('Set status'), 'resolved')
    await waitFor(() => {
      const call = stub.calls.find((c) => c.url === '/api/tickets/bulk')
      expect(call && JSON.parse(String(call.init.body))).toEqual({ ids: ['t1'], action: 'status', value: 'resolved' })
    })
    await waitFor(() => expect(screen.queryByText('Subject 1')).not.toBeInTheDocument())
    expect(screen.getByText('Subject 2')).toBeInTheDocument()
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument()
  })

  it('rolls back and explains when the server rejects a bulk change', async () => {
    stubFetch(server([ticket(1), ticket(2)], 'owner', true).handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.keyboard('x')
    await userEvent.selectOptions(await screen.findByLabelText('Set status'), 'resolved')
    expect(await screen.findByRole('alert')).toHaveTextContent('not an active member')
    expect(screen.getByText('Subject 1')).toBeInTheDocument()
  })

  it('e resolves and a assigns the highlighted ticket', async () => {
    const stub = stubFetch(server([ticket(1), ticket(2)]).handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.keyboard('a')
    await waitFor(() => {
      const call = stub.calls.find((c) => c.init.method === 'PATCH' && c.url === '/api/tickets/t1')
      expect(call && JSON.parse(String(call.init.body))).toEqual({ assignee_id: 'u1' })
    })
    await userEvent.keyboard('e')
    await waitFor(() => {
      const bodies = stub.calls.filter((c) => c.init.method === 'PATCH').map((c) => JSON.parse(String(c.init.body)))
      expect(bodies).toContainEqual({ status: 'resolved' })
    })
  })

  it('shows view-specific empty states with a next step', async () => {
    stubFetch(server([]).handler)
    renderApp(<AppRoutes />, '/inbox')
    expect(await screen.findByText('No open tickets')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Unassigned' }))
    expect(await screen.findByText('Nothing waiting')).toBeInTheDocument()
    expect(screen.getByText(/new requests land here/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Mine' }))
    expect(await screen.findByText('Nothing assigned to you')).toBeInTheDocument()
  })

  it('lists every keyboard shortcut in the help dialog, and each one is bound', async () => {
    stubFetch(server([ticket(1)]).handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    await userEvent.keyboard('?')
    const dialog = await screen.findByRole('dialog', { name: /keyboard shortcuts/i })
    for (const k of KEYS) {
      expect(within(dialog).getByText(k.description)).toBeInTheDocument()
      expect(typeof k.run).toBe('function')
    }
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('does not offer selection or bulk actions to a viewer', async () => {
    stubFetch(server([ticket(1)], 'viewer').handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    await userEvent.keyboard('x')
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument()
  })

  it('does not hijack keys while typing in a field', async () => {
    stubFetch(server([ticket(1), ticket(2)]).handler)
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('Subject 1')
    const select = screen.getByLabelText('Priority')
    select.focus()
    await userEvent.keyboard('x')
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument()
    expect(rows().length).toBeGreaterThan(0)
  })
})
