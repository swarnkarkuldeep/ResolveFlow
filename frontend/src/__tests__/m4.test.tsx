import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import type { Analytics, AppNotification, Delivery } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const now = new Date().toISOString()
const item = (id: string, subject: string) => ({
  id, number: 7, subject, status: 'open', priority: 'normal', channel: 'email',
  requester: { id: 'c1', email: 'c@x.test', name: 'Cora' }, assignee: null, tags: [], snippet: 'x',
  last_activity_at: now, created_at: now, possible_duplicate_of: null, merged_into_id: null,
})

describe('search', () => {
  it('shows highlighted matches, escapes markup, and explains an empty result', async () => {
    const seen: string[] = []
    stubFetch((url) => {
      const u = new URL(url, 'http://x')
      if (u.pathname === '/api/auth/me') return { body: meFor('agent') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: 0 } }
      if (u.pathname === '/api/search') {
        const q = u.searchParams.get('q') ?? ''
        seen.push(q)
        if (q === 'nothing') return { body: { items: [] } }
        return {
          body: {
            items: [{ ...item('t1', 'Boiler broken'), match: 'message', rank: 0.4, snippet_html: 'The <mark>boiler</mark> &amp; &lt;b&gt;pipes&lt;/b&gt; are cold' }],
          },
        }
      }
    })
    renderApp(<AppRoutes />, '/search')
    await userEvent.type(await screen.findByLabelText('Search tickets'), 'boiler')
    const list = await screen.findByRole('list', { name: 'Search results' })
    expect(within(list).getByText('boiler').tagName).toBe('MARK')
    expect(within(list).getByText(/& <b>pipes<\/b> are cold/)).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: /Boiler broken/ })).toHaveAttribute('href', '/inbox/t1')
    await userEvent.clear(screen.getByLabelText('Search tickets'))
    await userEvent.type(screen.getByLabelText('Search tickets'), 'nothing')
    expect(await screen.findByText(/No tickets match “nothing”/)).toBeInTheDocument()
    expect(seen.length).toBeGreaterThan(1)
  })
})

const notification = (id: string, read: boolean): AppNotification => ({
  id, kind: 'assigned', title: `Assigned to you: ticket #${id}`, body: 'Leaking tap', read, created_at: now,
  ticket: { id: `t-${id}`, number: 1 },
})

describe('notifications', () => {
  it('shows the unread count on the bell and marks a notification read when it is opened', async () => {
    const calls: string[] = []
    let unread = [{ ...notification('1', false), ticket: null }, notification('2', false), notification('3', true)]
    stubFetch((url, init) => {
      const u = new URL(url, 'http://x')
      const method = init.method ?? 'GET'
      if (u.pathname === '/api/auth/me') return { body: meFor('agent') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: unread.filter((n) => !n.read).length } }
      if (u.pathname === '/api/notifications' && method === 'GET') return { body: { items: unread } }
      if (u.pathname === '/api/notification-prefs') return { body: [] }
      if (u.pathname === '/api/notifications/read-all') {
        calls.push('read-all')
        unread = unread.map((n) => ({ ...n, read: true }))
        return { body: { ok: true } }
      }
      if (u.pathname.endsWith('/read')) {
        calls.push(u.pathname)
        unread = unread.map((n) => (u.pathname.includes(`/${n.id}/`) ? { ...n, read: true } : n))
        return { body: { ok: true } }
      }
      if (u.pathname === '/api/tickets/t-1') return { body: { ...item('t-1', 'Leaking tap'), messages: [] } }
      if (u.pathname.endsWith('/activity') || u.pathname.endsWith('/rules')) return { body: [] }
      if (u.pathname.startsWith('/api/tickets')) return { body: { items: [], next_cursor: null } }
      if (u.pathname === '/api/members') return { body: [] }
    })
    renderApp(<AppRoutes />, '/notifications')
    expect(await screen.findByRole('link', { name: 'Notifications, 2 unread' })).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: /Assigned to you: ticket #1/ }))
    expect(calls).toContain('/api/notifications/1/read')
    await waitFor(() => expect(screen.getByRole('link', { name: 'Notifications, 1 unread' })).toBeInTheDocument())
  })

  it('saves a preference change and shows failed emails to admins with a working retry', async () => {
    const calls: { path: string; body: unknown }[] = []
    const dead: Delivery[] = [
      { id: 'd1', title: 'Ticket #4 missed its first response deadline', kind: 'sla', recipient: 'lena@x.test', attempts: 5, error: 'provider is down', status: 'dead', created_at: now },
    ]
    stubFetch((url, init) => {
      const u = new URL(url, 'http://x')
      const method = init.method ?? 'GET'
      if (u.pathname === '/api/auth/me') return { body: meFor('owner') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: 0 } }
      if (u.pathname === '/api/notifications') return { body: { items: [] } }
      if (u.pathname === '/api/notification-prefs' && method === 'GET') {
        return { body: [{ kind: 'assigned', in_app: true, email: false }, { kind: 'sla', in_app: true, email: true }] }
      }
      if (u.pathname === '/api/notification-prefs' && method === 'PUT') {
        calls.push({ path: u.pathname, body: JSON.parse(String(init.body)) })
        return { body: [{ kind: 'assigned', in_app: true, email: true }, { kind: 'sla', in_app: true, email: true }] }
      }
      if (u.pathname === '/api/notification-deliveries') return { body: { items: dead } }
      if (u.pathname === '/api/notification-deliveries/d1/retry') {
        calls.push({ path: u.pathname, body: null })
        return { body: { ok: true } }
      }
    })
    renderApp(<AppRoutes />, '/notifications')
    await userEvent.click(await screen.findByRole('checkbox', { name: 'A ticket is assigned to me: by email' }))
    await waitFor(() => expect(calls[0]?.body).toEqual([{ kind: 'assigned', in_app: true, email: true }]))
    expect(await screen.findByText('provider is down')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Send again/ }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/retry'))).toBe(true))
  })

  it('does not show failed emails to an agent', async () => {
    stubFetch((url) => {
      const u = new URL(url, 'http://x')
      if (u.pathname === '/api/auth/me') return { body: meFor('agent') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: 0 } }
      if (u.pathname === '/api/notifications') return { body: { items: [] } }
      if (u.pathname === '/api/notification-prefs') return { body: [] }
    })
    renderApp(<AppRoutes />, '/notifications')
    expect(await screen.findByText('Nothing yet')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Emails that could not be sent' })).toBeNull()
  })
})

const analytics = (over: Partial<Analytics> = {}): Analytics => ({
  range: { days: 30, since: '2026-10-01', timezone: 'UTC' },
  totals: { created: 12, resolved: 8, open_now: 4 },
  sla: { first_response: { measured: 10, met: 9, compliance_pct: 90 }, resolution: { measured: 0, met: 0, compliance_pct: null }, breached: 2 },
  averages: { first_response_minutes: 75, resolution_minutes: null },
  by_day: [{ date: '2026-10-01', created: 3, resolved: 1 }],
  by_priority: [{ priority: 'high', count: 5 }],
  by_channel: [{ channel: 'email', count: 12 }],
  by_agent: [{ id: 'u1', agent: 'Lena Okafor', assigned: 6, resolved: 4 }],
  ...over,
})

describe('analytics', () => {
  it('shows the figures, refetches for another range, and is hidden from agents', async () => {
    const ranges: string[] = []
    stubFetch((url) => {
      const u = new URL(url, 'http://x')
      if (u.pathname === '/api/auth/me') return { body: meFor('owner') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: 0 } }
      if (u.pathname === '/api/analytics') {
        ranges.push(u.searchParams.get('days') ?? '')
        return { body: analytics() }
      }
    })
    renderApp(<AppRoutes />, '/analytics')
    const summary = await screen.findByRole('region', { name: 'Service levels' })
    expect(within(summary).getByText('90%')).toBeInTheDocument()
    expect(within(summary).getByText('9 of 10 tickets')).toBeInTheDocument()
    expect(within(summary).getByText('1 h 15 min')).toBeInTheDocument()
    expect(within(summary).getAllByText('No data yet').length).toBe(2)
    expect(screen.getByRole('list', { name: 'Tickets by priority' })).toHaveTextContent('High')
    expect(screen.getByRole('cell', { name: 'Lena Okafor' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Last 7 days' }))
    await waitFor(() => expect(ranges).toContain('7'))
  })

  it('sends an agent who opens the page back to the inbox', async () => {
    stubFetch((url) => {
      const u = new URL(url, 'http://x')
      if (u.pathname === '/api/auth/me') return { body: meFor('agent') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: 0 } }
      if (u.pathname.startsWith('/api/tickets')) return { body: { items: [], next_cursor: null } }
      if (u.pathname === '/api/members') return { body: [] }
    })
    renderApp(<AppRoutes />, '/analytics')
    expect(await screen.findByRole('heading', { name: 'Inbox', level: 1 })).toBeInTheDocument()
  })
})

describe('customer history', () => {
  it('lists the customer tickets and links to each', async () => {
    stubFetch((url) => {
      const u = new URL(url, 'http://x')
      if (u.pathname === '/api/auth/me') return { body: meFor('agent') }
      if (u.pathname === '/api/notifications/unread-count') return { body: { count: 0 } }
      if (u.pathname === '/api/customers/c1') {
        return {
          body: {
            customer: { id: 'c1', email: 'c@x.test', name: 'Cora', since: now },
            tickets: [item('t2', 'Second problem'), item('t1', 'First problem')],
            stats: { total: 2, open: 2 },
          },
        }
      }
    })
    renderApp(<AppRoutes />, '/customers/c1')
    expect(await screen.findByRole('heading', { name: 'Cora', level: 1 })).toBeInTheDocument()
    expect(screen.getByText(/2 tickets, 2 open/)).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Ticket history' })
    expect(within(list).getByRole('link', { name: /Second problem/ })).toHaveAttribute('href', '/inbox/t2')
  })
})
