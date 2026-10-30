import type { SlaSummary } from '../../lib/types'
import { describeSla } from './describe'
import type { SlaTone } from './describe'

const COLOR: Record<SlaTone, string> = {
  running: 'var(--st-new)',
  at_risk: 'var(--st-pending)',
  breached: 'var(--pr-urgent)',
  paused: 'var(--slate)',
}

/** Text is always shown, never colour alone. */
export function SlaBadge({ sla }: { sla: SlaSummary | undefined }) {
  const note = describeSla(sla)
  if (!note) return null
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-slate">
      <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: COLOR[note.tone] }} />
      {note.text}
    </span>
  )
}
