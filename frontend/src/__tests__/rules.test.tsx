import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { setCsrf } from '../lib/api'
import type { RuleDetail, TestResult } from '../lib/types'
import { meFor, renderApp, stubFetch } from '../test-utils'
import type { Handler } from '../test-utils'
import type { RuleDefinition } from '../features/rules/vocab'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const DEF: RuleDefinition = {
  trigger: { event: 'ticket.created' },
  conditions: { op: 'and', items: [{ field: 'subject', operator: 'contains', value: 'refund' }] },
  actions: [{ type: 'set_priority', value: 'high' }, { type: 'add_tag', tag: 'refund' }],
}

function rule(id: string, o: Partial<RuleDetail> = {}): RuleDetail {
  return {
    id, name: `Rule ${id}`, position: 1, status: 'draft', active_version: null, current_version: 1,
    definition: DEF, tested: false, updated_at: new Date().toISOString(),
    versions: [{ version: 1, content_hash: 'h1', created_at: new Date().toISOString(), author: 'Priya Raman', tested: false, active: false }],
    tests: [], ...o,
  }
}

interface Log {
  posts: { url: string; body: any }[]
  puts: { url: string; body: any }[]
}

function server(rules: RuleDetail[], log: Log, opts: { perms?: string[]; testResult?: Partial<TestResult>; passAfterRecord?: boolean } = {}): Handler {
  const state = rules.map((r) => structuredClone(r))
  return (url, init) => {
    const u = new URL(url, 'http://x')
    const method = init.method ?? 'GET'
    const body = init.body ? JSON.parse(String(init.body)) : undefined
    if (u.pathname === '/api/auth/me') return { body: meFor('owner', opts.perms ? { permissions: opts.perms } : {}) }
    if (u.pathname === '/api/members') return { body: [{ user_id: 'u1', email: 'a@x.test', name: 'Priya Raman', role: 'owner', active: true }, { user_id: 'u2', email: 'b@x.test', name: 'Lena Okafor', role: 'agent', active: true }] }
    if (u.pathname === '/api/teams') return { body: [{ id: 't1', name: 'Support', members: [] }] }
    if (u.pathname.startsWith('/api/tickets')) return { body: { items: [], next_cursor: null } }
    if (u.pathname === '/api/rules' && method === 'GET') return { body: state }
    if (u.pathname === '/api/rules' && method === 'POST') {
      log.posts.push({ url, body })
      const created = rule('new', { name: body.name, definition: body.definition })
      state.push(created)
      return { body: created }
    }
    if (u.pathname === '/api/rules/reorder') {
      log.posts.push({ url, body })
      return { body: state }
    }
    if (u.pathname === '/api/rules/test') {
      log.posts.push({ url, body })
      return { body: { matched: true, trigger_matched: true, conditions: { kind: 'group', op: 'and', passed: true, children: [{ kind: 'condition', field: 'subject', operator: 'contains', value: 'refund', actual: 'Refund for order 1042', passed: true }] }, actions: [{ type: 'set_priority', text: 'Set priority to high', status: 'apply', reason: null }, { type: 'add_tag', text: 'Add the tag “refund”', status: 'skipped', reason: 'Tag already added by Live rule.' }], ...opts.testResult } }
    }
    const m = u.pathname.match(/^\/api\/rules\/([^/]+)(?:\/(.+))?$/)
    if (m) {
      const r = state.find((x) => x.id === m[1])
      if (!r) return undefined
      if (!m[2] && method === 'GET') return { body: r }
      if (!m[2] && method === 'PUT') {
        log.puts.push({ url, body })
        if (body.name) r.name = body.name
        if (body.definition && JSON.stringify(body.definition) !== JSON.stringify(r.definition)) {
          r.definition = body.definition
          r.current_version += 1
          r.tested = false
          r.versions.unshift({ version: r.current_version, content_hash: `h${r.current_version}`, created_at: new Date().toISOString(), author: 'Priya Raman', tested: false, active: false })
        }
        return { body: r }
      }
      if (m[2] === 'tests') {
        log.posts.push({ url, body })
        const matched = body.expectation === 'match'
        if (matched) {
          r.tested = true
          r.versions[0].tested = true
        }
        return { body: { matched: true, trigger_matched: true, conditions: null, actions: [], passed: matched, test_id: 'x', version: r.current_version } }
      }
      if (m[2] === 'activate') {
        log.posts.push({ url, body })
        r.status = 'active'
        r.active_version = body.version ?? r.current_version
        return { body: r }
      }
      if (m[2] === 'archive' || m[2] === 'restore') {
        log.posts.push({ url, body })
        r.status = m[2] === 'archive' ? 'archived' : 'draft'
        return { body: r }
      }
    }
  }
}

const newLog = (): Log => ({ posts: [], puts: [] })

describe('automations list', () => {
  it('shows each automation in plain language with its status and test state', async () => {
    stubFetch(server([
      rule('a', { name: 'Refund requests', status: 'active', active_version: 1, tested: true }),
      rule('b', { name: 'Draft idea', position: 2, current_version: 2, active_version: 1, status: 'active', tested: false }),
    ], newLog()))
    renderApp(<AppRoutes />, '/automations')
    const list = await screen.findByRole('list', { name: 'Automations' })
    expect(within(list).getByText('Refund requests')).toBeInTheDocument()
    expect(within(list).getAllByText(/When a new ticket arrives/)[0]).toHaveTextContent(/the subject contains “refund”.*set priority to high.*add the tag “refund”/)
    expect(within(list).getAllByText('Live')).toHaveLength(2)
    expect(within(list).getByText('Tested')).toBeInTheDocument()
    expect(within(list).getByText(/changes not live/i)).toBeInTheDocument()
  })

  it('reorders with the arrows and archives or restores', async () => {
    const log = newLog()
    stubFetch(server([rule('a', { name: 'First', position: 1 }), rule('b', { name: 'Second', position: 2 }), rule('c', { name: 'Third', position: 3, status: 'archived' })], log))
    renderApp(<AppRoutes />, '/automations')
    await screen.findByText('Second')
    await userEvent.click(screen.getByRole('button', { name: 'Move Second up' }))
    await waitFor(() => expect(log.posts.find((p) => p.url.endsWith('/reorder'))?.body).toEqual({ ids: ['b', 'a'] }))
    await userEvent.click(screen.getByRole('button', { name: 'Archive First' }))
    await waitFor(() => expect(log.posts.some((p) => p.url.endsWith('/rules/a/archive'))).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: 'Restore Third' }))
    await waitFor(() => expect(log.posts.some((p) => p.url.endsWith('/rules/c/restore'))).toBe(true))
  })

  it('has an empty state that points at the next step', async () => {
    stubFetch(server([], newLog()))
    renderApp(<AppRoutes />, '/automations')
    expect(await screen.findByText('No automations yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'New automation' })).toHaveAttribute('href', '/automations/new')
  })

  it('is read-only without permission to manage', async () => {
    stubFetch(server([rule('a')], newLog(), { perms: ['rule:read', 'ticket:read', 'user:read'] }))
    renderApp(<AppRoutes />, '/automations')
    await screen.findByText('Rule a')
    expect(screen.queryByRole('link', { name: 'New automation' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /archive/i })).not.toBeInTheDocument()
  })
})

describe('editor', () => {
  it('builds the exact definition, including nested groups, and saves it', async () => {
    const log = newLog()
    stubFetch(server([], log))
    renderApp(<AppRoutes />, '/automations/new')
    await userEvent.type(await screen.findByLabelText('Name'), 'Refunds')
    const root = screen.getByRole('group', { name: 'Conditions' })
    await userEvent.type(within(root).getAllByLabelText('Value')[0], 'refund')
    await userEvent.click(within(root).getByRole('button', { name: 'Add group' }))
    const nested = screen.getByRole('group', { name: 'Nested conditions 1' })
    await userEvent.selectOptions(within(nested).getByLabelText('Match'), 'or')
    await userEvent.selectOptions(within(nested).getByLabelText('Field'), 'channel')
    await userEvent.selectOptions(within(nested).getByLabelText('Operator'), 'equals')
    await userEvent.selectOptions(within(nested).getByLabelText('Value'), 'form')
    await userEvent.click(within(nested).getByRole('button', { name: 'Add condition' }))
    const second = within(nested).getByRole('group', { name: 'Condition 2' })
    await userEvent.type(within(second).getByLabelText('Value'), 'invoice')
    const actions = screen.getByRole('group', { name: 'Actions' })
    await userEvent.selectOptions(within(within(actions).getByRole('group', { name: 'Action 1' })).getByLabelText('Priority'), 'urgent')
    await userEvent.click(within(actions).getByRole('button', { name: 'Add action' }))
    const a2 = within(actions).getByRole('group', { name: 'Action 2' })
    await userEvent.selectOptions(within(a2).getByLabelText('Action type'), 'add_tag')
    await userEvent.type(within(a2).getByLabelText('Tag'), 'refund')
    await userEvent.click(screen.getByRole('button', { name: 'Save automation' }))
    await waitFor(() => expect(log.posts.find((p) => p.url === '/api/rules')).toBeTruthy())
    expect(log.posts.find((p) => p.url === '/api/rules')!.body).toEqual({
      name: 'Refunds',
      definition: {
        trigger: { event: 'ticket.created' },
        conditions: {
          op: 'and',
          items: [
            { field: 'subject', operator: 'contains', value: 'refund' },
            { op: 'or', items: [{ field: 'channel', operator: 'equals', value: 'form' }, { field: 'subject', operator: 'contains', value: 'invoice' }] },
          ],
        },
        actions: [{ type: 'set_priority', value: 'urgent' }, { type: 'add_tag', tag: 'refund' }],
      },
    })
  })

  it('offers only the operators that make sense for the chosen field', async () => {
    stubFetch(server([], newLog()))
    renderApp(<AppRoutes />, '/automations/new')
    const op = async (field: string) => {
      await userEvent.selectOptions((await screen.findAllByLabelText('Field'))[0], field)
      return within(screen.getAllByLabelText('Operator')[0]).getAllByRole('option').map((o) => o.textContent)
    }
    expect(await op('assignee')).toEqual(['is nobody', 'is somebody'])
    expect(await op('priority')).toEqual(['is', 'is not', 'is one of'])
    expect(await op('subject')).toContain('contains any of')
    expect(await op('tags')).toContain('is empty')
  })

  it('shows a level only for service level triggers', async () => {
    stubFetch(server([], newLog()))
    renderApp(<AppRoutes />, '/automations/new')
    await screen.findByLabelText('When')
    expect(screen.queryByLabelText('Level')).not.toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('When'), 'sla.threshold')
    expect(await screen.findByLabelText('Level')).toBeInTheDocument()
  })

  it('will not save without a name', async () => {
    stubFetch(server([], newLog()))
    renderApp(<AppRoutes />, '/automations/new')
    expect(await screen.findByRole('button', { name: 'Save automation' })).toBeDisabled()
  })
})

describe('testing and activation', () => {
  it('locks Make live until a passing test of the current version exists, then unlocks it', async () => {
    const log = newLog()
    stubFetch(server([rule('a', { name: 'Refunds' })], log))
    renderApp(<AppRoutes />, '/automations/a')
    const live = await screen.findByRole('button', { name: 'Make live' })
    expect(live).toBeDisabled()
    expect(screen.getByText(/record a passing test/i)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('I expect this to match'))
    await userEvent.click(screen.getByRole('button', { name: 'Record as test' }))
    expect(await screen.findByText('Test passed')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Make live' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: 'Make live' }))
    await waitFor(() => expect(log.posts.some((p) => p.url === '/api/rules/a/activate')).toBe(true))
    expect(await screen.findByText(/live \(version 1\)/i)).toBeInTheDocument()
  })

  it('says plainly when a test did not do what you expected', async () => {
    stubFetch(server([rule('a')], newLog()))
    renderApp(<AppRoutes />, '/automations/a')
    await userEvent.click(await screen.findByLabelText('I expect it not to match'))
    await userEvent.click(screen.getByRole('button', { name: 'Record as test' }))
    expect(await screen.findByText(/did not match what you expected/i)).toBeInTheDocument()
  })

  it('editing and saving creates a new version that must be tested again', async () => {
    const log = newLog()
    stubFetch(server([rule('a', { name: 'Refunds', status: 'active', active_version: 1, tested: true })], log))
    renderApp(<AppRoutes />, '/automations/a')
    await screen.findByDisplayValue('Refunds')
    expect(screen.getByText(/version 1 is live/i)).toBeInTheDocument()
    const root = screen.getByRole('group', { name: 'Conditions' })
    await userEvent.type(within(root).getAllByLabelText('Value')[0], 's')
    expect(screen.getByRole('button', { name: 'Make live' })).toBeDisabled() // unsaved edits: nothing to activate yet
    await userEvent.click(screen.getByRole('button', { name: 'Save automation' }))
    await waitFor(() => expect(log.puts).toHaveLength(1))
    expect(log.puts[0].body.definition.conditions.items[0].value).toBe('refunds')
    expect(await screen.findByText(/version 2 is not live/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Make live' })).toBeDisabled()
    expect(screen.getByText(/record a passing test/i)).toBeInTheDocument()
  })

  it('runs a dry run and shows each condition and action, including overridden ones', async () => {
    const log = newLog()
    stubFetch(server([rule('a')], log))
    renderApp(<AppRoutes />, '/automations/a')
    await userEvent.clear(await screen.findByLabelText('Subject (test ticket)'))
    await userEvent.type(screen.getByLabelText('Subject (test ticket)'), 'Refund for order 1042')
    await userEvent.click(screen.getByLabelText('Include my other live automations'))
    await userEvent.click(screen.getByRole('button', { name: 'Run test' }))
    const result = await screen.findByRole('region', { name: 'Test result' })
    expect(within(result).getByText(/this automation would run/i)).toBeInTheDocument()
    expect(within(result).getByText(/Refund for order 1042/)).toBeInTheDocument()
    expect(within(result).getAllByText('Passed').length).toBeGreaterThan(0)
    expect(within(result).getByText('Set priority to high')).toBeInTheDocument()
    expect(within(result).getByText(/Tag already added by Live rule/)).toBeInTheDocument()
    const sent = log.posts.find((p) => p.url === '/api/rules/test')!.body
    expect(sent.include_active_rules).toBe(true)
    expect(sent.facts.subject).toBe('Refund for order 1042')
    expect(sent.definition.actions).toHaveLength(2)
  })

  it('rolls back to an older tested version from the versions list', async () => {
    const log = newLog()
    const r = rule('a', {
      name: 'Refunds', status: 'active', active_version: 2, current_version: 2, tested: true,
      versions: [
        { version: 2, content_hash: 'h2', created_at: new Date().toISOString(), author: 'Priya Raman', tested: true, active: true },
        { version: 1, content_hash: 'h1', created_at: new Date().toISOString(), author: 'Priya Raman', tested: true, active: false },
      ],
    })
    stubFetch(server([r], log))
    renderApp(<AppRoutes />, '/automations/a')
    const versions = await screen.findByRole('region', { name: 'Versions' })
    expect(within(versions).queryByRole('button', { name: 'Roll back to version 2' })).not.toBeInTheDocument()
    await userEvent.click(within(versions).getByRole('button', { name: 'Roll back to version 1' }))
    await waitFor(() => expect(log.posts.find((p) => p.url === '/api/rules/a/activate')?.body).toEqual({ version: 1 }))
  })

  it('shows the editor read-only when the person cannot manage automations', async () => {
    stubFetch(server([rule('a')], newLog(), { perms: ['rule:read', 'ticket:read', 'user:read'] }))
    renderApp(<AppRoutes />, '/automations/a')
    expect(await screen.findByText(/only an owner or admin can change automations/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save automation' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run test' })).not.toBeInTheDocument()
  })
})
