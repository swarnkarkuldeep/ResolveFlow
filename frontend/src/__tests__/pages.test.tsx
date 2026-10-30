import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import type { Member, Role } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'
import type { Handler } from '../test-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const members: Member[] = [
  { user_id: 'u1', email: 'owner@brightwork.test', name: 'Priya Raman', role: 'owner', active: true },
  { user_id: 'u2', email: 'agent@brightwork.test', name: 'Lena Okafor', role: 'agent', active: true },
  { user_id: 'u3', email: 'old@brightwork.test', name: 'Tom Alvarez', role: 'viewer', active: false },
]

function base(role: Role, extra: Handler): Handler {
  return (url, init) => {
    const u = new URL(url, 'http://x')
    if (u.pathname === '/api/auth/me') return { body: meFor(role) }
    return extra(url, init)
  }
}

describe('people', () => {
  it('invites a teammate, shows the pending invitation and lets you copy its link', async () => {
    const invites: unknown[] = []
    const stored: unknown[] = []
    const stub = stubFetch(
      base('owner', (url, init) => {
        if (url === '/api/members') return { body: members }
        if (url === '/api/invitations' && (init.method ?? 'GET') === 'GET') return { body: stored }
        if (url === '/api/invitations' && init.method === 'POST') {
          invites.push(JSON.parse(String(init.body)))
          const created = { id: 'i1', email: 'ana@x.test', role: 'agent', expires_at: new Date(Date.now() + 6 * 86400000).toISOString() }
          stored.push(created)
          return { body: { ...created, link: 'http://localhost:3000/accept-invite?token=abc' } }
        }
      }),
    )
    const user = userEvent.setup()
    renderApp(<AppRoutes />, '/people')
    expect(await screen.findByText('Lena Okafor')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Email'), 'ana@x.test')
    await user.selectOptions(screen.getByLabelText('Role'), 'agent')
    await user.click(screen.getByRole('button', { name: 'Send invitation' }))
    await waitFor(() => expect(invites).toEqual([{ email: 'ana@x.test', role: 'agent' }]))
    const pending = await screen.findByRole('region', { name: 'Pending invitations' })
    expect(within(pending).getByText('ana@x.test')).toBeInTheDocument()
    await user.click(within(pending).getByRole('button', { name: 'Copy link for ana@x.test' }))
    expect(await navigator.clipboard.readText()).toBe('http://localhost:3000/accept-invite?token=abc')
    expect(stub.calls.length).toBeGreaterThan(0)
  })

  it('changes a role and explains why the last owner cannot be demoted', async () => {
    const patches: unknown[] = []
    stubFetch(
      base('owner', (url, init) => {
        if (url === '/api/members') return { body: members }
        if (url === '/api/invitations') return { body: [] }
        if (url === '/api/members/u2' && init.method === 'PATCH') {
          patches.push(JSON.parse(String(init.body)))
          return { body: { user_id: 'u2', role: 'admin', active: true } }
        }
        if (url === '/api/members/u1' && init.method === 'PATCH')
          return { status: 409, body: { detail: { code: 'last_owner', message: 'A workspace needs at least one owner.' } } }
      }),
    )
    renderApp(<AppRoutes />, '/people')
    await screen.findByText('Lena Okafor')
    await userEvent.selectOptions(screen.getByLabelText('Role for Lena Okafor'), 'admin')
    await waitFor(() => expect(patches).toEqual([{ role: 'admin' }]))
    await userEvent.selectOptions(screen.getByLabelText('Role for Priya Raman'), 'admin')
    expect(await screen.findByRole('alert')).toHaveTextContent('A workspace needs at least one owner.')
  })

  it('asks before deactivating, then does it', async () => {
    const patches: unknown[] = []
    stubFetch(
      base('owner', (url, init) => {
        if (url === '/api/members') return { body: members }
        if (url === '/api/invitations') return { body: [] }
        if (url === '/api/members/u2' && init.method === 'PATCH') {
          patches.push(JSON.parse(String(init.body)))
          return { body: { user_id: 'u2', role: 'agent', active: false } }
        }
      }),
    )
    renderApp(<AppRoutes />, '/people')
    await screen.findByText('Lena Okafor')
    await userEvent.click(screen.getByRole('button', { name: 'Deactivate Lena Okafor' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/signed out and lose access/i)
    expect(patches).toEqual([])
    await userEvent.click(within(dialog).getByRole('button', { name: 'Deactivate' }))
    await waitFor(() => expect(patches).toEqual([{ active: false }]))
    expect(screen.getByText('Tom Alvarez').closest('tr')).toHaveTextContent('Deactivated')
  })

  it('shows the team read-only to an agent', async () => {
    stubFetch(base('agent', (url) => (url === '/api/members' ? { body: members } : undefined)))
    renderApp(<AppRoutes />, '/people')
    expect(await screen.findByText('Lena Okafor')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send invitation' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Role for Lena Okafor')).not.toBeInTheDocument()
  })
})

const channels = {
  inbound_address: 'inbound-abc123@inbound.resolveflow.local',
  form_url: 'http://localhost:3000/form/brightwork',
  form_snippet: '<iframe src="http://localhost:3000/form/brightwork"></iframe>',
  simulate_enabled: true,
}

describe('channels', () => {
  it('copies the exact inbound address, form link and embed snippet', async () => {
    stubFetch(base('owner', (url) => (url === '/api/settings/channels' ? { body: channels } : undefined)))
    const user = userEvent.setup()
    renderApp(<AppRoutes />, '/channels')
    expect(await screen.findByText(channels.inbound_address)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Copy email address' }))
    expect(await navigator.clipboard.readText()).toBe(channels.inbound_address)
    await user.click(screen.getByRole('button', { name: 'Copy form link' }))
    expect(await navigator.clipboard.readText()).toBe(channels.form_url)
    await user.click(screen.getByRole('button', { name: 'Copy embed code' }))
    expect(await navigator.clipboard.readText()).toBe(channels.form_snippet)
  })

  it('simulates a customer email and links to the created ticket', async () => {
    const sent: unknown[] = []
    stubFetch(
      base('owner', (url, init) => {
        if (url === '/api/settings/channels') return { body: channels }
        if (url === '/api/dev/simulate-inbound') {
          sent.push(JSON.parse(String(init.body)))
          return { body: { status: 'created', ticket_id: 't9' } }
        }
      }),
    )
    renderApp(<AppRoutes />, '/channels')
    await screen.findByText(channels.inbound_address)
    await userEvent.type(screen.getByLabelText('From email'), 'walk@in.test')
    await userEvent.type(screen.getByLabelText('Message'), 'Is anyone there?')
    await userEvent.click(screen.getByRole('button', { name: 'Send simulated email' }))
    await waitFor(() => expect(sent).toEqual([{ from_email: 'walk@in.test', from_name: null, subject: 'Question about my order', text: 'Is anyone there?' }]))
    expect(await screen.findByRole('link', { name: 'Open the ticket' })).toHaveAttribute('href', '/inbox/t9')
  })

  it('hides the simulator when it is switched off', async () => {
    stubFetch(base('owner', (url) => (url === '/api/settings/channels' ? { body: { ...channels, simulate_enabled: false } } : undefined)))
    renderApp(<AppRoutes />, '/channels')
    await screen.findByText(channels.inbound_address)
    expect(screen.queryByRole('button', { name: 'Send simulated email' })).not.toBeInTheDocument()
  })
})

describe('audit log', () => {
  const entry = (id: string, action: string, extra = {}) => ({
    id, created_at: new Date().toISOString(), actor_type: 'user', actor_id: 'u1', actor_name: 'Priya Raman',
    action, entity_type: 'ticket', entity_id: 'abcdef12-0000', before: null, after: null, ...extra,
  })

  it('shows entries in plain language and filters through the API', async () => {
    const stub = stubFetch(
      base('owner', (url) => {
        if (url === '/api/members') return { body: members }
        if (url.startsWith('/api/audit')) return { body: { items: [entry('a1', 'ticket.updated', { before: { status: 'open' }, after: { status: 'resolved' } }), entry('a2', 'member.updated', { entity_type: 'member', before: { role: 'agent' }, after: { role: 'admin' } })], next_cursor: null } }
      }),
    )
    renderApp(<AppRoutes />, '/audit')
    expect(await screen.findByText('Status: open → resolved')).toBeInTheDocument()
    expect(screen.getByText('Role: agent → admin')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Item type'), 'ticket')
    await waitFor(() => expect(stub.calls.some((c) => c.url.includes('entity_type=ticket'))).toBe(true))
  })

  it('exports a CSV that carries the active filters', async () => {
    stubFetch(
      base('owner', (url) => {
        if (url === '/api/members') return { body: members }
        if (url.startsWith('/api/audit')) return { body: { items: [], next_cursor: null } }
      }),
    )
    renderApp(<AppRoutes />, '/audit')
    const link = await screen.findByRole('link', { name: 'Export CSV' })
    expect(link).toHaveAttribute('href', '/api/audit.csv')
    await userEvent.selectOptions(screen.getByLabelText('Item type'), 'member')
    await waitFor(() => expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute('href', '/api/audit.csv?entity_type=member'))
  })

  it('is not reachable for an agent', async () => {
    stubFetch(base('agent', (url) => (url.startsWith('/api/tickets') ? { body: { items: [], next_cursor: null } } : url === '/api/members' ? { body: [] } : undefined)))
    renderApp(<AppRoutes />, '/audit')
    expect(await screen.findByRole('heading', { name: 'Inbox' })).toBeInTheDocument()
  })
})

describe('new ticket', () => {
  const inbox = (created: unknown[]): Handler =>
    base('agent', (url, init) => {
      if (url === '/api/members') return { body: [] }
      if (url.startsWith('/api/tickets?') && (init.method ?? 'GET') === 'GET') return { body: { items: [], next_cursor: null } }
      if (url === '/api/tickets/t77/activity') return { body: [] }
      if (url === '/api/tickets' && init.method === 'POST') {
        created.push(JSON.parse(String(init.body)))
        return { body: { id: 't77', number: 77 } }
      }
      if (url === '/api/tickets/t77') return { body: { id: 't77', number: 77, subject: 'Boiler is broken', messages: [], tags: [], status: 'new', priority: 'high', channel: 'manual', requester: { id: 'c', email: 'c@x.test', name: 'C' }, assignee: null, created_at: new Date().toISOString(), last_activity_at: new Date().toISOString(), possible_duplicate_of: null, merged_into_id: null, snippet: null } }
    })

  it('opens with c, validates, creates the ticket and opens it', async () => {
    const created: unknown[] = []
    stubFetch(inbox(created))
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('No open tickets')
    await userEvent.keyboard('c')
    const dialog = await screen.findByRole('dialog', { name: /new ticket/i })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create ticket' }))
    expect(await within(dialog).findAllByText(/required/i)).not.toHaveLength(0)
    expect(created).toEqual([])
    await userEvent.type(within(dialog).getByLabelText('Customer email'), 'c@x.test')
    await userEvent.type(within(dialog).getByLabelText('Subject'), 'Boiler is broken')
    await userEvent.type(within(dialog).getByLabelText('What happened'), 'No hot water since last night.')
    await userEvent.selectOptions(within(dialog).getByLabelText('Priority'), 'high')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create ticket' }))
    await waitFor(() => expect(created).toEqual([{ subject: 'Boiler is broken', body: 'No hot water since last night.', requester_email: 'c@x.test', requester_name: null, priority: 'high' }]))
    expect(await screen.findByTestId('ticket-pane')).toHaveAttribute('data-ticket-id', 't77')
  })

  it('is not offered to a viewer', async () => {
    stubFetch(base('viewer', (url) => (url === '/api/members' ? { body: [] } : url.startsWith('/api/tickets') ? { body: { items: [], next_cursor: null } } : undefined)))
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('No open tickets')
    expect(screen.queryByRole('button', { name: 'New ticket' })).not.toBeInTheDocument()
    await userEvent.keyboard('c')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('public form', () => {
  const form = (post: Handler): Handler => (url, init) => {
    if (url === '/api/public/forms/brightwork' && (init.method ?? 'GET') === 'GET') return { body: { workspace_name: 'Brightwork Studio' } }
    return post(url, init)
  }
  const fill = async () => {
    await userEvent.type(await screen.findByLabelText('Your name'), 'Frankie')
    await userEvent.type(screen.getByLabelText('Email'), 'frankie@customer.test')
    await userEvent.type(screen.getByLabelText('Subject'), 'Quote please')
    await userEvent.type(screen.getByLabelText('Message'), 'Could someone call me?')
  }

  it('submits without signing in and shows the reference number', async () => {
    const sent: Record<string, unknown>[] = []
    stubFetch(form((url, init) => {
      if (url === '/api/public/forms/brightwork' && init.method === 'POST') {
        sent.push(JSON.parse(String(init.body)))
        return { body: { reference: '#12' } }
      }
    }))
    renderApp(<AppRoutes />, '/form/brightwork')
    expect(await screen.findByRole('heading', { name: /brightwork studio/i })).toBeInTheDocument()
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByText(/#12/)).toBeInTheDocument()
    expect(sent[0]).toMatchObject({ name: 'Frankie', email: 'frankie@customer.test', subject: 'Quote please', message: 'Could someone call me?', website: '' })
  })

  it('tells the person plainly when they are sending too much', async () => {
    stubFetch(form((url, init) => (url === '/api/public/forms/brightwork' && init.method === 'POST'
      ? { status: 429, body: { detail: { code: 'rate_limited', message: 'Too many messages from this address. Try again later.' } } } : undefined)))
    renderApp(<AppRoutes />, '/form/brightwork')
    await fill()
    await userEvent.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many messages')
  })

  it('keeps the honeypot out of the tab order and away from screen readers', async () => {
    stubFetch(form(() => undefined))
    renderApp(<AppRoutes />, '/form/brightwork')
    await screen.findByLabelText('Your name')
    const trap = document.querySelector<HTMLInputElement>('input[name="website"]')!
    expect(trap.tabIndex).toBe(-1)
    expect(trap.closest('[aria-hidden="true"]')).not.toBeNull()
    expect(trap.autocomplete).toBe('off')
  })

  it('says so when the form does not exist', async () => {
    stubFetch(() => ({ status: 404, body: { detail: { code: 'not_found', message: 'This form does not exist.' } } }))
    renderApp(<AppRoutes />, '/form/nope')
    expect(await screen.findByText(/isn.t available/i)).toBeInTheDocument()
  })
})
