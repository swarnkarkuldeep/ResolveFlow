import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useParams } from 'react-router-dom'

import { api } from '../../lib/api'
import { Button, Field, FormError, Spinner, TextArea, TextInput } from '../../ui'

export function PublicFormPage() {
  const { slug = '' } = useParams()
  const info = useQuery({
    queryKey: ['public-form', slug],
    queryFn: () => api<{ workspace_name: string }>(`/api/public/forms/${slug}`, { skipUnauthorized: true }),
    retry: false,
  })
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [website, setWebsite] = useState('')
  const [error, setError] = useState<string | null>(null)

  const send = useMutation({
    mutationFn: () =>
      api<{ reference: string | null }>(`/api/public/forms/${slug}`, {
        method: 'POST',
        body: { name: name.trim() || null, email: email.trim(), subject: subject.trim(), message, website },
        skipUnauthorized: true,
      }),
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    send.mutate()
  }

  return (
    <div className="flex min-h-full justify-center bg-fog px-4 py-12">
      <div className="w-full max-w-[520px]">
        {info.isPending && <Spinner label="Loading" />}
        {info.isError && (
          <div>
            <h1 className="text-[22px] font-semibold tracking-tight">This form isn’t available</h1>
            <p className="mt-2 text-[14px] text-slate">The link may be out of date. Check it with the person who sent it to you.</p>
          </div>
        )}
        {info.data && send.isSuccess && (
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight">Thanks, we have your message</h1>
            <p className="mt-2 text-[15px] text-slate">
              {send.data.reference ? (
                <>
                  Your reference is <strong className="tabular text-ink">{send.data.reference}</strong>. We will reply by email.
                </>
              ) : (
                'We will reply by email.'
              )}
            </p>
          </div>
        )}
        {info.data && !send.isSuccess && (
          <>
            <h1 className="text-[26px] font-semibold leading-tight tracking-tight">Contact {info.data.workspace_name}</h1>
            <p className="mb-6 mt-1.5 text-[15px] text-slate">Tell us what you need and we will reply by email.</p>
            <form onSubmit={submit} className="grid gap-4">
              <Field label="Your name" htmlFor="pf-name">
                <TextInput id="pf-name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
              </Field>
              <Field label="Email" htmlFor="pf-email">
                <TextInput id="pf-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </Field>
              <Field label="Subject" htmlFor="pf-subject">
                <TextInput id="pf-subject" required value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
              </Field>
              <Field label="Message" htmlFor="pf-message">
                <TextArea id="pf-message" rows={6} required value={message} onChange={(e) => setMessage(e.target.value)} maxLength={10000} />
              </Field>
              {/* Honeypot: people never see or reach this; bots that fill every field give themselves away. */}
              <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
                <label>
                  Leave this empty
                  <input name="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
                </label>
              </div>
              <FormError message={error} />
              <Button type="submit" variant="primary" disabled={send.isPending || !email.trim() || !subject.trim() || !message.trim()}>
                {send.isPending ? 'Sending…' : 'Send message'}
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
