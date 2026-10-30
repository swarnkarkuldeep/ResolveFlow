import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import type { RuleExecution } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const ticket = {
  id: 't1', number: 5, subject: 'Refund please', status: 'open', priority: 'high', channel: 'email',
  requester: { id: 'c1', email: 'c@x.test', name: 'Cora' }, assignee: null, tags: ['refund'], snippet: 'x',
  last_activity_at: new Date().toISOString(), created_at: new Date().toISOString(), possible_duplicate_of: null,
  merged_into_id: null, messages: [],
}

function open(executions: RuleExecution[]) {
  stubFetch((url, init) => {
    const u = new URL(url, 'http://x')
    if (u.pathname === '/api/auth/me') return { body: meFor('agent') }
    if (u.pathname === '/api/members') return { body: [] }
    if (u.pathname === '/api/tickets' && (init.method ?? 'GET') === 'GET') return { body: { items: [ticket], next_cursor: null } }
    if (u.pathname === '/api/tickets/t1') return { body: ticket }
    if (u.pathname === '/api/tickets/t1/activity') return { body: [] }
    if (u.pathname === '/api/tickets/t1/rules') return { body: executions }
  })
  renderApp(<AppRoutes />, '/inbox/t1')
}

const ex = (name: string, actions: RuleExecution['actions']): RuleExecution => ({
  at: new Date().toISOString(), event: 'ticket.created', rule: { id: name, name, version: 2 }, matched: true, depth: 1, actions,
})

describe('automations on a ticket', () => {
  it('explains which rules ran and what each action did, including skips and failures', async () => {
    open([
      ex('Refund handler', [
        { type: 'set_priority', text: 'Set priority to high', status: 'applied', reason: null },
        { type: 'assign', text: 'Assign to Lena Okafor', status: 'failed', reason: 'That person is no longer an active teammate.' },
      ]),
      ex('Second rule', [{ type: 'set_priority', text: 'Set priority to low', status: 'skipped', reason: 'Overridden by Refund handler, which runs first.' }]),
    ])
    await userEvent.click(await screen.findByText(/Automations that ran/))
    const panel = screen.getByRole('region', { name: 'Automations on this ticket' })
    expect(within(panel).getByText('Refund handler')).toBeInTheDocument()
    expect(within(panel).getAllByText(/version 2/i).length).toBe(2)
    expect(within(panel).getByText('Set priority to high')).toBeInTheDocument()
    expect(within(panel).getByText(/Applied/)).toBeInTheDocument()
    expect(within(panel).getByText(/no longer an active teammate/)).toBeInTheDocument()
    expect(within(panel).getByText(/Overridden by Refund handler/)).toBeInTheDocument()
    expect(within(panel).getAllByText(/When a new ticket arrives/).length).toBeGreaterThan(0)
  })

  it('stays out of the way when nothing ran', async () => {
    open([])
    await screen.findByRole('heading', { name: 'Refund please' })
    expect(screen.queryByText(/Automations that ran/)).not.toBeInTheDocument()
  })
})
