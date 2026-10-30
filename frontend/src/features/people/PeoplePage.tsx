import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { copyText } from '../../lib/clipboard'
import { fullTime } from '../../lib/format'
import { ROLES, ROLE_LABEL } from '../../lib/types'
import type { Invitation, Member, Role } from '../../lib/types'
import { TeamsSection } from '../teams/TeamsSection'
import { Avatar, Button, Dialog, Field, FormError, Select, Spinner, TextInput } from '../../ui'

export function PeoplePage() {
  const { can, me } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const manage = can('user:manage')
  const invite = can('user:invite')
  const isOwner = me?.role === 'owner'

  const members = useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members') })
  const invitations = useQuery({
    queryKey: ['invitations'],
    enabled: invite,
    queryFn: () => api<Invitation[]>('/api/invitations'),
  })

  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<Member | null>(null)
  const [links, setLinks] = useState<Record<string, string>>({})
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('agent')

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: Role; active?: boolean } }) =>
      api(`/api/members/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['members'] })
    },
    onError: (e) => {
      setError(e.message)
      void queryClient.invalidateQueries({ queryKey: ['members'] })
    },
  })

  const send = useMutation({
    mutationFn: () => api<Invitation>('/api/invitations', { method: 'POST', body: { email: email.trim(), role } }),
    onSuccess: (inv) => {
      setError(null)
      if (inv.link) setLinks((l) => ({ ...l, [inv.id]: inv.link as string }))
      setEmail('')
      toast(`Invitation sent to ${inv.email}`)
      void queryClient.invalidateQueries({ queryKey: ['invitations'] })
    },
    onError: (e) => setError(e.message),
  })

  const revoke = useMutation({
    mutationFn: (id: string) => api(`/api/invitations/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('Invitation revoked')
      void queryClient.invalidateQueries({ queryKey: ['invitations'] })
    },
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (email.trim()) send.mutate()
  }

  const roleOptions = isOwner ? ROLES : ROLES.filter((r) => r !== 'owner')

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[860px] px-6 py-8">
        <h1 className="text-[24px] font-semibold tracking-tight">People</h1>
        <p className="mb-6 mt-1 text-[14px] text-slate">Everyone with access to this workspace.</p>
        <FormError message={error} />

        {members.isPending && <Spinner label="Loading people" />}
        {members.isError && <p className="text-danger">{members.error.message}</p>}
        {members.data && (
          <table className="mt-4 w-full text-left text-[14px]">
            <thead className="text-[13px] text-slate">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">Name</th>
                <th className="py-2 pr-3 font-medium">Role</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => {
                const locked = !isOwner && m.role === 'owner'
                return (
                  <tr key={m.user_id} className="border-b border-line/70">
                    <td className="py-3 pr-3">
                      <div className="flex items-center gap-3">
                        <Avatar name={m.name} size={32} />
                        <div>
                          <p className="font-medium">{m.name}</p>
                          <p className="text-[13px] text-slate">{m.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 pr-3">
                      {manage && m.active && !locked ? (
                        <Select
                          aria-label={`Role for ${m.name}`}
                          value={m.role}
                          onChange={(e) => update.mutate({ id: m.user_id, body: { role: e.target.value as Role } })}
                          className="!w-auto"
                        >
                          {roleOptions.map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABEL[r]}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        ROLE_LABEL[m.role]
                      )}
                    </td>
                    <td className="py-3 pr-3 text-slate">{m.active ? 'Active' : 'Deactivated'}</td>
                    <td className="py-3 text-right">
                      {manage && !locked &&
                        (m.active ? (
                          <Button variant="ghost" aria-label={`Deactivate ${m.name}`} onClick={() => setConfirming(m)}>
                            Deactivate
                          </Button>
                        ) : (
                          <Button variant="ghost" aria-label={`Reactivate ${m.name}`} onClick={() => update.mutate({ id: m.user_id, body: { active: true } })}>
                            Reactivate
                          </Button>
                        ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {invite && (
          <>
            <h2 className="mb-1 mt-10 text-[18px] font-semibold tracking-tight">Invite a teammate</h2>
            <p className="mb-4 text-[14px] text-slate">They get an email with a link that works once.</p>
            <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
              <div className="w-72 max-w-full">
                <Field label="Email" htmlFor="invite-email">
                  <TextInput id="invite-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
                </Field>
              </div>
              <Field label="Role" htmlFor="invite-role">
                <Select id="invite-role" value={role} onChange={(e) => setRole(e.target.value as Role)} className="!w-auto">
                  {roleOptions.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABEL[r]}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button type="submit" variant="primary" disabled={!email.trim() || send.isPending}>
                Send invitation
              </Button>
            </form>

            {invitations.data && invitations.data.length > 0 && (
              <section aria-label="Pending invitations" className="mt-8">
                <h3 className="mb-2 text-[15px] font-semibold">Pending invitations</h3>
                <ul>
                  {invitations.data.map((inv) => (
                    <li key={inv.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70 py-2.5 text-[14px]">
                      <span>
                        <span className="font-medium">{inv.email}</span>{' '}
                        <span className="text-slate">
                          · {ROLE_LABEL[inv.role]} · expires {fullTime(inv.expires_at)}
                        </span>
                      </span>
                      <span className="flex gap-1">
                        {links[inv.id] && (
                          <Button
                            variant="ghost"
                            aria-label={`Copy link for ${inv.email}`}
                            onClick={async () => toast((await copyText(links[inv.id])) ? 'Link copied' : 'Could not copy the link', 'info')}
                          >
                            Copy link
                          </Button>
                        )}
                        <Button variant="ghost" aria-label={`Revoke invitation for ${inv.email}`} onClick={() => revoke.mutate(inv.id)}>
                          Revoke
                        </Button>
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
        <TeamsSection />
      </div>

      {confirming && (
        <Dialog title={`Deactivate ${confirming.name}?`} onClose={() => setConfirming(null)}>
          <p className="mb-5 text-[14px] text-slate">
            They will be signed out and lose access immediately. Their tickets stay assigned to them until you reassign them. You can reactivate them later.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              data-autofocus
              onClick={() => {
                update.mutate({ id: confirming.user_id, body: { active: false } })
                setConfirming(null)
              }}
            >
              Deactivate
            </Button>
          </div>
        </Dialog>
      )}
    </div>
  )
}
