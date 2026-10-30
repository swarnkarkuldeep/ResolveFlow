import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { copyText } from '../../lib/clipboard'
import type { ChannelSettings } from '../../lib/types'
import { Button, Field, FormError, Spinner, TextArea, TextInput } from '../../ui'

function CopyRow({ label, value, copyLabel, multiline = false }: { label: string; value: string; copyLabel: string; multiline?: boolean }) {
  const toast = useToast()
  return (
    <div className="mb-4">
      <p className="mb-1 text-[13px] text-slate">{label}</p>
      <div className="flex items-start gap-2">
        {multiline ? (
          <pre className="min-w-0 flex-1 overflow-x-auto rounded-control border border-line bg-fog px-3 py-2 text-[13px]">{value}</pre>
        ) : (
          <code className="min-w-0 flex-1 truncate rounded-control border border-line bg-fog px-3 py-2 text-[14px]">{value}</code>
        )}
        <Button aria-label={copyLabel} onClick={async () => toast((await copyText(value)) ? 'Copied' : 'Could not copy', 'info')}>
          Copy
        </Button>
      </div>
    </div>
  )
}

function Simulator() {
  const [fromEmail, setFromEmail] = useState('')
  const [fromName, setFromName] = useState('')
  const [subject, setSubject] = useState('Question about my order')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const send = useMutation({
    mutationFn: () =>
      api<{ status: string; ticket_id: string | null }>('/api/dev/simulate-inbound', {
        method: 'POST',
        body: { from_email: fromEmail.trim(), from_name: fromName.trim() || null, subject, text },
      }),
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    send.mutate()
  }

  return (
    <section aria-label="Simulate a customer email" className="mt-10 border-t border-line pt-6">
      <h2 className="text-[18px] font-semibold tracking-tight">Simulate a customer email</h2>
      <p className="mb-4 mt-1 max-w-[60ch] text-[14px] text-slate">
        Sends a message through the same path as a real inbound email, so you can see how it arrives without setting up an email provider.
      </p>
      <form onSubmit={submit} className="grid max-w-[560px] gap-4">
        <Field label="From email" htmlFor="sim-from">
          <TextInput id="sim-from" type="email" required value={fromEmail} onChange={(e) => setFromEmail(e.target.value)} />
        </Field>
        <Field label="From name" htmlFor="sim-name">
          <TextInput id="sim-name" value={fromName} onChange={(e) => setFromName(e.target.value)} />
        </Field>
        <Field label="Subject" htmlFor="sim-subject">
          <TextInput id="sim-subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </Field>
        <Field label="Message" htmlFor="sim-text">
          <TextArea id="sim-text" rows={4} required value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <FormError message={error} />
        <div className="flex items-center gap-4">
          <Button type="submit" variant="primary" disabled={!fromEmail.trim() || !text.trim() || send.isPending}>
            {send.isPending ? 'Sending…' : 'Send simulated email'}
          </Button>
          {send.data?.ticket_id && (
            <Link to={`/inbox/${send.data.ticket_id}`} className="text-accent underline underline-offset-2">
              Open the ticket
            </Link>
          )}
        </div>
      </form>
    </section>
  )
}

export function ChannelsPage() {
  const { can } = useAuth()
  const settings = useQuery({ queryKey: ['channels'], queryFn: () => api<ChannelSettings>('/api/settings/channels') })

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[760px] px-6 py-8">
        <h1 className="text-[24px] font-semibold tracking-tight">Channels</h1>
        <p className="mb-6 mt-1 text-[14px] text-slate">Where customers can reach you. Every message becomes a ticket.</p>
        {settings.isPending && <Spinner label="Loading channels" />}
        {settings.isError && <p className="text-danger">{settings.error.message}</p>}
        {settings.data && (
          <>
            <h2 className="mb-1 text-[18px] font-semibold tracking-tight">Email</h2>
            <p className="mb-3 max-w-[60ch] text-[14px] text-slate">
              Forward your support address to this address, or point your email provider’s inbound webhook at it. Replies from your team are sent from ResolveFlow and thread correctly.
            </p>
            <CopyRow label="Your inbound address" value={settings.data.inbound_address} copyLabel="Copy email address" />

            <h2 className="mb-1 mt-8 text-[18px] font-semibold tracking-tight">Web form</h2>
            <p className="mb-3 max-w-[60ch] text-[14px] text-slate">
              Share the link, or embed the form on your own site.{' '}
              <a href={settings.data.form_url} target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">
                Open the form
              </a>
            </p>
            <CopyRow label="Form link" value={settings.data.form_url} copyLabel="Copy form link" />
            <CopyRow label="Embed code" value={settings.data.form_snippet} copyLabel="Copy embed code" multiline />

            {settings.data.simulate_enabled && can('settings:update') && <Simulator />}
          </>
        )}
      </div>
    </div>
  )
}
