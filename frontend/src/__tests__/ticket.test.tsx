import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import type { Message, Role, TicketDetail } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'
import type { Handler } from '../test-utils'

beforeEach(() => window.localStorage.clear())
afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

function message(n: number, o: Partial<Message> = {}): Message {
  return {
    id: `m${n}`,
    kind: 'public',
    direction: 'inbound',
    body: `Body ${n}`,
    created_at: new Date(Date.now() - (10 - n) * 600_000).toISOString(),
    delivery_status: 'none',
    author: { type: 'customer', name: 'Cora Customer' },
    ...o,
  }
}

function detail(o: Partial<TicketDetail> = {}): TicketDetail {
  return {
    id: 't1',
    number: 7,
    subject: 'Leaking tap in the kitchen',
    status: 'open',
    priority: 'normal',
    channel: 'email',
    requester: { id: 'c1', email: 'cora@customer.test', name: 'Cora Customer' },
    assignee: null,
    tags: ['billing'],
    snippet: 'x',
    last_activity_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    possible_duplicate_of: null,
    merged_into_id: null,
    messages: [message(1)],
    ...o,
  }
}

function server(t: TicketDetail, role: Role = 'owner', opts: { failPatch?: boolean } = {}) {
  const state = { t: structuredClone(t), posted: [] as unknown[], patched: [] as unknown[], merged: [] as unknown[] }
  const handler: Handler = (url, init) => {
    const u = new URL(url, 'http://x')
    const method = init.method ?? 'GET'
    if (u.pathname === '/api/auth/me') return { body: meFor(role) }
    if (u.pathname === '/api/members')
      return { body: [{ user_id: 'u1', email: 'o@b.test', name: 'Owner Person', role: 'owner', active: true }, { user_id: 'u2', email: 'l@b.test', name: 'Lena Okafor', role: 'agent', active: true }] }
    if (u.pathname === '/api/tickets' && method === 'GET') {
      const others = [state.t, { ...state.t, id: 't2', number: 8, subject: 'Other open ticket' }]
      return { body: { items: others, next_cursor: null } }
    }
    if (u.pathname === `/api/tickets/${state.t.id}` && method === 'GET') return { body: state.t }
    if (u.pathname === `/api/tickets/${state.t.id}` && method === 'PATCH') {
      if (opts.failPatch) return { status: 422, body: { detail: { code: 'bad_assignee', message: 'That change was rejected.' } } }
      const body = JSON.parse(String(init.body))
      state.patched.push(body)
      if ('assignee_id' in body) state.t.assignee = body.assignee_id ? { id: body.assignee_id, name: 'Owner Person' } : null
      if ('tags' in body) state.t.tags = body.tags
      if ('status' in body) state.t.status = body.status
      if ('priority' in body) state.t.priority = body.priority
      return { body: { ...state.t, messages: undefined } }
    }
    if (u.pathname === `/api/tickets/${state.t.id}/messages` && method === 'POST') {
      const body = JSON.parse(String(init.body))
      state.posted.push(body)
      const m = message(state.t.messages.length + 1, {
        kind: body.kind,
        direction: body.kind === 'note' ? 'internal' : 'outbound',
        body: body.body,
        delivery_status: body.kind === 'note' ? 'none' : 'queued',
        author: { type: 'user', name: 'Owner Person' },
      })
      state.t.messages.push(m)
      return { body: m }
    }
    if (u.pathname === `/api/tickets/${state.t.id}/merge`) {
      state.merged.push(JSON.parse(String(init.body)))
      return { body: { ...state.t, id: 't2' } }
    }
    if (u.pathname === `/api/tickets/${state.t.id}/activity`)
      return {
        body: [
          { action: 'ticket.created', created_at: new Date().toISOString(), before: null, after: { channel: 'email' }, actor_type: 'system', actor_name: 'System' },
          { action: 'ticket.updated', created_at: new Date().toISOString(), before: { priority: 'normal' }, after: { priority: 'urgent' }, actor_type: 'user', actor_name: 'Owner Person' },
        ],
      }
  }
  return { state, handler }
}

const open = async (t: TicketDetail, role: Role = 'owner', opts = {}) => {
  const s = server(t, role, opts)
  const stub = stubFetch(s.handler)
  renderApp(<AppRoutes />, '/inbox/t1')
  await screen.findByRole('heading', { name: t.subject })
  return { ...s, stub }
}

describe('thread', () => {
  it('renders message bodies as inert text, never as HTML', async () => {
    await open(detail({ messages: [message(1, { body: '<img src=x onerror=alert(1)> and <script>alert(2)</script>' })] }))
    const thread = screen.getByRole('region', { name: 'Conversation' })
    expect(thread.querySelector('img')).toBeNull()
    expect(thread.querySelector('script')).toBeNull()
    expect(within(thread).getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument()
  })

  it('marks internal notes plainly and shows delivery state for replies', async () => {
    await open(
      detail({
        messages: [
          message(1),
          message(2, { kind: 'note', direction: 'internal', body: 'Call the supplier', author: { type: 'user', name: 'Lena Okafor' } }),
          message(3, { direction: 'outbound', body: 'On our way', delivery_status: 'sent', author: { type: 'user', name: 'Lena Okafor' } }),
          message(4, { direction: 'outbound', body: 'Second try', delivery_status: 'failed', author: { type: 'user', name: 'Lena Okafor' } }),
          message(5, { direction: 'outbound', body: 'Third', delivery_status: 'queued', author: { type: 'user', name: 'Lena Okafor' } }),
        ],
      }),
    )
    const thread = within(screen.getByRole('region', { name: 'Conversation' }))
    expect(thread.getByText('Internal note')).toBeInTheDocument()
    expect(thread.getByText('Sent')).toBeInTheDocument()
    expect(thread.getByText(/couldn.t send/i)).toBeInTheDocument()
    expect(thread.getByText('Sending…')).toBeInTheDocument()
  })
})

describe('composer', () => {
  it('sends a reply and shows it in the thread', async () => {
    const { state } = await open(detail())
    await userEvent.type(screen.getByLabelText('Message'), 'We will be there Tuesday.')
    await userEvent.click(screen.getByRole('button', { name: 'Send reply' }))
    await waitFor(() => expect(state.posted).toEqual([{ body: 'We will be there Tuesday.', kind: 'public', set_pending: false }]))
    expect(await screen.findByText('We will be there Tuesday.')).toBeInTheDocument()
    expect(screen.getByLabelText('Message')).toHaveValue('')
  })

  it('Ctrl+Enter sends, and the waiting-on-customer box is honoured', async () => {
    const { state } = await open(detail())
    await userEvent.click(screen.getByLabelText(/waiting on customer/i))
    await userEvent.type(screen.getByLabelText('Message'), 'Can you send a photo?')
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(state.posted).toEqual([{ body: 'Can you send a photo?', kind: 'public', set_pending: true }]))
  })

  it('adds an internal note from the Note tab', async () => {
    const { state } = await open(detail())
    await userEvent.click(screen.getByRole('tab', { name: 'Internal note' }))
    await userEvent.type(screen.getByLabelText('Message'), 'Customer is on the premium plan')
    await userEvent.click(screen.getByRole('button', { name: 'Add note' }))
    await waitFor(() => expect(state.posted).toEqual([{ body: 'Customer is on the premium plan', kind: 'note', set_pending: false }]))
  })

  it('keeps an unsent draft per ticket and restores it', async () => {
    await open(detail())
    await userEvent.type(screen.getByLabelText('Message'), 'half a thought')
    expect(window.localStorage.getItem('rf-draft:t1:public')).toBe('half a thought')
    vi.unstubAllGlobals()
    cleanup()
    await open(detail())
    expect(screen.getByLabelText('Message')).toHaveValue('half a thought')
  })

  it('is read-only with an explanation for a viewer', async () => {
    await open(detail(), 'viewer')
    expect(screen.queryByLabelText('Message')).not.toBeInTheDocument()
    expect(screen.getByText(/view-only access/i)).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Status' })).not.toBeInTheDocument()
  })

  it('r moves focus to the composer', async () => {
    await open(detail())
    await userEvent.keyboard('r')
    expect(screen.getByLabelText('Message')).toHaveFocus()
  })
})

describe('properties', () => {
  it('changes priority and status through the real API', async () => {
    const { state } = await open(detail())
    await userEvent.selectOptions(screen.getByLabelText('Priority', { selector: '#prop-priority' }), 'urgent')
    await waitFor(() => expect(state.patched).toContainEqual({ priority: 'urgent' }))
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'resolved')
    await waitFor(() => expect(state.patched).toContainEqual({ status: 'resolved' }))
  })

  it('assigns to me, then adds and removes a tag', async () => {
    const { state } = await open(detail())
    await userEvent.click(screen.getByRole('button', { name: 'Assign to me' }))
    await waitFor(() => expect(state.patched).toContainEqual({ assignee_id: 'u1' }))
    await userEvent.type(screen.getByLabelText('Add tag'), 'vip{Enter}')
    await waitFor(() => expect(state.patched).toContainEqual({ tags: ['billing', 'vip'] }))
    await userEvent.click(screen.getByRole('button', { name: 'Remove tag billing' }))
    await waitFor(() => expect(state.patched).toContainEqual({ tags: ['vip'] }))
  })

  it('reverts the control and explains when the server rejects a change', async () => {
    await open(detail(), 'owner', { failPatch: true })
    const status = screen.getByLabelText('Status')
    await userEvent.selectOptions(status, 'resolved')
    expect(await screen.findByRole('alert')).toHaveTextContent('That change was rejected.')
    await waitFor(() => expect(status).toHaveValue('open'))
  })
})

describe('merge and history', () => {
  it('merges into another open ticket after confirmation', async () => {
    const { state } = await open(detail())
    await userEvent.click(screen.getByRole('button', { name: 'Merge…' }))
    const dialog = await screen.findByRole('dialog', { name: /merge ticket/i })
    expect(within(dialog).queryByRole('option', { name: /#7/ })).not.toBeInTheDocument()
    await userEvent.selectOptions(within(dialog).getByLabelText('Merge into'), 't2')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Merge tickets' }))
    await waitFor(() => expect(state.merged).toEqual([{ into_id: 't2' }]))
  })

  it('shows the real audit history in plain language', async () => {
    await open(detail())
    await userEvent.click(screen.getByText('History'))
    expect(await screen.findByText(/priority: normal → urgent/i)).toBeInTheDocument()
    expect(screen.getByText(/ticket created/i)).toBeInTheDocument()
    expect(screen.getAllByText('Owner Person').length).toBeGreaterThan(0)
  })

  it('explains a ticket that was merged away', async () => {
    await open(detail({ merged_into_id: 't2', status: 'closed', messages: [] }))
    expect(screen.getByText(/merged into another ticket/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Merge…' })).not.toBeInTheDocument()
  })
})
