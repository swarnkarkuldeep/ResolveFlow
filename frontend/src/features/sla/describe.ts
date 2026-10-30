import { formatRemaining, shortDue } from '../../lib/format'
import type { SlaMetric, SlaSummary } from '../../lib/types'

export type SlaTone = 'running' | 'at_risk' | 'breached' | 'paused'

export interface SlaNote {
  text: string
  tone: SlaTone
}

const DAY = 24 * 3600_000

/** Short badge copy for a ticket, or null when there is nothing worth saying (met / no policy). */
export function describeSla(sla: SlaSummary | undefined, now: number = Date.now()): SlaNote | null {
  if (!sla || sla.state === 'none' || sla.state === 'met') return null
  if (sla.state === 'paused') return { text: 'Paused', tone: 'paused' }
  const candidates = [sla.first_response, sla.resolution].filter(
    (m: SlaMetric) => m.state === sla.state && m.due_at,
  )
  if (candidates.length === 0) return null
  const due = Math.min(...candidates.map((m) => new Date(m.due_at as string).getTime()))
  if (sla.state === 'breached') return { text: `Breached ${formatRemaining(now - due)} ago`, tone: 'breached' }
  if (sla.state === 'at_risk') return { text: `At risk · ${formatRemaining(due - now)} left`, tone: 'at_risk' }
  const text = due - now < DAY ? `Due in ${formatRemaining(due - now)}` : `Due ${shortDue(new Date(due).toISOString())}`
  return { text, tone: 'running' }
}
