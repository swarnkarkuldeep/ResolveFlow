import { useState } from 'react'
import type { FormEvent } from 'react'

import { PRIORITIES, PRIORITY_LABEL, STATUSES, STATUS_LABEL } from '../../lib/types'
import type { Member, Priority, Status } from '../../lib/types'
import { Button, Select, TextInput } from '../../ui'
import type { Change } from './queries'

export function BulkBar({
  count,
  members,
  canAssign,
  onApply,
  onClear,
}: {
  count: number
  members: Member[]
  canAssign: boolean
  onApply: (change: Change) => void
  onClear: () => void
}) {
  const [tag, setTag] = useState('')

  const addTag = (e: FormEvent) => {
    e.preventDefault()
    const value = tag.trim()
    if (!value) return
    onApply({ kind: 'tag', value })
    setTag('')
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-paper px-3.5 py-2.5">
      <p className="mr-1 text-[14px] font-medium tabular" aria-live="polite">
        {count} selected
      </p>
      <Select
        aria-label="Set status"
        value=""
        className="!w-auto"
        onChange={(e) => e.target.value && onApply({ kind: 'status', value: e.target.value as Status })}
      >
        <option value="">Status…</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABEL[s]}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Set priority"
        value=""
        className="!w-auto"
        onChange={(e) => e.target.value && onApply({ kind: 'priority', value: e.target.value as Priority })}
      >
        <option value="">Priority…</option>
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {PRIORITY_LABEL[p]}
          </option>
        ))}
      </Select>
      {canAssign && (
        <Select
          aria-label="Assign to"
          value=""
          className="!w-auto"
          onChange={(e) => {
            const v = e.target.value
            if (!v) return
            if (v === 'none') return onApply({ kind: 'assign', value: null })
            const m = members.find((x) => x.user_id === v)
            if (m) onApply({ kind: 'assign', value: { id: m.user_id, name: m.name } })
          }}
        >
          <option value="">Assign…</option>
          <option value="none">Unassigned</option>
          {members
            .filter((m) => m.active && m.role !== 'viewer')
            .map((m) => (
              <option key={m.user_id} value={m.user_id}>
                {m.name}
              </option>
            ))}
        </Select>
      )}
      <form onSubmit={addTag} className="flex items-center gap-1.5">
        <TextInput aria-label="Tag name" placeholder="Add tag" value={tag} onChange={(e) => setTag(e.target.value)} maxLength={40} className="!h-9 !w-28" />
        <Button type="submit" disabled={!tag.trim()}>
          Add
        </Button>
      </form>
      <Button variant="ghost" onClick={onClear} className="ml-auto">
        Clear
      </Button>
    </div>
  )
}
