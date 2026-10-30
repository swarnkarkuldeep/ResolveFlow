import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../lib/api'
import { fullTime } from '../../lib/format'
import type { AuditEntry, Member } from '../../lib/types'
import { Button, Select, Spinner } from '../../ui'
import { describeActivity } from '../ticket/queries'

interface AuditPageData {
  items: AuditEntry[]
  next_cursor: string | null
}

const ENTITY_LABEL: Record<string, string> = {
  ticket: 'Ticket',
  member: 'Member',
  invitation: 'Invitation',
  workspace: 'Workspace',
}

export function describeAudit(e: AuditEntry): string {
  const a = e.after ?? {}
  const b = e.before ?? {}
  switch (e.action) {
    case 'member.updated': {
      const parts: string[] = []
      if (a.role !== b.role) parts.push(`Role: ${String(b.role)} → ${String(a.role)}`)
      if (a.active !== b.active) parts.push(a.active ? 'Reactivated' : 'Deactivated')
      return parts.join('; ') || 'Member updated'
    }
    case 'invitation.created':
      return `Invited ${String(a.email)} as ${String(a.role)}`
    case 'invitation.revoked':
      return `Revoked the invitation for ${String(b.email)}`
    case 'invitation.accepted':
      return `${String(a.email)} accepted their invitation`
    case 'workspace.created':
      return `Created the workspace ${String(a.name)}`
    default:
      return describeActivity({ ...e, actor_name: e.actor_name })
  }
}

export function AuditPage() {
  const [entity, setEntity] = useState('')
  const [actor, setActor] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')

  const members = useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members') })

  const filters = new URLSearchParams()
  if (entity) filters.set('entity_type', entity)
  if (actor) filters.set('actor_id', actor)
  if (from) filters.set('from', new Date(`${from}T00:00:00`).toISOString())
  if (to) filters.set('to', new Date(`${to}T23:59:59`).toISOString())
  const qs = filters.toString()

  const log = useInfiniteQuery({
    queryKey: ['audit', qs],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams(filters)
      p.set('limit', '50')
      if (pageParam) p.set('cursor', pageParam)
      return api<AuditPageData>(`/api/audit?${p.toString()}`)
    },
    getNextPageParam: (last) => last.next_cursor,
  })
  const items = log.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[980px] px-6 py-8">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight">Audit log</h1>
            <p className="mt-1 text-[14px] text-slate">Every change to tickets, people and settings, with who made it.</p>
          </div>
          <a
            href={`/api/audit.csv${qs ? `?${qs}` : ''}`}
            download
            className="inline-flex h-9 items-center rounded-control border border-line bg-paper px-3.5 text-[14px] font-medium hover:bg-wash"
          >
            Export CSV
          </a>
        </div>

        <div className="mb-5 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-[13px] text-slate">
            Item type
            <Select value={entity} onChange={(e) => setEntity(e.target.value)} className="!w-auto text-ink">
              <option value="">All items</option>
              {Object.entries(ENTITY_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-[13px] text-slate">
            Person
            <Select value={actor} onChange={(e) => setActor(e.target.value)} className="!w-auto text-ink">
              <option value="">Anyone</option>
              {members.data?.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name}
                </option>
              ))}
            </Select>
          </label>
          <label className="flex flex-col gap-1 text-[13px] text-slate">
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 rounded-control border border-line bg-paper px-2 text-[14px] text-ink" />
          </label>
          <label className="flex flex-col gap-1 text-[13px] text-slate">
            To
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 rounded-control border border-line bg-paper px-2 text-[14px] text-ink" />
          </label>
        </div>

        {log.isPending && <Spinner label="Loading the audit log" />}
        {log.isError && <p className="text-danger">{log.error.message}</p>}
        {log.isSuccess && items.length === 0 && <p className="py-8 text-slate">No entries match these filters.</p>}
        {items.length > 0 && (
          <table className="w-full text-left text-[14px]">
            <thead className="text-[13px] text-slate">
              <tr className="border-b border-line">
                <th className="py-2 pr-3 font-medium">When</th>
                <th className="py-2 pr-3 font-medium">Who</th>
                <th className="py-2 pr-3 font-medium">What happened</th>
                <th className="py-2 font-medium">Item</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-b border-line/70 align-top">
                  <td className="tabular whitespace-nowrap py-2.5 pr-3 text-slate">
                    <time dateTime={e.created_at}>{fullTime(e.created_at)}</time>
                  </td>
                  <td className="py-2.5 pr-3">{e.actor_name ?? 'Someone'}</td>
                  <td className="py-2.5 pr-3">{describeAudit(e)}</td>
                  <td className="py-2.5 text-slate">
                    {ENTITY_LABEL[e.entity_type] ?? e.entity_type}
                    {e.entity_id ? ` ${e.entity_id.slice(0, 8)}` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {log.hasNextPage && (
          <div className="mt-4">
            <Button onClick={() => log.fetchNextPage()} disabled={log.isFetchingNextPage}>
              {log.isFetchingNextPage ? 'Loading…' : 'Show older entries'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
