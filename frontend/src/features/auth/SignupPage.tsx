import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { Button, Field, FormError, TextInput } from '../../ui'
import { AuthLayout } from './AuthLayout'

export function SignupPage() {
  const { me, isLoading, signup } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (!isLoading && me) return <Navigate to="/inbox" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password.length < 10) {
      setPasswordError('Use at least 10 characters.')
      return
    }
    setPasswordError(null)
    setPending(true)
    try {
      await signup({ email: email.trim(), password, name: name.trim(), workspace_name: workspace.trim() })
      navigate('/inbox', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout
      title="Create your workspace"
      lead="You will be the owner. Invite your team once you are in."
      footer={
        <>
          Already have an account? <Link to="/login" className="text-accent underline underline-offset-2">Sign in</Link>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label="Your name" htmlFor="name">
          <TextInput id="name" autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Workspace name" htmlFor="workspace" hint="Usually your business name.">
          <TextInput id="workspace" required value={workspace} onChange={(e) => setWorkspace(e.target.value)} />
        </Field>
        <Field label="Email" htmlFor="email">
          <TextInput id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 10 characters." error={passwordError}>
          <TextInput id="password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" disabled={pending || !name || !workspace || !email || !password}>
          {pending ? 'Creating…' : 'Create workspace'}
        </Button>
      </form>
    </AuthLayout>
  )
}
