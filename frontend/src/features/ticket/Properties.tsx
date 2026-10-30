import { X } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'

import { useAuth } from '../../app/auth'
import { PRIORITIES, PRIORITY_LABEL, STATUSES, STATUS_LABEL } from '../../lib/types'
import type { Member, Priority, Status, TicketDetail } from '../../lib/types'
import { Button, PriorityMark, Select, StatusMark, TextInput } from '../../ui'
import { usePatchTicket } from './queries'

function Row({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="text-[13px] text-slate">
        {label}
      </label>
      {children}
    </div>
  )
}

export function Properties({ ticket, members }: { ticket: TicketDetail; members: Member[] }) {
  const { me, can } = useAuth()
  const patch = usePatchTicket(ticket.id)
  const [tag, setTag] = useState('')
  const editable = can('ticket:update')
  const canAssign = can('ticket:assign')

  if (!editable) {
    return (
      <dl className="flex flex-wrap gap-x-8 gap-y-3 text-[14px]">
        <div>
          <dt className="text-[13px] text-slate">Status</dt>
          <dd><StatusMark status={ticket.status} /></dd>
        </div>
        <div>
          <dt className="text-[13px] text-slate">Priority</dt>
          <dd className="flex items-center gap-1">{PRIORITY_LABEL[ticket.priority]} <PriorityMark priority={ticket.priority} /></dd>
        </div>
        <div>
          <dt className="text-[13px] text-slate">Assignee</dt>
          <dd>{ticket.assignee?.name ?? 'Unassigned'}</dd>
        </div>
        {ticket.tags.length > 0 && (
          <div>
            <dt className="text-[13px] text-slate">Tags</dt>
            <dd>{ticket.tags.join(', ')}</dd>
          </div>
        )}
      </dl>
    )
  }

  const setStatus = (value: Status) => patch.mutate({ fields: { status: value }, optimistic: { status: value } })
  const setPriority = (value: Priority) => patch.mutate({ fields: { priority: value }, optimistic: { priority: value } })
  const setAssignee = (id: string | null) => {
    const m = members.find((x) => x.user_id === id)
    patch.mutate({
      fields: { assignee_id: id },
      optimistic: { assignee: id && m ? { id, name: m.name } : null, status: id && ticket.status === 'new' ? 'open' : ticket.status },
    })
  }
  const setTags = (tags: string[]) => patch.mutate({ fields: { tags }, optimistic: { tags } })

  const addTag = (e: FormEvent) => {
    e.preventDefault()
    const value = tag.trim()
    if (!value || ticket.tags.includes(value)) return setTag('')
    setTags([...ticket.tags, value].sort())
    setTag('')
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
        <Row label="Status" htmlFor="prop-status">
          <Select id="prop-status" value={ticket.status} onChange={(e) => setStatus(e.target.value as Status)} className="!w-auto">
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </Select>
        </Row>
        <Row label="Priority" htmlFor="prop-priority">
          <Select id="prop-priority" value={ticket.priority} onChange={(e) => setPriority(e.target.value as Priority)} className="!w-auto">
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABEL[p]}
              </option>
            ))}
          </Select>
        </Row>
        {canAssign && (
          <Row label="Assignee" htmlFor="prop-assignee">
            <div className="flex items-center gap-2">
              <Select id="prop-assignee" value={ticket.assignee?.id ?? ''} onChange={(e) => setAssignee(e.target.value || null)} className="!w-auto">
                <option value="">Unassigned</option>
                {members
                  .filter((m) => m.active && m.role !== 'viewer')
                  .map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.name}
                    </option>
                  ))}
              </Select>
              {me && ticket.assignee?.id !== me.user.id && (
                <Button onClick={() => setAssignee(me.user.id)}>Assign to me</Button>
              )}
            </div>
          </Row>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {ticket.tags.map((t) => (
          <span key={t} className="inline-flex items-center gap-1 rounded-full border border-line bg-fog py-0.5 pl-2.5 pr-1 text-[13px]">
            {t}
            <button
              type="button"
              aria-label={`Remove tag ${t}`}
              onClick={() => setTags(ticket.tags.filter((x) => x !== t))}
              className="flex h-5 w-5 items-center justify-center rounded-full text-slate hover:bg-wash hover:text-ink"
            >
              <X size={12} aria-hidden="true" />
            </button>
          </span>
        ))}
        <form onSubmit={addTag}>
          <TextInput aria-label="Add tag" placeholder="Add tag" value={tag} onChange={(e) => setTag(e.target.value)} maxLength={40} className="!h-8 !w-28 !text-[13px]" />
        </form>
      </div>
    </div>
  )
}
