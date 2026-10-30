import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { Button, Field, FormError, TextInput } from '../../ui'
import { AuthLayout } from './AuthLayout'

export function LoginPage() {
  const { me, isLoading, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (!isLoading && me) return <Navigate to="/inbox" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(email.trim(), password)
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? '/inbox', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      lead="A shared inbox where every request has an owner and a deadline."
      footer={
        <>
          New here? <Link to="/signup" className="text-accent underline underline-offset-2">Create a workspace</Link>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label="Email" htmlFor="email">
          <TextInput id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <TextInput id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" disabled={pending || !email || !password}>
          {pending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AuthLayout>
  )
}
