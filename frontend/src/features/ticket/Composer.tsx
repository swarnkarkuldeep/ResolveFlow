import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

import { useAuth } from '../../app/auth'
import { useToast } from '../../app/Toasts'
import { Button, FormError, TextArea } from '../../ui'
import { useSendMessage } from './queries'

type Kind = 'public' | 'note'
const draftKey = (ticketId: string, kind: Kind) => `rf-draft:${ticketId}:${kind}`

function loadDraft(ticketId: string, kind: Kind): string {
  try {
    return window.localStorage.getItem(draftKey(ticketId, kind)) ?? ''
  } catch {
    return ''
  }
}

function saveDraft(ticketId: string, kind: Kind, value: string) {
  try {
    if (value) window.localStorage.setItem(draftKey(ticketId, kind), value)
    else window.localStorage.removeItem(draftKey(ticketId, kind))
  } catch {
    /* storage unavailable: the draft just won't survive a reload */
  }
}

export function Composer({ ticketId }: { ticketId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const send = useSendMessage(ticketId)
  const [kind, setKind] = useState<Kind>('public')
  const [drafts, setDrafts] = useState<Record<Kind, string>>(() => ({
    public: loadDraft(ticketId, 'public'),
    note: loadDraft(ticketId, 'note'),
  }))
  const [waiting, setWaiting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const areaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const focus = () => {
      setKind('public')
      window.setTimeout(() => areaRef.current?.focus(), 0)
    }
    window.addEventListener('rf:reply', focus)
    return () => window.removeEventListener('rf:reply', focus)
  }, [])

  if (!can('ticket:reply')) {
    return (
      <p className="rounded-panel border border-line bg-fog px-4 py-3 text-[14px] text-slate">
        You have view-only access, so you can read this ticket but not reply to it.
      </p>
    )
  }

  const body = drafts[kind]
  const setBody = (value: string) => {
    setDrafts((d) => ({ ...d, [kind]: value }))
    saveDraft(ticketId, kind, value)
  }

  const submit = () => {
    const text = body.trim()
    if (!text || send.isPending) return
    setError(null)
    send.mutate(
      { body: text, kind, set_pending: kind === 'public' && waiting },
      {
        onSuccess: () => {
          setBody('')
          setWaiting(false)
          toast(kind === 'public' ? 'Reply sent' : 'Note added')
        },
        onError: (e) => setError(e.message),
      },
    )
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="rounded-panel border border-line bg-paper">
      <div role="tablist" aria-label="Message type" className="flex gap-1 border-b border-line px-2 pt-2">
        {(
          [
            ['public', 'Reply'],
            ['note', 'Internal note'],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            role="tab"
            type="button"
            aria-selected={kind === k}
            onClick={() => setKind(k)}
            className={`-mb-px rounded-t-control border-b-2 px-3 py-1.5 text-[14px] ${
              kind === k ? 'border-accent font-medium text-ink' : 'border-transparent text-slate hover:text-ink'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="p-3">
        <label htmlFor="composer" className="sr-only">
          Message
        </label>
        <TextArea
          id="composer"
          ref={areaRef}
          rows={3}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={kind === 'public' ? 'Write a reply to the customer…' : 'Write a note only your team can see…'}
          className="font-serif !text-[16px] !leading-relaxed"
        />
        <FormError message={error} />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          {kind === 'public' ? (
            <label className="flex items-center gap-2 text-[14px] text-slate">
              <input type="checkbox" checked={waiting} onChange={(e) => setWaiting(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
              Mark as waiting on customer
            </label>
          ) : (
            <span className="text-[13px] text-slate">Only your team can see this note.</span>
          )}
          <div className="flex items-center gap-3">
            <span className="hidden text-[12px] text-slate sm:inline">Ctrl+Enter to send</span>
            <Button variant="primary" onClick={submit} disabled={!body.trim() || send.isPending}>
              {send.isPending ? 'Sending…' : kind === 'public' ? 'Send reply' : 'Add note'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
