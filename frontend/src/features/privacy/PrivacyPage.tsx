import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { Button, Field, Select, Spinner } from '../../ui'

interface Policy {
  retention_days: number | null
  eligible_tickets: number
}

const CHOICES = [
  { value: '', label: 'Keep everything' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '1 year' },
  { value: '730', label: '2 years' },
]

export function PrivacyPage() {
  const { can } = useAuth()
  const manage = can('settings:update')
  const queryClient = useQueryClient()
  const toast = useToast()
  const policy = useQuery({ queryKey: ['privacy'], queryFn: () => api<Policy>('/api/settings/privacy') })
  const [choice, setChoice] = useState('')
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    if (policy.data) setChoice(policy.data.retention_days ? String(policy.data.retention_days) : '')
  }, [policy.data])

  const save = useMutation({
    mutationFn: () => api<Policy>('/api/settings/privacy', { method: 'PUT', body: { retention_days: choice ? Number(choice) : null } }),
    onSuccess: (data) => {
      queryClient.setQueryData(['privacy'], data)
      toast('Retention saved')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const purge = useMutation({
    mutationFn: () => api<Policy & { tickets: number; customers: number }>('/api/settings/privacy/apply', { method: 'POST', body: {} }),
    onSuccess: (data) => {
      setConfirming(false)
      queryClient.setQueryData(['privacy'], { retention_days: data.retention_days, eligible_tickets: data.eligible_tickets })
      toast(`Removed the content of ${data.tickets} ${data.tickets === 1 ? 'ticket' : 'tickets'}`)
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const data = policy.data
  const dirty = data !== undefined && (data.retention_days ? String(data.retention_days) : '') !== choice

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[640px] px-6 py-8">
        <h1 className="text-[24px] font-semibold tracking-tight">Privacy</h1>
        <p className="mt-1 max-w-[56ch] text-[14px] text-slate">
          Decide how long finished tickets keep their content. Customer names and emails are removed once all of their tickets have expired.
        </p>
        {policy.isPending && <div className="mt-6"><Spinner label="Loading privacy settings" /></div>}
        {policy.isError && <p className="mt-6 text-danger">{policy.error.message}</p>}
        {data && (
          <section aria-label="Data retention" className="mt-8">
            <h2 className="text-[18px] font-semibold tracking-tight">Data retention</h2>
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <div className="w-60 max-w-full">
                <Field label="Remove content of resolved and closed tickets after" htmlFor="retention">
                  <Select id="retention" value={choice} disabled={!manage} onChange={(e) => setChoice(e.target.value)}>
                    {CHOICES.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              {manage && (
                <Button variant="primary" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
                  Save retention
                </Button>
              )}
            </div>
            <p className="mt-3 text-[14px] text-slate">
              The ticket number, dates, priority and service-level results stay so your numbers remain accurate. The audit log is not changed.
              {data.retention_days
                ? ' The check runs every hour.'
                : ' Nothing is removed while this is set to keep everything.'}
            </p>
            {data.retention_days !== null && (
              <div className="mt-6 rounded-panel border border-line p-4">
                <p className="text-[15px] font-medium">
                  {data.eligible_tickets === 0
                    ? 'No tickets are past the limit right now.'
                    : `${data.eligible_tickets} ${data.eligible_tickets === 1 ? 'ticket is' : 'tickets are'} past the limit.`}
                </p>
                {manage && data.eligible_tickets > 0 && !confirming && (
                  <Button className="mt-3" onClick={() => setConfirming(true)}>
                    Remove expired content now
                  </Button>
                )}
                {confirming && (
                  <div role="alert" className="mt-3">
                    <p className="text-[14px]">This permanently erases message text, subjects and customer details for those tickets. It cannot be undone.</p>
                    <div className="mt-3 flex gap-2">
                      <Button variant="primary" onClick={() => purge.mutate()} disabled={purge.isPending}>
                        Erase now
                      </Button>
                      <Button variant="ghost" onClick={() => setConfirming(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
