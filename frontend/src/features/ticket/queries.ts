import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import type { ActivityEntry, Message, Priority, Status, TicketDetail, TicketPage } from '../../lib/types'

export function useTicket(id: string) {
  return useQuery({
    queryKey: ['ticket', id],
    queryFn: () => api<TicketDetail>(`/api/tickets/${id}`),
    // Replies are delivered by a background worker: poll until nothing is still queued.
    refetchInterval: (query) =>
      query.state.data?.messages.some((m) => m.delivery_status === 'queued') ? 4000 : false,
  })
}

export function useActivity(id: string) {
  return useQuery({
    queryKey: ['ticket', id, 'activity'],
    queryFn: () => api<ActivityEntry[]>(`/api/tickets/${id}/activity`),
  })
}

export interface TicketFields {
  status?: Status
  priority?: Priority
  assignee_id?: string | null
  tags?: string[]
}

export function usePatchTicket(id: string) {
  const queryClient = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ fields }: { fields: TicketFields; optimistic: Partial<TicketDetail> }) =>
      api<Partial<TicketDetail>>(`/api/tickets/${id}`, { method: 'PATCH', body: fields }),
    onMutate: async ({ optimistic }) => {
      await queryClient.cancelQueries({ queryKey: ['ticket', id] })
      const previous = queryClient.getQueryData<TicketDetail>(['ticket', id])
      queryClient.setQueryData<TicketDetail>(['ticket', id], (old) => (old ? { ...old, ...optimistic } : old))
      return { previous }
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(['ticket', id], context.previous)
      toast(error.message, 'error')
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['ticket', id] })
      void queryClient.invalidateQueries({ queryKey: ['tickets'] })
    },
  })
}

export function useSendMessage(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: { body: string; kind: 'public' | 'note'; set_pending: boolean }) =>
      api<Message>(`/api/tickets/${id}/messages`, { method: 'POST', body: input }),
    onSuccess: (message) => {
      queryClient.setQueryData<TicketDetail>(['ticket', id], (old) =>
        old && !old.messages.some((m) => m.id === message.id) ? { ...old, messages: [...old.messages, message] } : old,
      )
      void queryClient.invalidateQueries({ queryKey: ['ticket', id] })
      void queryClient.invalidateQueries({ queryKey: ['tickets'] })
    },
  })
}

export function useMergeCandidates(currentId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['merge-candidates'],
    enabled,
    queryFn: () => api<TicketPage>('/api/tickets?status=new,open,pending&limit=100'),
    select: (page) => page.items.filter((t) => t.id !== currentId && !t.merged_into_id),
  })
}

export function useMerge(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (intoId: string) =>
      api(`/api/tickets/${sourceId}/merge`, { method: 'POST', body: { into_id: intoId } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tickets'] })
      void queryClient.invalidateQueries({ queryKey: ['ticket'] })
    },
  })
}

export function describeActivity(e: ActivityEntry): string {
  const a = e.after ?? {}
  const b = e.before ?? {}
  switch (e.action) {
    case 'ticket.created':
      return `Ticket created${a.channel ? ` (${String(a.channel)})` : ''}`
    case 'ticket.updated': {
      const parts: string[] = []
      if ('status' in a) parts.push(`Status: ${String(b.status)} → ${String(a.status)}`)
      if ('priority' in a) parts.push(`Priority: ${String(b.priority)} → ${String(a.priority)}`)
      if ('assignee_id' in a) parts.push(a.assignee_id ? 'Assigned' : 'Unassigned')
      if ('tags' in a) parts.push(`Tags: ${(a.tags as string[]).join(', ') || 'none'}`)
      return parts.join('; ') || 'Ticket updated'
    }
    case 'message.added':
      return a.kind === 'note' ? 'Added an internal note' : 'Replied to the customer'
    case 'message.received':
      return 'Customer replied'
    case 'ticket.merged':
      return `Merged ticket #${String(a.source_number)} into this one`
    case 'ticket.merged_away':
      return 'Merged into another ticket'
    default:
      return e.action
  }
}
