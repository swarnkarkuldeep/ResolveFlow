import { useQuery } from '@tanstack/react-query'

import { api } from '../../lib/api'
import { useNow } from '../../lib/useNow'
import { formatMinutes, formatRemaining, fullTime, relativeTime, shortDue } from '../../lib/format'
import type { SlaExplain } from '../../lib/types'

type Metric = SlaExplain['metrics'][number]

function line(m: Metric, now: number): string {
  switch (m.state) {
    case 'met':
      return `${m.name}: met${m.met_at ? ` ${relativeTime(m.met_at)}` : ''}`
    case 'paused':
      return `${m.name}: paused, waiting on the customer`
    case 'breached':
      return `${m.name}: breached ${m.due_at ? formatRemaining(now - new Date(m.due_at).getTime()) : ''} ago`
    case 'at_risk':
    case 'running':
      return m.due_at
        ? `${m.name}: due ${shortDue(m.due_at)} · ${formatRemaining(new Date(m.due_at).getTime() - now)} left`
        : `${m.name}: running`
    default:
      return m.name
  }
}

const DOT: Record<string, string> = {
  running: 'var(--st-new)',
  at_risk: 'var(--st-pending)',
  breached: 'var(--pr-urgent)',
  paused: 'var(--slate)',
  met: 'var(--st-resolved)',
}

export function SlaPanel({ ticketId }: { ticketId: string }) {
  const q = useQuery({
    queryKey: ['ticket', ticketId, 'sla'],
    queryFn: () => api<SlaExplain>(`/api/tickets/${ticketId}/sla`),
    refetchInterval: 30_000,
    retry: false,
  })
  const now = useNow()
  const x = q.data
  if (!x || !x.policy.enabled || x.state === 'none') return null
  const visible = x.metrics.filter((m) => m.state !== 'none')

  return (
    <section aria-label="Service levels" className="mb-8">
      <ul className="flex flex-col gap-1.5 text-[14px]">
        {visible.map((m) => (
          <li key={m.key} className="flex items-center gap-2">
            <span aria-hidden="true" className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: DOT[m.state] ?? 'var(--slate)' }} />
            {line(m, now)}
          </li>
        ))}
      </ul>
      <details className="mt-2 text-[14px]">
        <summary className="cursor-pointer text-slate hover:text-ink">How is this calculated?</summary>
        <div className="mt-3 flex max-w-[64ch] flex-col gap-2 text-slate">
          <p>
            {x.policy.business_hours_only
              ? `Business hours only (${x.calendar.schedule_text}, ${x.calendar.timezone}${x.calendar.holidays ? `, ${x.calendar.holidays} closed dates` : ''}).`
              : 'Counts every hour, including nights and weekends.'}
          </p>
          {x.policy.targets && (
            <p>
              For {x.policy.priority} priority: first response within {formatMinutes(x.policy.targets.first_response_minutes)} and
              resolution within {formatMinutes(x.policy.targets.resolution_minutes)}. The clock pauses while the ticket is waiting on the customer.
            </p>
          )}
          {visible.map((m) => (
            <p key={m.key}>
              <span className="text-ink">{m.name}:</span>{' '}
              {m.target_minutes !== null && m.elapsed_minutes !== null
                ? `Used ${formatMinutes(Math.round(m.elapsed_minutes))} of ${formatMinutes(m.target_minutes)}.`
                : ''}
              {m.paused_minutes > 0 ? ` Paused for ${formatMinutes(Math.round(m.paused_minutes))}.` : ''}
            </p>
          ))}
          <ul className="mt-1 flex flex-col gap-1 border-t border-line pt-3">
            {x.events.map((e, i) => (
              <li key={`${e.at}-${i}`} className="flex flex-wrap gap-x-2">
                <span className="text-ink">{e.text}</span>
                <time dateTime={e.at} title={fullTime(e.at)} className="tabular">
                  {relativeTime(e.at)}
                </time>
              </li>
            ))}
          </ul>
        </div>
      </details>
    </section>
  )
}
