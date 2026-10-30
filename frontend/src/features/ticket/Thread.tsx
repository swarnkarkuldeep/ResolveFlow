import { fullTime, relativeTime } from '../../lib/format'
import type { Message } from '../../lib/types'

function Delivery({ status }: { status: Message['delivery_status'] }) {
  if (status === 'sent') return <span className="text-[13px] text-slate">Sent</span>
  if (status === 'queued') return <span className="text-[13px] text-slate">Sending…</span>
  if (status === 'failed')
    return <span className="text-[13px] text-danger">Couldn’t send. The email was not delivered.</span>
  return null
}

export function Thread({ messages }: { messages: Message[] }) {
  return (
    <section aria-label="Conversation" className="flex flex-col gap-8">
      {messages.map((m) => {
        const note = m.kind === 'note'
        const outbound = m.direction === 'outbound'
        return (
          <article
            key={m.id}
            className={
              note
                ? 'rounded-panel border border-note-line bg-note px-5 py-4'
                : outbound
                  ? 'border-l-2 border-accent pl-5'
                  : ''
            }
          >
            <header className="mb-1.5 flex flex-wrap items-baseline gap-x-2 text-[13px] text-slate">
              <span className="text-[14px] font-medium text-ink">{m.author.name}</span>
              {note && <span className="font-medium text-ink">Internal note</span>}
              <time dateTime={m.created_at} title={fullTime(m.created_at)} className="tabular">
                {relativeTime(m.created_at)}
              </time>
            </header>
            <div className="letter">{m.body}</div>
            {outbound && (
              <p className="mt-2">
                <Delivery status={m.delivery_status} />
              </p>
            )}
          </article>
        )
      })}
    </section>
  )
}
