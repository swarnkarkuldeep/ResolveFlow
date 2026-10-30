import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { describeSla } from '../features/sla/describe'
import { formatMinutes, formatRemaining } from '../lib/format'
import { setCsrf } from '../lib/api'
import type { SlaSummary, TicketDetail, TicketItem } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'
import type { Handler } from '../test-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const NOW = Date.now()
const iso = (offsetMs: number) => new Date(NOW + offsetMs).toISOString()
const H = 3600_000

function sla(overrides: Partial<SlaSummary> & Pick<SlaSummary, 'state'>, fr?: Partial<SlaSummary['first_response']>, res?: Partial<SlaSummary['resolution']>): SlaSummary {
  return {
    next_due_at: null,
    first_response: { due_at: null, met_at: null, state: 'none', ...fr },
    resolution: { due_at: null, met_at: null, state: 'none', ...res },
    ...overrides,
  }
}

describe('formatting', () => {
  it('formats remaining time and minutes compactly', () => {
    expect(formatRemaining(2 * H + 10 * 60_000)).toBe('2h 10m')
    expect(formatRemaining(2 * H)).toBe('2h')
    expect(formatRemaining(40 * 60_000)).toBe('40m')
    expect(formatRemaining(20_000)).toBe('<1m')
    expect(formatMinutes(480)).toBe('8 h')
    expect(formatMinutes(90)).toBe('1 h 30 min')
    expect(formatMinutes(45)).toBe('45 min')
  })
})

describe('describeSla', () => {
  const cases: [string, SlaSummary, string | null][] = [
    ['running soon', sla({ state: 'running' }, { due_at: iso(2 * H + 10 * 60_000), state: 'running' }), 'Due in 2h 10m'],
    ['at risk', sla({ state: 'at_risk' }, { due_at: iso(40 * 60_000), state: 'at_risk' }), 'At risk · 40m left'],
    ['breached', sla({ state: 'breached' }, { due_at: iso(-3 * H), state: 'breached' }), 'Breached 3h ago'],
    ['paused', sla({ state: 'paused' }, { state: 'paused' }), 'Paused'],
    ['met', sla({ state: 'met' }, { state: 'met', met_at: iso(-H) }, { state: 'met' }), null],
    ['no policy', sla({ state: 'none' }), null],
    ['the worst metric wins', sla({ state: 'breached' }, { due_at: iso(-H), state: 'breached' }, { due_at: iso(5 * H), state: 'running' }), 'Breached 1h ago'],
  ]
  it.each(cases)('%s', (_name, summary, expected) => {
    expect(describeSla(summary, NOW)?.text ?? null).toBe(expected)
  })

  it('shows a weekday and time when the deadline is more than a day away', () => {
    const d = describeSla(sla({ state: 'running' }, { due_at: iso(30 * H), state: 'running' }), NOW)
    expect(d?.text).toMatch(/^Due \w{3} \d{2}:\d{2}$/)
  })
})

function ticket(n: number, slaValue: SlaSummary, extra: Partial<TicketItem> = {}): TicketItem {
  return {
    id: `t${n}`, number: n, subject: `Subject ${n}`, status: 'open', priority: 'normal', channel: 'email',
    requester: { id: `c${n}`, email: `c${n}@x.test`, name: `Customer ${n}` }, assignee: null, tags: [],
    snippet: `Snippet ${n}`, last_activity_at: iso(-n * H), created_at: iso(-n * H), possible_duplicate_of: null,
    merged_into_id: null, sla: slaValue, ...extra,
  }
}

function inboxServer(items: TicketItem[], onList?: (url: string) => void): Handler {
  return (url, init) => {
    const u = new URL(url, 'http://x')
    if (u.pathname === '/api/auth/me') return { body: meFor('owner') }
    if (u.pathname === '/api/members') return { body: [] }
    if (u.pathname === '/api/tickets' && (init.method ?? 'GET') === 'GET') {
      onList?.(url)
      return { body: { items: u.searchParams.get('sla') ? [] : items, next_cursor: null } }
    }
  }
}

describe('queue', () => {
  it('shows the deadline badge for open tickets and nothing for met ones', async () => {
    stubFetch(inboxServer([
      ticket(1, sla({ state: 'running' }, { due_at: iso(2 * H + 30_000), state: 'running' })),
      ticket(2, sla({ state: 'met' }, { state: 'met' }, { state: 'met' })),
      ticket(3, sla({ state: 'breached' }, { due_at: iso(-3 * H), state: 'breached' })),
    ]))
    renderApp(<AppRoutes />, '/inbox')
    expect(await screen.findByText('Due in 2h')).toBeInTheDocument()
    expect(screen.getByText('Breached 3h ago')).toBeInTheDocument()
    const rows = screen.getAllByRole('listitem')
    expect(within(rows[1]).queryByText(/due|breached|risk|paused/i)).toBeNull()
  })

  it('has At risk and Breached views that ask the API and explain when empty', async () => {
    const urls: string[] = []
    stubFetch(inboxServer([], (u) => urls.push(u)))
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByText('No open tickets')
    await userEvent.click(screen.getByRole('tab', { name: 'At risk' }))
    expect(await screen.findByText('Nothing at risk')).toBeInTheDocument()
    expect(urls.some((u) => u.includes('sla=at_risk'))).toBe(true)
    await userEvent.click(screen.getByRole('tab', { name: 'Breached' }))
    expect(await screen.findByText('No breaches')).toBeInTheDocument()
    expect(urls.some((u) => u.includes('sla=breached'))).toBe(true)
  })
})

function explainer(overrides: Record<string, unknown> = {}) {
  return {
    policy: { enabled: true, business_hours_only: true, priority: 'normal', targets: { first_response_minutes: 480, resolution_minutes: 1440 } },
    calendar: { timezone: 'UTC', schedule_text: 'Mon–Fri 09:00–17:00', holidays: 0 },
    state: 'running',
    metrics: [
      { key: 'first_response', name: 'First response', target_minutes: 480, due_at: iso(2 * H + 30_000), met_at: null, state: 'running', elapsed_minutes: 360, paused_minutes: 180 },
      { key: 'resolution', name: 'Resolution', target_minutes: 1440, due_at: iso(30 * H), met_at: null, state: 'running', elapsed_minutes: 360, paused_minutes: 180 },
    ],
    events: [
      { at: iso(-8 * H), kind: 'started', text: 'Clock started' },
      { at: iso(-6 * H), kind: 'paused', text: 'Paused: waiting on the customer' },
      { at: iso(-3 * H), kind: 'resumed', text: 'Resumed' },
    ],
    ...overrides,
  }
}

function paneServer(summary: SlaSummary, explain: unknown): Handler {
  const detail: TicketDetail = { ...ticket(1, summary), messages: [] }
  return (url, init) => {
    const u = new URL(url, 'http://x')
    if (u.pathname === '/api/auth/me') return { body: meFor('owner') }
    if (u.pathname === '/api/members') return { body: [] }
    if (u.pathname === '/api/tickets' && (init.method ?? 'GET') === 'GET') return { body: { items: [detail], next_cursor: null } }
    if (u.pathname === '/api/tickets/t1') return { body: detail }
    if (u.pathname === '/api/tickets/t1/activity') return { body: [] }
    if (u.pathname === '/api/tickets/t1/sla') return { body: explain }
  }
}

describe('ticket panel', () => {
  it('shows each deadline and expands into the plain-language explanation', async () => {
    stubFetch(paneServer(sla({ state: 'running' }, { due_at: iso(2 * H + 30_000), state: 'running' }, { due_at: iso(30 * H), state: 'running' }), explainer()))
    renderApp(<AppRoutes />, '/inbox/t1')
    const panel = await screen.findByRole('region', { name: 'Service levels' })
    expect(within(panel).getAllByText(/First response/).length).toBeGreaterThan(0)
    expect(within(panel).getByText(/2h left/)).toBeInTheDocument()
    await userEvent.click(within(panel).getByText('How is this calculated?'))
    expect(await within(panel).findByText(/Business hours only/)).toBeInTheDocument()
    expect(within(panel).getByText(/Mon–Fri 09:00–17:00/)).toBeInTheDocument()
    expect(within(panel).getAllByText(/Used 6 h of 8 h/).length).toBeGreaterThan(0)
    expect(within(panel).getAllByText(/Paused for 3 h/).length).toBeGreaterThan(0)
    expect(within(panel).getByText('Paused: waiting on the customer')).toBeInTheDocument()
  })

  it('says plainly when the clock is paused waiting on the customer', async () => {
    const paused = sla({ state: 'paused' }, { state: 'paused' }, { state: 'paused' })
    stubFetch(paneServer(paused, explainer({ state: 'paused', metrics: [
      { key: 'first_response', name: 'First response', target_minutes: 480, due_at: null, met_at: null, state: 'paused', elapsed_minutes: 120, paused_minutes: 60 },
      { key: 'resolution', name: 'Resolution', target_minutes: 1440, due_at: null, met_at: null, state: 'paused', elapsed_minutes: 120, paused_minutes: 60 },
    ] })))
    renderApp(<AppRoutes />, '/inbox/t1')
    const panel = await screen.findByRole('region', { name: 'Service levels' })
    expect(within(panel).getAllByText(/paused, waiting on the customer/i).length).toBe(2)
  })

  it('reports a breach and a met metric clearly', async () => {
    const mixed = sla({ state: 'breached' }, { due_at: iso(-3 * H), state: 'breached' }, { state: 'met', met_at: iso(-H) })
    stubFetch(paneServer(mixed, explainer({ state: 'breached', metrics: [
      { key: 'first_response', name: 'First response', target_minutes: 480, due_at: iso(-3 * H), met_at: null, state: 'breached', elapsed_minutes: 660, paused_minutes: 0 },
      { key: 'resolution', name: 'Resolution', target_minutes: 1440, due_at: iso(-2 * H), met_at: iso(-H), state: 'met', elapsed_minutes: 600, paused_minutes: 0 },
    ] })))
    renderApp(<AppRoutes />, '/inbox/t1')
    const panel = await screen.findByRole('region', { name: 'Service levels' })
    expect(within(panel).getByText(/breached 3h ago/i)).toBeInTheDocument()
    expect(within(panel).getByText(/Resolution: met/i)).toBeInTheDocument()
  })

  it('stays out of the way when service levels are switched off', async () => {
    stubFetch(paneServer(sla({ state: 'none' }), explainer({ state: 'none', policy: { enabled: false, business_hours_only: true, priority: 'normal', targets: null } })))
    renderApp(<AppRoutes />, '/inbox/t1')
    await screen.findByRole('heading', { name: 'Subject 1' })
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Service levels' })).not.toBeInTheDocument())
  })
})
