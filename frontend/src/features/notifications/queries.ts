import { useQuery } from '@tanstack/react-query'

import { api } from '../../lib/api'
import type { AppNotification } from '../../lib/types'

export const UNREAD_KEY = ['notifications', 'unread-count']

/** Polled: the bell stays current without a second transport to keep alive. */
export function useUnreadCount() {
  return useQuery({
    queryKey: UNREAD_KEY,
    queryFn: () => api<{ count: number }>('/api/notifications/unread-count'),
    refetchInterval: 20_000,
    select: (d) => d.count,
  })
}

export function useNotifications() {
  return useQuery({
    queryKey: ['notifications', 'list'],
    queryFn: () => api<{ items: AppNotification[] }>('/api/notifications?limit=50'),
    refetchInterval: 20_000,
    select: (d) => d.items,
  })
}
