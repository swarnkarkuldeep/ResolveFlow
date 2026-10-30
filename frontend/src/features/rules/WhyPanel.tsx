import { useQuery } from '@tanstack/react-query'

import { api } from '../../lib/api'
import { relativeTime } from '../../lib/format'
import type { RuleExecution } from '../../lib/types'
import { EVENT_PHRASE } from './vocab'
import type { EventName } from './vocab'

const MARK: Record<string, string> = { applied: '✓', skipped: '–', failed: '✗' }
const LABEL: Record<string, string> = { applied: 'Applied', skipped: 'Skipped', failed: 'Failed' }

/** Why is this ticket the way it is? Lists every automation that ran on it and what each action did. */
export function WhyPanel({ ticketId }: { ticketId: string }) {
  const q = useQuery({
    queryKey: ['ticket', ticketId, 'rules'],
    queryFn: () => api<RuleExecution[]>(`/api/tickets/${ticketId}/rules`),
    retry: false,
  })
  const items = q.data
  if (!items || items.length === 0) return null
  return (
    <section aria-label="Automations on this ticket" className="mb-8">
      <details className="text-[14px]">
        <summary className="cursor-pointer text-slate hover:text-ink">Automations that ran ({items.length})</summary>
        <ul className="mt-3 flex max-w-[68ch] flex-col gap-4">
          {items.map((e, i) => (
            <li key={`${e.rule.id}-${e.at}-${i}`}>
              <p>
                <span className="font-medium">{e.rule.name}</span>{' '}
                <span className="text-slate">
                  <span>version {e.rule.version}</span> · When {EVENT_PHRASE[e.event as EventName] ?? e.event} · {relativeTime(e.at)}
                </span>
              </p>
              <ul className="mt-1.5 flex flex-col gap-1">
                {e.actions.map((a, j) => (
                  <li key={j} className="flex flex-col">
                    <span>
                      <span aria-hidden="true" className={a.status === 'failed' ? 'text-danger' : 'text-slate'}>
                        {MARK[a.status]}
                      </span>{' '}
                      <span>{a.text}</span>
                    </span>
                    <span className="ml-5 text-[13px] text-slate">
                      {a.status === 'applied' ? LABEL.applied : `${LABEL[a.status]}: ${a.reason ?? 'no reason recorded'}`}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}
