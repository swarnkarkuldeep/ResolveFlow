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
  { user_id: 'u1', email: 'owner@x.test', name: 'Priya Raman', role: 'owner', active: true },
  { user_id: 'u2', email: 'agent@x.test', name: 'Lena Okafor', role: 'agent', active: true },
  { user_id: 'u3', email: 'agent2@x.test', name: 'Jonas Weber', role: 'admin', active: true },
  { user_id: 'u4', email: 'viewer@x.test', name: 'Tom Alvarez', role: 'viewer', active: true },
  { user_id: 'u5', email: 'gone@x.test', name: 'Gina Gone', role: 'agent', active: false },
]

interface Team {
  id: string
  name: string
  members: { user_id: string; name: string; role: Role; active: boolean }[]
}

function server(role: Role, teams: Team[], hooks: { onPost?: (b: unknown) => { status?: number; body?: unknown } | undefined; onPut?: (b: unknown) => void; onDelete?: () => { status?: number; body?: unknown } | undefined } = {}): Handler {
  return (url, init) => {
    const method = init.method ?? 'GET'
    if (url === '/api/auth/me') return { body: meFor(role) }
    if (url === '/api/members') return { body: members }
    if (url === '/api/invitations') return { body: [] }
    if (url === '/api/teams' && method === 'GET') return { body: teams }
    if (url === '/api/teams' && method === 'POST') {
      const body = JSON.parse(String(init.body))
      return hooks.onPost?.(body) ?? { body: { id: 't-new', name: body.name, members: [] } }
    }
    if (url === '/api/teams/t1/members' && method === 'PUT') {
      const body = JSON.parse(String(init.body))
      hooks.onPut?.(body)
      return { body: { ...teams[0], members: [] } }
    }
    if (url === '/api/teams/t1' && method === 'DELETE') return hooks.onDelete?.() ?? { body: { status: 'ok' } }
  }
}

const support: Team = { id: 't1', name: 'Support', members: [{ user_id: 'u2', name: 'Lena Okafor', role: 'agent', active: true }] }

describe('teams', () => {
  it('lists teams and members, read-only for people who cannot manage them', async () => {
    stubFetch(server('agent', [support]))
    renderApp(<AppRoutes />, '/people')
    const section = await screen.findByRole('region', { name: 'Teams' })
    expect(await within(section).findByText('Support')).toBeInTheDocument()
    expect(within(section).getByText(/Lena Okafor/)).toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: /create team/i })).not.toBeInTheDocument()
    expect(within(section).queryByRole('button', { name: /delete team/i })).not.toBeInTheDocument()
  })

  it('creates a team', async () => {
    const posts: unknown[] = []
    stubFetch(server('owner', [], { onPost: (b) => (posts.push(b), undefined) }))
    renderApp(<AppRoutes />, '/people')
    const section = await screen.findByRole('region', { name: 'Teams' })
    await userEvent.type(within(section).getByLabelText('Team name'), 'Billing')
    await userEvent.click(within(section).getByRole('button', { name: 'Create team' }))
    await waitFor(() => expect(posts).toEqual([{ name: 'Billing' }]))
  })

  it('explains a duplicate name in plain language', async () => {
    stubFetch(server('owner', [support], { onPost: () => ({ status: 409, body: { detail: { code: 'team_exists', message: 'A team with that name already exists.' } } }) }))
    renderApp(<AppRoutes />, '/people')
    const section = await screen.findByRole('region', { name: 'Teams' })
    await userEvent.type(within(section).getByLabelText('Team name'), 'support')
    await userEvent.click(within(section).getByRole('button', { name: 'Create team' }))
    expect(await within(section).findByRole('alert')).toHaveTextContent('already exists')
  })

  it('edits members: only active non-viewers are offered, and the exact ids are saved', async () => {
    const puts: unknown[] = []
    stubFetch(server('owner', [support], { onPut: (b) => puts.push(b) }))
    renderApp(<AppRoutes />, '/people')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit members of Support' }))
    const dialog = await screen.findByRole('dialog', { name: /members of support/i })
    expect(within(dialog).getByLabelText('Lena Okafor')).toBeChecked()
    expect(within(dialog).queryByLabelText('Tom Alvarez')).not.toBeInTheDocument()
    expect(within(dialog).queryByLabelText('Gina Gone')).not.toBeInTheDocument()
    await userEvent.click(within(dialog).getByLabelText('Jonas Weber'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save members' }))
    await waitFor(() => expect(puts).toEqual([{ user_ids: ['u2', 'u3'] }]))
  })

  it('asks before deleting and explains when a team is still in use', async () => {
    let deletes = 0
    stubFetch(server('owner', [support], { onDelete: () => (deletes++, { status: 409, body: { detail: { code: 'team_in_use', message: 'This team is used by 1 automation rule(s). Change or archive them first.' } } }) }))
    renderApp(<AppRoutes />, '/people')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete team Support' }))
    const dialog = await screen.findByRole('dialog')
    expect(deletes).toBe(0)
    expect(dialog).toHaveTextContent(/automations that use it/i)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete team' }))
    await waitFor(() => expect(deletes).toBe(1))
    expect(await screen.findByRole('alert')).toHaveTextContent('used by 1 automation rule')
  })
})
