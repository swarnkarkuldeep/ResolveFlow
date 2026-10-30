import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import type { Member, Team } from '../../lib/types'
import { Button, Dialog, Field, FormError, TextInput } from '../../ui'

type Modal = { kind: 'members' | 'rename' | 'delete'; team: Team } | null

export function TeamsSection() {
  const { can } = useAuth()
  const manage = can('team:manage')
  const queryClient = useQueryClient()
  const toast = useToast()
  const teams = useQuery({ queryKey: ['teams'], queryFn: () => api<Team[]>('/api/teams') })
  const members = useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members') })
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [modal, setModal] = useState<Modal>(null)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['teams'] })

  const create = useMutation({
    mutationFn: () => api<Team>('/api/teams', { method: 'POST', body: { name: name.trim() } }),
    onSuccess: () => {
      setName('')
      setError(null)
      toast('Team created')
      void refresh()
    },
    onError: (e) => setError(e.message),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) create.mutate()
  }

  return (
    <section aria-label="Teams" className="mt-12">
      <h2 className="mb-1 text-[18px] font-semibold tracking-tight">Teams</h2>
      <p className="mb-4 max-w-[60ch] text-[14px] text-slate">
        Groups of teammates. Automation rules can hand new tickets to a team one person at a time.
      </p>
      {manage && (
        <form onSubmit={submit} className="mb-4 flex flex-wrap items-end gap-3">
          <div className="w-64 max-w-full">
            <Field label="Team name" htmlFor="team-name">
              <TextInput id="team-name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
            Create team
          </Button>
        </form>
      )}
      <FormError message={error} />
      {teams.isPending && <p className="text-[14px] text-slate">Loading teams…</p>}
      {teams.isError && <p className="text-[14px] text-slate">Teams could not be loaded.</p>}
      {teams.data && teams.data.length === 0 && (
        <p className="text-[14px] text-slate">{manage ? 'No teams yet. Create one to use round-robin assignment.' : 'No teams yet.'}</p>
      )}
      <ul>
        {teams.data?.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70 py-3">
            <div>
              <h3 className="text-[15px] font-medium">{t.name}</h3>
              <p className="text-[14px] text-slate">
                {t.members.length === 0 ? 'No members yet' : t.members.map((m) => m.name).join(', ')}
              </p>
            </div>
            {manage && (
              <div className="flex gap-1">
                <Button variant="ghost" aria-label={`Edit members of ${t.name}`} onClick={() => setModal({ kind: 'members', team: t })}>
                  Edit members
                </Button>
                <Button variant="ghost" aria-label={`Rename team ${t.name}`} onClick={() => setModal({ kind: 'rename', team: t })}>
                  Rename
                </Button>
                <Button variant="ghost" aria-label={`Delete team ${t.name}`} onClick={() => setModal({ kind: 'delete', team: t })}>
                  Delete
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {modal?.kind === 'members' && (
        <MembersDialog team={modal.team} people={members.data ?? []} onClose={() => setModal(null)} onSaved={() => (setModal(null), void refresh())} />
      )}
      {modal?.kind === 'rename' && <RenameDialog team={modal.team} onClose={() => setModal(null)} onSaved={() => (setModal(null), void refresh())} />}
      {modal?.kind === 'delete' && (
        <DeleteDialog
          team={modal.team}
          onClose={() => setModal(null)}
          onDone={() => {
            setModal(null)
            setError(null)
            toast('Team deleted')
            void refresh()
          }}
          onError={(m) => {
            setModal(null)
            setError(m)
          }}
        />
      )}
    </section>
  )
}

function MembersDialog({ team, people, onClose, onSaved }: { team: Team; people: Member[]; onClose: () => void; onSaved: () => void }) {
  const eligible = people.filter((p) => p.active && p.role !== 'viewer')
  const [selected, setSelected] = useState<string[]>(team.members.map((m) => m.user_id))
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => api(`/api/teams/${team.id}/members`, { method: 'PUT', body: { user_ids: eligible.filter((p) => selected.includes(p.user_id)).map((p) => p.user_id) } }),
    onSuccess: onSaved,
    onError: (e) => setError(e.message),
  })
  return (
    <Dialog title={`Members of ${team.name}`} onClose={onClose}>
      <p className="mb-3 text-[14px] text-slate">Only active teammates who can work on tickets can be added.</p>
      <ul className="mb-4 flex max-h-72 flex-col gap-1 overflow-y-auto">
        {eligible.map((p) => (
          <li key={p.user_id}>
            <label className="flex items-center gap-2.5 py-1 text-[15px]">
              <input
                type="checkbox"
                checked={selected.includes(p.user_id)}
                onChange={(e) => setSelected((s) => (e.target.checked ? [...s, p.user_id] : s.filter((x) => x !== p.user_id)))}
                className="h-4 w-4 accent-[var(--accent)]"
              />
              {p.name}
            </label>
          </li>
        ))}
      </ul>
      <FormError message={error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>
          Save members
        </Button>
      </div>
    </Dialog>
  )
}

function RenameDialog({ team, onClose, onSaved }: { team: Team; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(team.name)
  const [error, setError] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: () => api(`/api/teams/${team.id}`, { method: 'PATCH', body: { name: name.trim() } }),
    onSuccess: onSaved,
    onError: (e) => setError(e.message),
  })
  return (
    <Dialog title={`Rename ${team.name}`} onClose={onClose}>
      <Field label="Team name" htmlFor="rename-team">
        <TextInput id="rename-team" data-autofocus value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="mt-3">
        <FormError message={error} />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" onClick={() => save.mutate()} disabled={!name.trim() || save.isPending}>
          Save name
        </Button>
      </div>
    </Dialog>
  )
}

function DeleteDialog({ team, onClose, onDone, onError }: { team: Team; onClose: () => void; onDone: () => void; onError: (m: string) => void }) {
  const del = useMutation({
    mutationFn: () => api(`/api/teams/${team.id}`, { method: 'DELETE' }),
    onSuccess: onDone,
    onError: (e) => onError(e.message),
  })
  return (
    <Dialog title={`Delete ${team.name}?`} onClose={onClose}>
      <p className="mb-5 text-[14px] text-slate">
        The team is removed; its members stay in the workspace. Automations that use it must be changed or archived first.
      </p>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="danger" data-autofocus onClick={() => del.mutate()} disabled={del.isPending}>
          Delete team
        </Button>
      </div>
    </Dialog>
  )
}
