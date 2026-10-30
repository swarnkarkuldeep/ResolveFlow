import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import type { CustomerHistory } from '../../lib/types'
import { PriorityMark, Spinner, StatusMark } from '../../ui'

export function CustomerPage() {
  const { id } = useParams()
  const q = useQuery({ queryKey: ['customer', id], enabled: !!id, queryFn: () => api<CustomerHistory>(`/api/customers/${id}`) })

  if (q.isPending) return <div className="p-6"><Spinner label="Loading customer" /></div>
  if (q.isError) {
    return (
      <div className="mx-auto max-w-[760px] px-6 py-8">
        <p className="font-medium">We could not find that customer</p>
        <Link to="/inbox" className="text-[14px] text-accent underline underline-offset-2">Back to the inbox</Link>
      </div>
    )
  }
  const { customer, tickets, stats } = q.data
  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto max-w-[760px] px-6 py-8">
        <Link to="/inbox" className="text-[14px] text-slate hover:text-ink">← Inbox</Link>
        <h1 className="mb-1 mt-2 text-[24px] font-semibold tracking-tight">{customer.name || customer.email}</h1>
        <p className="text-[14px] text-slate">
          {customer.name ? `${customer.email} · ` : ''}
          {stats.total} {stats.total === 1 ? 'ticket' : 'tickets'}, {stats.open} open · first contact {relativeTime(customer.since)}
        </p>
        <h2 className="mb-2 mt-8 text-[18px] font-semibold tracking-tight">History</h2>
        <ul aria-label="Ticket history">
          {tickets.map((t) => (
            <li key={t.id} className="border-t border-line/70 py-3">
              <Link to={`/inbox/${t.id}`} className="flex items-center gap-2 text-[15px] font-medium hover:text-accent">
                <StatusMark status={t.status} label={false} />
                <span className="truncate">{t.subject}</span>
                <span className="shrink-0 text-[13px] font-normal text-slate">#{t.number}</span>
              </Link>
              <p className="mt-0.5 flex items-center gap-2 text-[13px] text-slate">
                <PriorityMark priority={t.priority} />
                <span>{t.assignee ? `Assigned to ${t.assignee.name}` : 'Unassigned'}</span>
                <span>· {relativeTime(t.last_activity_at)}</span>
              </p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
