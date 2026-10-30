import type { Priority, TicketItem } from '../../lib/types'

export type ViewId = 'mine' | 'unassigned' | 'open' | 'done'

export interface View {
  id: ViewId
  label: string
  params: Record<string, string>
  empty: { title: string; body: string }
}

const OPEN = 'new,open,pending'

export const VIEWS: View[] = [
  {
    id: 'mine',
    label: 'Mine',
    params: { assignee: 'me', status: OPEN },
    empty: { title: 'Nothing assigned to you', body: 'Pick up a ticket from Unassigned and it will show up here.' },
  },
  {
    id: 'unassigned',
    label: 'Unassigned',
    params: { assignee: 'none', status: OPEN },
    empty: { title: 'Nothing waiting', body: 'New requests land here.' },
  },
  {
    id: 'open',
    label: 'All open',
    params: { status: OPEN },
    empty: { title: 'No open tickets', body: 'When a customer writes in or fills the form, the ticket appears here.' },
  },
  {
    id: 'done',
    label: 'Done',
    params: { status: 'resolved,closed' },
    empty: { title: 'Nothing resolved yet', body: 'Resolved and closed tickets are kept here.' },
  },
]

export const DEFAULT_VIEW: ViewId = 'open'

export function viewById(id: string | null): View {
  return VIEWS.find((v) => v.id === id) ?? VIEWS.find((v) => v.id === DEFAULT_VIEW)!
}

export interface Filters {
  view: ViewId
  priority: Priority | null
}

export function ticketQuery(filters: Filters): URLSearchParams {
  const p = new URLSearchParams(viewById(filters.view).params)
  if (filters.priority) p.set('priority', filters.priority)
  return p
}

/** Client-side mirror of the server filters, used to drop rows from the list optimistically. */
export function matchesFilters(t: TicketItem, filters: Filters, meId: string): boolean {
  const open = ['new', 'open', 'pending'].includes(t.status)
  const inView =
    filters.view === 'mine'
      ? open && t.assignee?.id === meId
      : filters.view === 'unassigned'
        ? open && t.assignee === null
        : filters.view === 'open'
          ? open
          : !open
  return inView && (!filters.priority || t.priority === filters.priority)
}
