import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'

import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { PRIORITIES, PRIORITY_LABEL } from '../../lib/types'
import type { Priority, TicketItem } from '../../lib/types'
import { Button, Dialog, Field, FormError, Select, TextArea, TextInput } from '../../ui'

export function NewTicketDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (ticket: TicketItem) => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [priority, setPriority] = useState<Priority>('normal')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      api<TicketItem>('/api/tickets', {
        method: 'POST',
        body: { subject: subject.trim(), body: body.trim(), requester_email: email.trim(), requester_name: name.trim() || null, priority },
      }),
    onSuccess: (ticket) => {
      void queryClient.invalidateQueries({ queryKey: ['tickets'] })
      toast(`Ticket #${ticket.number} created`)
      onCreated(ticket)
    },
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    const next: Record<string, string> = {}
    if (!email.trim()) next.email = 'Customer email is required.'
    else if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) next.email = 'Enter a valid email address.'
    if (!subject.trim()) next.subject = 'Subject is required.'
    if (!body.trim()) next.body = 'Describe what happened. This is required.'
    setErrors(next)
    if (Object.keys(next).length === 0) create.mutate()
  }

  return (
    <Dialog title="New ticket" onClose={onClose} width={560}>
      <p className="mb-4 text-[14px] text-slate">For a request that did not arrive by email or the web form, such as a phone call.</p>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Customer email" htmlFor="nt-email" error={errors.email}>
            <TextInput id="nt-email" type="email" data-autofocus value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Customer name" htmlFor="nt-name">
            <TextInput id="nt-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
        <Field label="Subject" htmlFor="nt-subject" error={errors.subject}>
          <TextInput id="nt-subject" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
        </Field>
        <Field label="What happened" htmlFor="nt-body" error={errors.body}>
          <TextArea id="nt-body" rows={4} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <Field label="Priority" htmlFor="nt-priority">
          <Select id="nt-priority" value={priority} onChange={(e) => setPriority(e.target.value as Priority)} className="!w-auto">
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABEL[p]}
              </option>
            ))}
          </Select>
        </Field>
        <FormError message={error} />
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create ticket'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
