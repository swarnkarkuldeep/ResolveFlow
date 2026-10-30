import { ArrowLeft, GitMerge } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import type { To } from 'react-router-dom'

import { useAuth } from '../../app/auth'
import { fullTime, relativeTime } from '../../lib/format'
import { Button, Spinner } from '../../ui'
import { useMembers } from '../inbox/queries'
import { Composer } from './Composer'
import { MergeDialog } from './MergeDialog'
import { SlaPanel } from '../sla/SlaPanel'
import { Properties } from './Properties'
import { describeActivity, useActivity, useTicket } from './queries'
import { Thread } from './Thread'

const CHANNEL: Record<string, string> = { email: 'Email', form: 'Web form', manual: 'Added by hand' }

export function TicketPane({ ticketId, backTo }: { ticketId: string; backTo: To }) {
  const ticket = useTicket(ticketId)
  const members = useMembers()
  const activity = useActivity(ticketId)
  const { can } = useAuth()
  const navigate = useNavigate()
  const [merging, setMerging] = useState(false)

  if (ticket.isPending) return <Spinner label="Loading ticket" />
  if (ticket.isError) {
    const notFound = (ticket.error as { status?: number }).status === 404
    return (
      <div className="p-8">
        <p className="font-medium">{notFound ? 'Ticket not found' : 'Could not load this ticket'}</p>
        <p className="mb-3 mt-1 text-[14px] text-slate">
          {notFound ? 'It may have been removed, or it belongs to another workspace.' : ticket.error.message}
        </p>
        <Link to={backTo} className="text-accent underline underline-offset-2">
          Back to the inbox
        </Link>
      </div>
    )
  }

  const t = ticket.data
  const merged = !!t.merged_into_id

  return (
    <div data-testid="ticket-pane" data-ticket-id={t.id} className="pane-in flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <article className="mx-auto max-w-[760px] px-5 pb-10 pt-5 md:px-8">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 text-[13px] text-slate">
              <Link to={backTo} className="flex items-center gap-1 text-ink md:hidden" aria-label="Back to the inbox">
                <ArrowLeft size={16} aria-hidden="true" /> Inbox
              </Link>
              <span className="tabular font-medium text-ink">#{t.number}</span>
              <span>{CHANNEL[t.channel] ?? t.channel}</span>
              <time dateTime={t.created_at} title={fullTime(t.created_at)}>
                Opened {relativeTime(t.created_at)}
              </time>
            </div>
            {can('ticket:merge') && !merged && (
              <Button variant="ghost" onClick={() => setMerging(true)}>
                <GitMerge size={15} aria-hidden="true" /> Merge…
              </Button>
            )}
          </div>

          <h2 className="font-serif text-[28px] font-medium leading-tight tracking-tight">{t.subject}</h2>
          <p className="mb-5 mt-1.5 text-[14px] text-slate">
            {t.requester.name ? `${t.requester.name} · ` : ''}
            {t.requester.email}
          </p>

          {merged && (
            <p className="mb-5 rounded-panel border border-line bg-fog px-4 py-3 text-[14px]">
              This ticket was merged into another ticket, so its messages now live there.{' '}
              <Link to={{ pathname: `/inbox/${t.merged_into_id}` }} className="text-accent underline underline-offset-2">
                Open the other ticket
              </Link>
            </p>
          )}
          {t.possible_duplicate_of && !merged && (
            <p className="mb-5 rounded-panel border border-line bg-fog px-4 py-3 text-[14px]">
              This may be a duplicate of another recent ticket from the same person.{' '}
              <Link to={{ pathname: `/inbox/${t.possible_duplicate_of}` }} className="text-accent underline underline-offset-2">
                Open it
              </Link>
            </p>
          )}

          <div className="mb-8 border-y border-line py-4">
            <Properties ticket={t} members={members.data ?? []} />
          </div>

          <SlaPanel ticketId={t.id} />

          <Thread messages={t.messages} />

          <details className="mt-10 border-t border-line pt-4">
            <summary className="cursor-pointer text-[14px] font-medium text-slate hover:text-ink">History</summary>
            <ul className="mt-3 flex flex-col gap-2 text-[14px]">
              {activity.data?.map((e, i) => (
                <li key={`${e.created_at}-${i}`} className="flex flex-wrap gap-x-2">
                  <span>{describeActivity(e)}</span>
                  <span className="text-slate">
                    <span>{e.actor_name ?? 'Someone'}</span> · <time dateTime={e.created_at} className="tabular">{relativeTime(e.created_at)}</time>
                  </span>
                </li>
              ))}
              {activity.isPending && <li className="text-slate">Loading history…</li>}
            </ul>
          </details>
        </article>
      </div>
      {!merged && (
        <div className="border-t border-line bg-fog px-5 py-3 md:px-8">
          <div className="mx-auto max-w-[760px]">
            <Composer ticketId={t.id} />
          </div>
        </div>
      )}
      {merging && (
        <MergeDialog
          ticketId={t.id}
          number={t.number}
          onClose={() => setMerging(false)}
          onMerged={(into) => {
            setMerging(false)
            navigate({ pathname: `/inbox/${into}` })
          }}
        />
      )}
    </div>
  )
}
