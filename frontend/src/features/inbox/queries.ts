import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { InfiniteData, QueryClient } from '@tanstack/react-query'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { STATUS_LABEL } from '../../lib/types'
import type { Member, Priority, Status, TicketItem, TicketPage } from '../../lib/types'
import { matchesFilters, ticketQuery } from './views'
import type { Filters } from './views'

export function useTickets(filters: Filters) {
  return useInfiniteQuery({
    queryKey: ['tickets', filters],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = ticketQuery(filters)
      params.set('limit', '50')
      if (pageParam) params.set('cursor', pageParam)
      return api<TicketPage>(`/api/tickets?${params.toString()}`)
    },
    getNextPageParam: (last) => last.next_cursor,
    // A shared inbox: show what arrived while you were looking elsewhere, without a manual refresh.
    staleTime: 0,
    refetchInterval: 20_000,
  })
}

export function useMembers() {
  return useQuery({ queryKey: ['members'], queryFn: () => api<Member[]>('/api/members') })
}

export type Change =
  | { kind: 'status'; value: Status }
  | { kind: 'priority'; value: Priority }
  | { kind: 'assign'; value: { id: string; name: string } | null }
  | { kind: 'tag'; value: string }

function applyChange(t: TicketItem, c: Change): TicketItem {
  switch (c.kind) {
    case 'status':
      return { ...t, status: c.value }
    case 'priority':
      return { ...t, priority: c.value }
    case 'assign':
      return { ...t, assignee: c.value, status: c.value && t.status === 'new' ? 'open' : t.status }
    case 'tag':
      return t.tags.includes(c.value) ? t : { ...t, tags: [...t.tags, c.value].sort() }
  }
}

type Snapshot = [readonly unknown[], unknown][]

function patchCache(queryClient: QueryClient, ids: string[], change: Change, meId: string): Snapshot {
  const snapshot: Snapshot = queryClient.getQueriesData({ queryKey: ['tickets'] })
  for (const [key, data] of snapshot) {
    const filters = key[1] as Filters
    const pages = (data as InfiniteData<TicketPage> | undefined)?.pages
    if (!pages) continue
    queryClient.setQueryData<InfiniteData<TicketPage>>(key, {
      ...(data as InfiniteData<TicketPage>),
      pages: pages.map((p) => ({
        ...p,
        items: p.items
          .map((t) => (ids.includes(t.id) ? applyChange(t, change) : t))
          .filter((t) => !ids.includes(t.id) || matchesFilters(t, filters, meId)),
      })),
    })
  }
  return snapshot
}

function restore(queryClient: QueryClient, snapshot: Snapshot) {
  for (const [key, data] of snapshot) queryClient.setQueryData(key, data)
}

function bulkBody(ids: string[], change: Change) {
  switch (change.kind) {
    case 'status':
      return { ids, action: 'status', value: change.value }
    case 'priority':
      return { ids, action: 'priority', value: change.value }
    case 'assign':
      return { ids, action: 'assign', value: change.value?.id ?? 'none' }
    case 'tag':
      return { ids, action: 'add_tag', value: change.value }
  }
}

function patchBody(change: Change) {
  switch (change.kind) {
    case 'status':
      return { status: change.value }
    case 'priority':
      return { priority: change.value }
    case 'assign':
      return { assignee_id: change.value?.id ?? null }
    case 'tag':
      return null
  }
}

/** Applies one change to one or many tickets: optimistic, rolled back with a plain error on failure. */
export function useTicketChange() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const { me } = useAuth()
  const meId = me?.user.id ?? ''

  return useMutation({
    mutationFn: async ({ ids, change, bulk = false }: { ids: string[]; change: Change; bulk?: boolean }) => {
      const single = patchBody(change)
      if (ids.length === 1 && single && !bulk) {
        await api(`/api/tickets/${ids[0]}`, { method: 'PATCH', body: single })
      } else {
        await api('/api/tickets/bulk', { method: 'POST', body: bulkBody(ids, change) })
      }
    },
    onMutate: async ({ ids, change }) => {
      await queryClient.cancelQueries({ queryKey: ['tickets'] })
      return { snapshot: patchCache(queryClient, ids, change, meId) }
    },
    onError: (error, _vars, context) => {
      if (context) restore(queryClient, context.snapshot)
      toast(error.message, 'error')
    },
    onSuccess: (_data, { ids, change }) => {
      const what =
        change.kind === 'status'
          ? `marked ${STATUS_LABEL[change.value].toLowerCase()}`
          : change.kind === 'priority'
            ? `set to ${change.value} priority`
            : change.kind === 'assign'
              ? change.value
                ? `assigned to ${change.value.name}`
                : 'unassigned'
              : `tagged ${change.value}`
      toast(ids.length === 1 ? `Ticket ${what}` : `${ids.length} tickets ${what}`)
    },
    onSettled: (_d, _e, { ids }) => {
      void queryClient.invalidateQueries({ queryKey: ['tickets'] })
      for (const id of ids) void queryClient.invalidateQueries({ queryKey: ['ticket', id] })
    },
  })
}
