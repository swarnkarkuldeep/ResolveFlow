import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AppRoutes } from '../app/router'
import { api, setCsrf } from '../lib/api'
import { meFor, renderApp, stubFetch } from '../test-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrf('')
})

const unauthenticated = { status: 401, body: { detail: { code: 'unauthenticated', message: 'Sign in to continue.' } } }

describe('authentication', () => {
  it('sends a signed-out visitor to the sign-in page', async () => {
    stubFetch((url) => (url === '/api/auth/me' ? unauthenticated : undefined))
    renderApp(<AppRoutes />, '/inbox')
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeInTheDocument()
  })

  it('shows the API error without revealing which field was wrong', async () => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return unauthenticated
      if (url === '/api/auth/login')
        return { status: 401, body: { detail: { code: 'invalid_credentials', message: 'Email or password is incorrect.' } } }
    })
    renderApp(<AppRoutes />, '/login')
    await userEvent.type(await screen.findByLabelText(/email/i), 'owner@brightwork.test')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.')
  })

  it('signs in and lands on the inbox', async () => {
    let signedIn = false
    stubFetch((url) => {
      if (url === '/api/auth/me') return signedIn ? { body: meFor('owner') } : unauthenticated
      if (url === '/api/auth/login') {
        signedIn = true
        return { body: { csrf_token: 'csrf-test' } }
      }
      if (url.startsWith('/api/tickets')) return { body: { items: [], next_cursor: null } }
      if (url === '/api/members') return { body: [] }
    })
    renderApp(<AppRoutes />, '/login')
    await userEvent.type(await screen.findByLabelText(/email/i), 'owner@brightwork.test')
    await userEvent.type(screen.getByLabelText(/password/i), 'resolveflow-demo')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByRole('navigation', { name: /main/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /inbox/i })).toBeInTheDocument()
  })

  it('validates the password length before calling the API when signing up', async () => {
    const stub = stubFetch((url) => (url === '/api/auth/me' ? unauthenticated : undefined))
    renderApp(<AppRoutes />, '/signup')
    await userEvent.type(await screen.findByLabelText(/your name/i), 'Sam Owner')
    await userEvent.type(screen.getByLabelText(/workspace name/i), 'Acme')
    await userEvent.type(screen.getByLabelText(/email/i), 'sam@acme.test')
    await userEvent.type(screen.getByLabelText(/password/i), 'short')
    await userEvent.click(screen.getByRole('button', { name: /create workspace/i }))
    expect(await screen.findByText(/at least 10 characters/i)).toBeInTheDocument()
    expect(stub.calls.some((c) => c.url === '/api/auth/signup')).toBe(false)
  })

  it('explains an expired invitation in plain language', async () => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return unauthenticated
      if (url === '/api/auth/accept-invite')
        return { status: 410, body: { detail: { code: 'invite_used', message: 'This invitation has expired or was already used.' } } }
    })
    renderApp(<AppRoutes />, '/accept-invite?token=abc')
    await userEvent.type(await screen.findByLabelText(/your name/i), 'Ana Agent')
    await userEvent.type(screen.getByLabelText(/password/i), 'correct-horse-battery')
    await userEvent.click(screen.getByRole('button', { name: /join workspace/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('expired or was already used')
  })
})

describe('navigation by permission', () => {
  const navLinks = async (role: 'owner' | 'viewer' | 'agent') => {
    stubFetch((url) => {
      if (url === '/api/auth/me') return { body: meFor(role) }
      if (url.startsWith('/api/tickets')) return { body: { items: [], next_cursor: null } }
      if (url === '/api/members') return { body: [] }
    })
    renderApp(<AppRoutes />, '/inbox')
    const nav = await screen.findByRole('navigation', { name: /main/i })
    return Array.from(nav.querySelectorAll('a')).map((a) => a.getAttribute('aria-label') ?? a.textContent)
  }

  it('shows everything to an owner', async () => {
    expect(await navLinks('owner')).toEqual(['Inbox', 'Search', 'People', 'Channels', 'Automations', 'Analytics', 'Service levels', 'Audit log', 'Notifications'])
  })
  it('hides admin pages from a viewer', async () => {
    expect(await navLinks('viewer')).toEqual(['Inbox', 'Search', 'People', 'Notifications'])
  })
  it('hides channels and audit from an agent', async () => {
    expect(await navLinks('agent')).toEqual(['Inbox', 'Search', 'People', 'Notifications'])
  })
})

describe('api client', () => {
  it('sends the CSRF token on unsafe requests only', async () => {
    const stub = stubFetch(() => ({ body: {} }))
    setCsrf('tok-123')
    await api('/api/things', { method: 'POST', body: { a: 1 } })
    await api('/api/things')
    const [post, get] = stub.calls
    expect((post.init.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok-123')
    expect((get.init.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined()
  })

  it('returns the user to sign-in when any call comes back 401', async () => {
    let expired = false
    stubFetch((url) => {
      if (url === '/api/auth/me') return expired ? unauthenticated : { body: meFor('owner') }
      if (url.startsWith('/api/tickets')) return expired ? unauthenticated : { body: { items: [], next_cursor: null } }
      if (url === '/api/members') return { body: [] }
    })
    renderApp(<AppRoutes />, '/inbox')
    await screen.findByRole('navigation', { name: /main/i })
    expired = true
    await api('/api/tickets').catch(() => undefined)
    await waitFor(() => expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument())
  })

  it('turns a network failure into a plain message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    await expect(api('/api/x')).rejects.toMatchObject({ status: 0, message: expect.stringMatching(/unable to reach/i) })
  })
})
