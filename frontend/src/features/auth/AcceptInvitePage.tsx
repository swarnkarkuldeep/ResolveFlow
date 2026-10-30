import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { Button, Field, FormError, TextInput } from '../../ui'
import { AuthLayout } from './AuthLayout'

export function AcceptInvitePage() {
  const { me, isLoading, acceptInvite } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (!isLoading && me) return <Navigate to="/inbox" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await acceptInvite({ token, name: name.trim(), password })
      navigate('/inbox', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPending(false)
    }
  }

  if (!token) {
    return (
      <AuthLayout title="Invitation link incomplete" lead="Open the full link from your invitation email, or ask your admin to send a new one.">
        {null}
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Join your team"
      lead="Choose a name and a password. If you already have a ResolveFlow account, use your current password."
    >
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label="Your name" htmlFor="name">
          <TextInput id="name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 10 characters for a new account.">
          <TextInput id="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" disabled={pending || !name || !password}>
          {pending ? 'Joining…' : 'Join workspace'}
        </Button>
      </form>
    </AuthLayout>
  )
}
