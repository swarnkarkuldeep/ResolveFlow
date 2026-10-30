import { Keyboard } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { PRIORITIES, PRIORITY_LABEL } from '../../lib/types'
import type { Priority } from '../../lib/types'
import { Button, Select, Spinner } from '../../ui'
import { TicketPane } from '../ticket/TicketPane'
import { BulkBar } from './BulkBar'
import { KEYS, shouldIgnoreKey } from './keys'
import type { KeyActions } from './keys'
import { QueueRow } from './QueueRow'
import { useMembers, useTicketChange, useTickets } from './queries'
import type { Change } from './queries'
import { ShortcutsDialog } from './ShortcutsDialog'
import { VIEWS, viewById } from './views'
import type { Filters } from './views'

export function InboxPage() {
  const { ticketId } = useParams()
  const navigate = useNavigate()
  const [search, setSearch] = useSearchParams()
  const { me, can } = useAuth()

  const view = viewById(search.get('view'))
  const priorityParam = search.get('priority')
  const priority = PRIORITIES.includes(priorityParam as Priority) ? (priorityParam as Priority) : null
  const filters = useMemo<Filters>(() => ({ view: view.id, priority }), [view.id, priority])

  const tickets = useTickets(filters)
  const members = useMembers()
  const change = useTicketChange()
  const items = useMemo(() => tickets.data?.pages.flatMap((p) => p.items) ?? [], [tickets.data])

  const [cursor, setCursor] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [helpOpen, setHelpOpen] = useState(false)
  const filterRef = useRef<HTMLSelectElement>(null)

  const canSelect = can('ticket:bulk')
  const cursorIndex = items.length === 0 ? -1 : Math.min(cursor, items.length - 1)
  const cursorTicket = cursorIndex >= 0 ? items[cursorIndex] : undefined

  const [seenFilters, setSeenFilters] = useState(filters)
  if (seenFilters !== filters) {
    setSeenFilters(filters)
    setSelected(new Set())
    setCursor(0)
  }

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(search)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearch(next, { replace: true })
  }

  const targets = useCallback((): string[] => {
    if (selected.size > 0) return [...selected]
    return cursorTicket ? [cursorTicket.id] : []
  }, [selected, cursorTicket])

  const apply = useCallback(
    (c: Change) => {
      const ids = targets()
      if (ids.length === 0) return
      const bulk = selected.size > 0
      setSelected(new Set())
      change.mutate({ ids, change: c, bulk })
    },
    [targets, change, selected],
  )

  const actions: KeyActions = {
    move: (delta) => items.length > 0 && setCursor(Math.max(0, Math.min(items.length - 1, cursorIndex + delta))),
    open: () => cursorTicket && navigate({ pathname: `/inbox/${cursorTicket.id}`, search: search.toString() }),
    toggleSelect: () => {
      if (!canSelect || !cursorTicket) return
      setSelected((s) => {
        const next = new Set(s)
        if (next.has(cursorTicket.id)) next.delete(cursorTicket.id)
        else next.add(cursorTicket.id)
        return next
      })
    },
    resolve: () => can('ticket:update') && apply({ kind: 'status', value: 'resolved' }),
    assignMe: () => can('ticket:assign') && me && apply({ kind: 'assign', value: { id: me.user.id, name: me.user.name } }),
    focusFilter: () => filterRef.current?.focus(),
    reply: () => window.dispatchEvent(new Event('rf:reply')),
    showHelp: () => setHelpOpen(true),
  }
  const actionsRef = useRef(actions)
  useEffect(() => {
    actionsRef.current = actions
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (shouldIgnoreKey(e) || document.querySelector('[role="dialog"]')) return
      const binding = KEYS.find((k) => k.key === e.key)
      if (!binding) return
      e.preventDefault()
      binding.run(actionsRef.current)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const rowSearch = search.toString() ? `?${search.toString()}` : ''

  return (
    <div className="flex h-full">
      <section
        aria-label="Tickets"
        className={`min-h-0 w-full flex-col border-r border-line bg-fog md:flex md:w-[420px] md:shrink-0 ${ticketId ? 'hidden' : 'flex'}`}
      >
        <header className="border-b border-line px-3.5 pb-3 pt-4">
          <div className="mb-3 flex items-center justify-between">
            <h1 className="text-[20px] font-semibold tracking-tight">Inbox</h1>
            <Button variant="ghost" onClick={() => setHelpOpen(true)} aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" className="!h-8 !w-8 !px-0">
              <Keyboard size={17} aria-hidden="true" />
            </Button>
          </div>
          <div role="tablist" aria-label="Views" className="flex gap-1">
            {VIEWS.map((v) => (
              <button
                key={v.id}
                role="tab"
                type="button"
                aria-selected={v.id === view.id}
                onClick={() => setParam('view', v.id === 'open' ? null : v.id)}
                className={`rounded-control px-2.5 py-1 text-[14px] ${
                  v.id === view.id ? 'bg-paper font-medium text-ink shadow-[inset_0_0_0_1px_var(--line)]' : 'text-slate hover:text-ink'
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
          <div className="mt-3">
            <Select
              ref={filterRef}
              aria-label="Priority"
              value={priority ?? ''}
              onChange={(e) => setParam('priority', e.target.value || null)}
              className="!w-auto !h-8 text-[13px]"
            >
              <option value="">Any priority</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {PRIORITY_LABEL[p]}
                </option>
              ))}
            </Select>
          </div>
        </header>

        {selected.size > 0 && (
          <BulkBar
            count={selected.size}
            members={members.data ?? []}
            canAssign={can('ticket:assign')}
            onApply={apply}
            onClear={() => setSelected(new Set())}
          />
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tickets.isPending && <Spinner label="Loading tickets" />}
          {tickets.isError && (
            <div className="px-5 py-8">
              <p className="font-medium">Could not load tickets</p>
              <p className="mb-3 text-[14px] text-slate">{tickets.error.message}</p>
              <Button onClick={() => tickets.refetch()}>Try again</Button>
            </div>
          )}
          {tickets.isSuccess && items.length === 0 && (
            <div className="px-5 py-10">
              <p className="font-medium">{view.empty.title}</p>
              <p className="mt-1 max-w-[32ch] text-[14px] text-slate">{view.empty.body}</p>
              {view.id === 'mine' && (
                <Button className="mt-4" onClick={() => setParam('view', 'unassigned')}>
                  See unassigned tickets
                </Button>
              )}
            </div>
          )}
          {items.length > 0 && (
            <ul>
              {items.map((t, i) => (
                <QueueRow
                  key={t.id}
                  ticket={t}
                  isOpen={t.id === ticketId}
                  isCursor={i === cursorIndex}
                  isSelected={selected.has(t.id)}
                  selectable={canSelect}
                  search={rowSearch}
                  onFocusRow={() => setCursor(i)}
                  onToggle={() => {
                    setCursor(i)
                    setSelected((s) => {
                      const next = new Set(s)
                      if (next.has(t.id)) next.delete(t.id)
                      else next.add(t.id)
                      return next
                    })
                  }}
                />
              ))}
            </ul>
          )}
          {tickets.hasNextPage && (
            <div className="p-3">
              <Button className="w-full" onClick={() => tickets.fetchNextPage()} disabled={tickets.isFetchingNextPage}>
                {tickets.isFetchingNextPage ? 'Loading…' : 'Show older tickets'}
              </Button>
            </div>
          )}
        </div>
      </section>

      <section aria-label="Ticket" className={`min-w-0 flex-1 bg-paper md:block ${ticketId ? 'block' : 'hidden'}`}>
        {ticketId ? (
          <TicketPane key={ticketId} ticketId={ticketId} backTo={{ pathname: '/inbox', search: rowSearch }} />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-1 p-8 text-center">
            <p className="font-serif text-[20px]">Select a ticket to read it</p>
            <p className="text-[14px] text-slate">
              Press <kbd className="rounded-[5px] border border-line bg-wash px-1.5 text-[12px]">?</kbd> for keyboard shortcuts.
            </p>
          </div>
        )}
      </section>

      {helpOpen && <ShortcutsDialog onClose={() => setHelpOpen(false)} />}
    </div>
  )
}
