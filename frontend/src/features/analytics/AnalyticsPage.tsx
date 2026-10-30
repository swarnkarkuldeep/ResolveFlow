import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../lib/api'
import { formatMinutes } from '../../lib/format'
import type { Analytics } from '../../lib/types'
import { PRIORITY_LABEL } from '../../lib/types'
import { Spinner } from '../../ui'

const RANGES = [7, 30, 90] as const

function Figure({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="min-w-[9rem]">
      <dt className="text-[13px] text-slate">{label}</dt>
      <dd className="mt-0.5 text-[26px] font-semibold leading-tight tracking-tight">{value}</dd>
      {note && <dd className="text-[13px] text-slate">{note}</dd>}
    </div>
  )
}

const pct = (v: number | null) => (v === null ? 'No data yet' : `${v}%`)
const mins = (v: number | null) => (v === null ? 'No data yet' : formatMinutes(v))

function Bars({ rows, label }: { rows: { name: string; value: number }[]; label: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (rows.length === 0) return <p className="text-[14px] text-slate">No tickets in this period.</p>
  return (
    <ul aria-label={label} className="flex flex-col gap-1.5">
      {rows.map((r) => (
        <li key={r.name} className="grid grid-cols-[8rem_minmax(0,1fr)_2.5rem] items-center gap-3 text-[14px]">
          <span className="truncate">{r.name}</span>
          <span className="h-2 rounded-full bg-wash">
            <span className="block h-2 rounded-full bg-accent" style={{ width: `${(100 * r.value) / max}%` }} />
          </span>
          <span className="text-right tabular-nums text-slate">{r.value}</span>
        </li>
      ))}
    </ul>
  )
}

function Daily({ days }: { days: Analytics['by_day'] }) {
  const max = Math.max(1, ...days.map((d) => d.created))
  return (
    <figure aria-label="Tickets created per day" className="m-0">
      <div className="flex h-24 items-end gap-[3px]" role="img" aria-label={`${days.reduce((a, d) => a + d.created, 0)} tickets created over ${days.length} days`}>
        {days.map((d) => (
          <span
            key={d.date}
            title={`${d.date}: ${d.created} created, ${d.resolved} resolved`}
            className="flex-1 rounded-t-sm bg-accent/80"
            style={{ height: `${Math.max(d.created ? 6 : 2, (100 * d.created) / max)}%`, opacity: d.created ? 1 : 0.25 }}
          />
        ))}
      </div>
      <figcaption className="mt-1.5 flex justify-between text-[12px] text-slate">
        <span>{days[0]?.date}</span>
        <span>{days[days.length - 1]?.date}</span>
      </figcaption>
    </figure>
  )
}

export function AnalyticsPage() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  const q = useQuery({ queryKey: ['analytics', days], queryFn: () => api<Analytics>(`/api/analytics?days=${days}`) })
  const d = q.data

  return (
    <div className="h-full overflow-y-auto bg-paper">
      <div className="mx-auto flex max-w-[860px] flex-col gap-9 px-6 py-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight">Analytics</h1>
            <p className="mt-1 text-[14px] text-slate">How the team is doing against its service levels. Days are counted in UTC.</p>
          </div>
          <div role="group" aria-label="Time range" className="flex rounded-control border border-line p-0.5">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                aria-pressed={days === r}
                onClick={() => setDays(r)}
                className={`h-8 rounded-[6px] px-3 text-[14px] ${days === r ? 'bg-wash font-medium' : 'text-slate hover:text-ink'}`}
              >
                Last {r} days
              </button>
            ))}
          </div>
        </div>
        {q.isPending && <Spinner label="Loading analytics" />}
        {q.isError && <p className="text-danger">{q.error.message}</p>}
        {d && (
          <>
            <dl aria-label="Summary" className="grid grid-cols-2 gap-6 sm:grid-cols-4">
              <Figure label="Tickets created" value={String(d.totals.created)} />
              <Figure label="Tickets resolved" value={String(d.totals.resolved)} />
              <Figure label="Open right now" value={String(d.totals.open_now)} />
              <Figure label="Deadlines missed" value={String(d.sla.breached)} />
            </dl>
            <section aria-label="Service levels">
              <h2 className="mb-3 text-[18px] font-semibold tracking-tight">Service levels</h2>
              <dl className="grid grid-cols-2 gap-6 sm:grid-cols-4">
                <Figure label="First response on time" value={pct(d.sla.first_response.compliance_pct)} note={`${d.sla.first_response.met} of ${d.sla.first_response.measured} tickets`} />
                <Figure label="Resolved on time" value={pct(d.sla.resolution.compliance_pct)} note={`${d.sla.resolution.met} of ${d.sla.resolution.measured} tickets`} />
                <Figure label="Average first response" value={mins(d.averages.first_response_minutes)} />
                <Figure label="Average time to resolve" value={mins(d.averages.resolution_minutes)} />
              </dl>
            </section>
            <section aria-label="Volume">
              <h2 className="mb-3 text-[18px] font-semibold tracking-tight">Volume</h2>
              <Daily days={d.by_day} />
            </section>
            <div className="grid gap-9 sm:grid-cols-2">
              <section aria-label="By priority">
                <h2 className="mb-3 text-[18px] font-semibold tracking-tight">By priority</h2>
                <Bars label="Tickets by priority" rows={d.by_priority.map((p) => ({ name: PRIORITY_LABEL[p.priority], value: p.count }))} />
              </section>
              <section aria-label="By channel">
                <h2 className="mb-3 text-[18px] font-semibold tracking-tight">By channel</h2>
                <Bars label="Tickets by channel" rows={d.by_channel.map((c) => ({ name: c.channel, value: c.count }))} />
              </section>
            </div>
            <section aria-label="By teammate">
              <h2 className="mb-3 text-[18px] font-semibold tracking-tight">By teammate</h2>
              {d.by_agent.length === 0 ? (
                <p className="text-[14px] text-slate">No tickets are assigned in this period.</p>
              ) : (
                <table className="w-full max-w-[520px] text-left text-[14px]">
                  <thead>
                    <tr className="text-[13px] text-slate">
                      <th className="py-1.5 font-normal">Teammate</th>
                      <th className="py-1.5 text-right font-normal">Assigned</th>
                      <th className="py-1.5 text-right font-normal">Resolved</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.by_agent.map((a) => (
                      <tr key={a.agent} className="border-t border-line/70">
                        <td className="py-2">{a.agent}</td>
                        <td className="py-2 text-right tabular-nums">{a.assigned}</td>
                        <td className="py-2 text-right tabular-nums">{a.resolved}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  )
}
