import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import { meFor, renderApp, stubFetch } from '../test-utils'
import type { Handler } from '../test-utils'
import type { Role } from '../lib/types'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

function settings() {
  return {
    enabled: true,
    business_hours_only: true,
    targets: {
      urgent: { first_response_minutes: 60, resolution_minutes: 240 },
      high: { first_response_minutes: 240, resolution_minutes: 480 },
      normal: { first_response_minutes: 480, resolution_minutes: 1440 },
      low: { first_response_minutes: 1440, resolution_minutes: 4320 },
    },
    timezone: 'UTC',
    schedule: Object.fromEntries(DAYS.map((d) => [d, d === 'sat' || d === 'sun' ? [] : [{ start: '09:00', end: '17:00' }]])),
    holidays: [] as string[],
    version: 3,
  }
}

function server(role: Role, put?: (body: unknown) => { status?: number; body?: unknown }, permissions?: string[]): Handler {
  const state = settings()
  return (url, init) => {
    const u = new URL(url, 'http://x')
    if (u.pathname === '/api/auth/me') return { body: meFor(role, permissions ? { permissions } : {}) }
    if (u.pathname === '/api/settings/sla' && (init.method ?? 'GET') === 'GET') return { body: state }
    if (u.pathname === '/api/settings/sla' && init.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      const res = put?.(body)
      if (res) return res
      Object.assign(state, body, { version: state.version + 1 })
      return { body: state }
    }
    if (u.pathname.startsWith('/api/tickets')) return { body: { items: [], next_cursor: null } }
    if (u.pathname === '/api/members') return { body: [] }
  }
}

describe('service levels page', () => {
  it('shows the current policy, calendar and targets', async () => {
    stubFetch(server('owner'))
    renderApp(<AppRoutes />, '/service-levels')
    expect(await screen.findByRole('heading', { name: 'Service levels' })).toBeInTheDocument()
    expect(await screen.findByLabelText('Track service levels')).toBeChecked()
    expect(screen.getByLabelText('Count business hours only')).toBeChecked()
    expect(screen.getByLabelText('Normal: first response (minutes)')).toHaveValue(480)
    expect(screen.getByLabelText('Urgent: resolution (minutes)')).toHaveValue(240)
    expect(screen.getByLabelText('Time zone')).toHaveValue('UTC')
    expect(screen.getByLabelText('Monday opens')).toHaveValue('09:00')
    expect(screen.getByLabelText('Saturday open')).not.toBeChecked()
    expect(screen.getAllByText('8 h').length).toBeGreaterThan(0)
  })

  it('saves exactly what was edited and confirms it', async () => {
    const puts: unknown[] = []
    stubFetch(server('owner', (b) => (puts.push(b), undefined)))
    renderApp(<AppRoutes />, '/service-levels')
    const field = await screen.findByLabelText('Normal: first response (minutes)')
    const save = screen.getByRole('button', { name: 'Save changes' })
    expect(save).toBeDisabled()
    await userEvent.clear(field)
    await userEvent.type(field, '120')
    await userEvent.selectOptions(screen.getByLabelText('Time zone'), 'Europe/London')
    await userEvent.click(screen.getByLabelText('Count business hours only'))
    expect(save).toBeEnabled()
    await userEvent.click(save)
    await waitFor(() => expect(puts).toHaveLength(1))
    const body = puts[0] as ReturnType<typeof settings>
    expect(body.targets.normal).toEqual({ first_response_minutes: 120, resolution_minutes: 1440 })
    expect(body.timezone).toBe('Europe/London')
    expect(body.business_hours_only).toBe(false)
    expect('version' in body).toBe(false)
    expect(await screen.findByText('Service levels saved')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled())
  })

  it('keeps the form and shows the reason when the server rejects a change', async () => {
    stubFetch(server('owner', () => ({
      status: 422,
      body: { detail: [{ loc: ['body', 'schedule'], msg: 'Value error, mon: each range must start before it ends.', type: 'value_error' }] },
    })))
    renderApp(<AppRoutes />, '/service-levels')
    const start = await screen.findByLabelText('Monday opens')
    await userEvent.clear(start)
    await userEvent.type(start, '18:00')
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('mon: each range must start before it ends.')
    expect(screen.getByLabelText('Monday opens')).toHaveValue('18:00')
  })

  it('opens a weekend day with sensible hours and closes a weekday', async () => {
    const puts: unknown[] = []
    stubFetch(server('owner', (b) => (puts.push(b), undefined)))
    renderApp(<AppRoutes />, '/service-levels')
    await userEvent.click(await screen.findByLabelText('Saturday open'))
    expect(screen.getByLabelText('Saturday opens')).toHaveValue('09:00')
    await userEvent.click(screen.getByLabelText('Friday open'))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect(puts).toHaveLength(1))
    const body = puts[0] as ReturnType<typeof settings>
    expect(body.schedule.sat).toEqual([{ start: '09:00', end: '17:00' }])
    expect(body.schedule.fri).toEqual([])
  })

  it('adds and removes closed dates', async () => {
    const puts: unknown[] = []
    stubFetch(server('owner', (b) => (puts.push(b), undefined)))
    renderApp(<AppRoutes />, '/service-levels')
    await userEvent.type(await screen.findByLabelText('Closed date'), '2026-12-25')
    await userEvent.click(screen.getByRole('button', { name: 'Add closed date' }))
    await userEvent.type(screen.getByLabelText('Closed date'), '2026-12-26')
    await userEvent.click(screen.getByRole('button', { name: 'Add closed date' }))
    expect(screen.getByText('2026-12-25')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove 2026-12-25' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() => expect((puts[0] as ReturnType<typeof settings>).holidays).toEqual(['2026-12-26']))
  })

  it('is in the navigation for owners and admins only', async () => {
    stubFetch(server('owner'))
    const { unmount } = renderApp(<AppRoutes />, '/inbox')
    const nav = await screen.findByRole('navigation', { name: /main/i })
    expect(within(nav).getByRole('link', { name: 'Service levels' })).toBeInTheDocument()
    unmount()
    vi.unstubAllGlobals()
    stubFetch(server('agent'))
    renderApp(<AppRoutes />, '/inbox')
    const nav2 = await screen.findByRole('navigation', { name: /main/i })
    expect(within(nav2).queryByRole('link', { name: 'Service levels' })).toBeNull()
  })

  it('is read-only, with an explanation, when the person cannot change settings', async () => {
    stubFetch(server('admin', undefined, ['settings:read', 'ticket:read', 'user:read']))
    renderApp(<AppRoutes />, '/service-levels')
    expect(await screen.findByText(/only an owner or admin can change/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Normal: first response (minutes)')).toBeDisabled()
  })
})
