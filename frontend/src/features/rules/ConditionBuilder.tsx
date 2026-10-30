import { useState } from 'react'

import { Button, Select, TextInput } from '../../ui'
import {
  ENUM_VALUES,
  FIELD_LABEL,
  FIELD_OPERATORS,
  LIST_OPS,
  MAX_DEPTH,
  NO_VALUE,
  emptyCondition,
  isGroup,
  operatorLabel,
} from './vocab'
import type { Condition, FieldName, Group } from './vocab'

function defaultValue(field: FieldName, operator: string): Condition['value'] {
  if (NO_VALUE.has(operator)) return null
  const options = ENUM_VALUES[field]
  if (options) return LIST_OPS.has(operator) ? [options[0]] : options[0]
  return LIST_OPS.has(operator) ? [] : ''
}

function ConditionRow({ index, value, onChange, onRemove }: { index: number; value: Condition; onChange: (c: Condition) => void; onRemove: () => void }) {
  const options = ENUM_VALUES[value.field]
  const [raw, setRaw] = useState(Array.isArray(value.value) ? value.value.join(', ') : '')

  const setField = (field: FieldName) => {
    const operator = FIELD_OPERATORS[field][0]
    setRaw('')
    onChange({ field, operator, value: defaultValue(field, operator) })
  }
  const setOperator = (operator: string) => {
    setRaw('')
    onChange({ ...value, operator, value: defaultValue(value.field, operator) })
  }

  let control: React.ReactNode = null
  if (!NO_VALUE.has(value.operator)) {
    if (options && LIST_OPS.has(value.operator)) {
      const chosen = Array.isArray(value.value) ? value.value : []
      control = (
        <div role="group" aria-label="Value" className="flex flex-wrap gap-3">
          {options.map((o) => (
            <label key={o} className="flex items-center gap-1.5 text-[14px]">
              <input
                type="checkbox"
                checked={chosen.includes(o)}
                onChange={(e) => onChange({ ...value, value: e.target.checked ? [...chosen, o] : chosen.filter((x) => x !== o) })}
                className="h-4 w-4 accent-[var(--accent)]"
              />
              {o}
            </label>
          ))}
        </div>
      )
    } else if (options) {
      control = (
        <Select aria-label="Value" value={String(value.value ?? '')} onChange={(e) => onChange({ ...value, value: e.target.value })} className="!w-auto">
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </Select>
      )
    } else if (LIST_OPS.has(value.operator)) {
      control = (
        <TextInput
          aria-label="Value"
          placeholder="Words, separated by commas"
          value={raw}
          onChange={(e) => {
            setRaw(e.target.value)
            onChange({ ...value, value: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })
          }}
          className="!h-9 min-w-[14rem] flex-1"
        />
      )
    } else {
      control = (
        <TextInput
          aria-label="Value"
          value={typeof value.value === 'string' ? value.value : ''}
          maxLength={200}
          onChange={(e) => onChange({ ...value, value: e.target.value })}
          className="!h-9 min-w-[14rem] flex-1"
        />
      )
    }
  }

  return (
    <div role="group" aria-label={`Condition ${index + 1}`} className="flex flex-wrap items-center gap-2">
      <Select aria-label="Field" value={value.field} onChange={(e) => setField(e.target.value as FieldName)} className="!w-auto">
        {(Object.keys(FIELD_LABEL) as FieldName[]).map((f) => (
          <option key={f} value={f}>
            {FIELD_LABEL[f]}
          </option>
        ))}
      </Select>
      <Select aria-label="Operator" value={value.operator} onChange={(e) => setOperator(e.target.value)} className="!w-auto">
        {FIELD_OPERATORS[value.field].map((op) => (
          <option key={op} value={op}>
            {operatorLabel(value.field, op)}
          </option>
        ))}
      </Select>
      {control}
      <Button type="button" variant="ghost" aria-label="Remove condition" onClick={onRemove}>
        Remove
      </Button>
    </div>
  )
}

export function ConditionBuilder({
  group,
  onChange,
  depth = 1,
  label = 'Conditions',
  onRemove,
}: {
  group: Group
  onChange: (g: Group) => void
  depth?: number
  label?: string
  onRemove?: () => void
}) {
  const setItems = (items: Group['items']) => onChange({ ...group, items })
  let groupCount = 0
  return (
    <div role="group" aria-label={label} className={`flex flex-col gap-3 ${depth > 1 ? 'rounded-panel border border-line bg-fog p-3' : ''}`}>
      <div className="flex flex-wrap items-center gap-2 text-[14px]">
        <span className="text-slate">{depth === 1 ? 'Run this when' : 'Inside this group,'}</span>
        <Select aria-label="Match" value={group.op} onChange={(e) => onChange({ ...group, op: e.target.value as Group['op'] })} className="!w-auto">
          <option value="and">all of these match</option>
          <option value="or">any of these match</option>
        </Select>
        {onRemove && (
          <Button type="button" variant="ghost" onClick={onRemove} aria-label="Remove group" className="ml-auto">
            Remove group
          </Button>
        )}
      </div>
      {group.items.map((item, i) =>
        isGroup(item) ? (
          <ConditionBuilder
            key={i}
            group={item}
            depth={depth + 1}
            label={`Nested conditions ${++groupCount}`}
            onChange={(g) => setItems(group.items.map((x, idx) => (idx === i ? g : x)))}
            onRemove={() => setItems(group.items.filter((_, idx) => idx !== i))}
          />
        ) : (
          <ConditionRow
            key={i}
            index={i}
            value={item}
            onChange={(c) => setItems(group.items.map((x, idx) => (idx === i ? c : x)))}
            onRemove={() => setItems(group.items.filter((_, idx) => idx !== i))}
          />
        ),
      )}
      {group.items.length === 0 && <p className="text-[14px] text-slate">No conditions: this runs for every matching event.</p>}
      <div className="flex gap-2">
        <Button type="button" onClick={() => setItems([...group.items, emptyCondition()])}>
          Add condition
        </Button>
        {depth < MAX_DEPTH && (
          <Button type="button" variant="ghost" onClick={() => setItems([...group.items, { op: 'or', items: [emptyCondition()] }])}>
            Add group
          </Button>
        )}
      </div>
    </div>
  )
}
