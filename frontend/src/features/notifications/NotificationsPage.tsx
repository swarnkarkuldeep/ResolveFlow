import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { api } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import type { AppNotification, Delivery, NotificationKind, NotificationPref } from '../../lib/types'
import { Button, Spinner } from '../../ui'
import { useNotifications, useUnreadCount } from './queries'

const KIND_LABEL: Record<NotificationKind, { name: string; hint: string }> = {
  assigned: { name: 'A ticket is assigned to me', hint: 'Someone or a rule hands you a ticket.' },
  customer_reply: { name: 'A customer replies on my ticket', hint: 'Only tickets assigned to you.' },
  sla: { name: 'A service deadline is near or missed', hint: 'Tickets assigned to you, or any unassigned ticket if you are an owner or admin.' },
  escalation: { name: 'A ticket is escalated', hint: 'An automation escalates a ticket to you.' },
  rule: { name: 'An automation notifies me', hint: 'Notify actions from your automations.' },
}

function Preferences() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const prefs = useQuery({ queryKey: ['notification-prefs'], queryFn: () => api<NotificationPref[]>('/api/notification-prefs') })
  const save = useMutation({
    mutationFn: (next: NotificationPref[]) => api<NotificationPref[]>('/api/notification-prefs', { method: 'PUT', body: next }),
    onSuccess: (data) => {
      queryClient.setQueryData(['notification-prefs'], data)
      toast('Notification settings saved')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  if (!prefs.data) return prefs.isError ? <p className="text-danger">{prefs.error.message}</p> : <Spinner label="Loading settings" />

  const change = (kind: NotificationKind, field: 'in_app' | 'email', value: boolean) =>
    save.mutate(prefs.data.map((p) => (p.kind === kind ? { ...p, [field]: value } : p)).filter((p) => p.kind === kind))

  return (
    <section aria-label="Notification settings">
      <h2 className="text-[18px] font-semibold tracking-tight">What you hear about</h2>
      <p className="mb-3 mt-1 text-[14px] text-slate">Choose where each kind of notification reaches you.</p>
      <table className="w-full max-w-[720px] text-left text-[14px]">
        <thead>
          <tr className="text-[13px] text-slate">
            <th className="py-2 font-normal">When</th>
            <th className="w-20 py-2 font-normal">In the app</th>
            <th className="w-20 py-2 font-normal">By email</th>
          </tr>
        </thead>
        <tbody>
          {prefs.data.map((p) => (
            <tr key={p.kind} className="border-t border-line/70">
              <td className="py-3 pr-4">
                <p>{KIND_LABEL[p.kind].name}</p>
                <p className="text-[13px] text-slate">{KIND_LABEL[p.kind].hint}</p>
              </td>
              <td>
                <input
                  type="checkbox"
                  aria-label={`${KIND_LABEL[p.kind].name}: in the app`}
                  checked={p.in_app}
                  disabled={save.isPending}
                  onChange={(e) => change(p.kind, 'in_app', e.target.checked)}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
              </td>
              <td>
                <input
                  type="checkbox"
                  aria-label={`${KIND_LABEL[p.kind].name}: by email`}
                  checked={p.email}
                  disabled={save.isPending}
                  onChange={(e) => change(p.kind, 'email', e.target.checked)}
                  className="h-4 w-4 accent-[var(--accent)]"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function Problems() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const dead = useQuery({
    queryKey: ['deliveries', 'dead'],
    queryFn: () => api<{ items: Delivery[] }>('/api/notification-deliveries?status=dead'),
  })
  const retry = useMutation({
    mutationFn: (id: string) => api(`/api/notification-deliveries/${id}/retry`, { method: 'POST', body: {} }),
    onSuccess: () => {
      toast('Queued to send again')
      void queryClient.invalidateQueries({ queryKey: ['deliveries'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const items = dead.data?.items ?? []
  return (
    <section aria-label="Emails that could not be sent">
      <h2 className="text-[18px] font-semibold tracking-tight">Emails that could not be sent</h2>
      <p className="mb-3 mt-1 text-[14px] text-slate">After five failed attempts a notification email stops retrying. Send it again once the problem is fixed.</p>
      {dead.isSuccess && items.length === 0 && <p className="text-[14px] text-slate">Nothing is stuck. Every notification email went out.</p>}
      <ul>
        {items.map((d) => (
          <li key={d.id} className="flex flex-wrap items-start justify-between gap-3 border-t border-line/70 py-3 text-[14px]">
            <div className="min-w-0">
              <p>{d.title}</p>
              <p className="text-[13px] text-slate">
                To {d.recipient} · {d.attempts} attempts · {relativeTime(d.created_at)}
              </p>
              {d.error && <p className="text-[13px] text-danger">{d.error}</p>}
            </div>
            <Button onClick={() => retry.mutate(d.id)} disabled={retry.isPending} aria-label={`Send again: ${d.title}`}>
              Send again
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function NotificationsPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const list = useNotifications()
  const items = list.data ?? []
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['notifications'] })

  const markRead = useMutation({
    mutationFn: (id: string) => api(`/api/notifications/${id}/read`, { method: 'POST', body: {} }),
    onSuccess: () => void refresh(),
  })
  const readAll = useMutation({
    mutationFn: () => api('/api/notifications/read-all', { method: 'POST', body: {} }),
    onSuccess: () => void refresh(),
    onError: (e) => toast(e.message, 'error'),
  })

  const open = (n: AppNotification) => {
    if (!n.read) markRead.mutate(n.id)
    if (n.ticket) navigate(`/inbox/${n.ticket.id}`)
  }
  const unread = useUnreadCount().data ?? items.filter((n) => !n.read).length

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto flex max-w-[760px] flex-col gap-10 px-6 py-8">
        <section aria-label="Notifications">
          <div className="mb-3 flex items-end justify-between gap-4">
            <div>
              <h1 className="text-[24px] font-semibold tracking-tight">Notifications</h1>
              <p className="mt-1 text-[14px] text-slate">{unread > 0 ? `${unread} unread` : 'You are all caught up.'}</p>
            </div>
            <Button variant="ghost" onClick={() => readAll.mutate()} disabled={unread === 0 || readAll.isPending}>
              Mark all read
            </Button>
          </div>
          {list.isPending && <Spinner label="Loading notifications" />}
          {list.isError && <p className="text-danger">{list.error.message}</p>}
          {list.isSuccess && items.length === 0 && (
            <div className="py-6">
              <p className="font-medium">Nothing yet</p>
              <p className="mt-1 max-w-[48ch] text-[14px] text-slate">
                You will see assignments, customer replies and service-deadline alerts here.
              </p>
            </div>
          )}
          <ul aria-label="Notification list">
            {items.map((n) => (
              <li key={n.id} className="border-t border-line/70">
                <button
                  type="button"
                  onClick={() => open(n)}
                  className="flex w-full items-start gap-3 py-3 text-left hover:bg-wash/60"
                >
                  <span
                    aria-hidden="true"
                    className={`mt-2 h-2 w-2 shrink-0 rounded-full ${n.read ? 'bg-transparent' : 'bg-accent'}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className={`block text-[15px] ${n.read ? '' : 'font-medium'}`}>
                      {n.title}
                      {!n.read && <span className="sr-only"> (unread)</span>}
                    </span>
                    {n.body && <span className="block truncate text-[14px] text-slate">{n.body}</span>}
                  </span>
                  <span className="shrink-0 text-[13px] text-slate">{relativeTime(n.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <Preferences />
        {can('notification:admin') && <Problems />}
      </div>
    </div>
  )
}
