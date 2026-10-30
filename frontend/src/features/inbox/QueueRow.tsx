import { Link } from 'react-router-dom'

import { relativeTime } from '../../lib/format'
import type { TicketItem } from '../../lib/types'
import { Avatar, PriorityMark, StatusMark } from '../../ui'
import { SlaBadge } from '../sla/SlaBadge'

export function QueueRow({
  ticket,
  isOpen,
  isCursor,
  isSelected,
  selectable,
  search,
  onToggle,
  onFocusRow,
}: {
  ticket: TicketItem
  isOpen: boolean
  isCursor: boolean
  isSelected: boolean
  selectable: boolean
  search: string
  onToggle: () => void
  onFocusRow: () => void
}) {
  const name = ticket.requester.name || ticket.requester.email
  return (
    <li
      data-cursor={isCursor || undefined}
      className={`group relative border-b border-line/70 ${
        isSelected ? 'bg-wash' : isCursor ? 'bg-wash/70' : 'hover:bg-wash/50'
      } ${isOpen ? 'shadow-[inset_3px_0_0_var(--accent)]' : ''}`}
    >
      <div className="grid grid-cols-[22px_minmax(0,1fr)_auto] gap-x-2.5 px-3.5 py-3">
        <div className="relative z-10 flex h-5 items-center justify-center">
          {selectable && (
            <input
              type="checkbox"
              aria-label={`Select ticket ${ticket.number}`}
              checked={isSelected}
              onChange={onToggle}
              className={`h-4 w-4 accent-[var(--accent)] ${
                isSelected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
              }`}
            />
          )}
          {!selectable || !isSelected ? (
            <span className={`absolute ${selectable ? 'group-hover:hidden' : ''}`} aria-hidden="true">
              <StatusMark status={ticket.status} label={false} />
            </span>
          ) : null}
        </div>
        <Link
          to={{ pathname: `/inbox/${ticket.id}`, search }}
          onFocus={onFocusRow}
          aria-current={isOpen ? 'true' : undefined}
          className="min-w-0 after:absolute after:inset-0 after:content-['']"
        >
          <span className="flex items-center gap-2">
            <span className="truncate text-[14px] font-semibold">{name}</span>
            {ticket.possible_duplicate_of && (
              <span className="shrink-0 rounded-[4px] border border-line px-1.5 text-[12px] text-slate">Possible duplicate</span>
            )}
            <PriorityMark priority={ticket.priority} />
          </span>
          <span className="block truncate text-[14px]">{ticket.subject}</span>
          {ticket.snippet && <span className="block truncate text-[13px] text-slate">{ticket.snippet}</span>}
          {ticket.sla && ['running', 'at_risk', 'breached', 'paused'].includes(ticket.sla.state) && (
            <span className="mt-0.5 block">
              <SlaBadge sla={ticket.sla} />
            </span>
          )}
        </Link>
        <div className="flex flex-col items-end justify-between">
          <time dateTime={ticket.last_activity_at} className="tabular text-[12px] text-slate">
            {relativeTime(ticket.last_activity_at)}
          </time>
          {ticket.assignee && (
            <span title={`Assigned to ${ticket.assignee.name}`}>
              <Avatar name={ticket.assignee.name} size={22} />
              <span className="sr-only">Assigned to {ticket.assignee.name}</span>
            </span>
          )}
        </div>
      </div>
    </li>
  )
}
